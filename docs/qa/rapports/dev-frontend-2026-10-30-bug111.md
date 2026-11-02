# Rapport dev-frontend — 2026-10-30 — BUG-111

## Ticket traité
BUG-111 — `Sales.tsx::confirmDelivery()` : le reçu imprimé après livraison affichait le prix
catalogue (pas le prix réellement facturé) pour une facture Vente Soldée/Vente Cash.

## Cause
Dans `frontend/src/pages/dashboard/Sales.tsx::confirmDelivery()` (l.441-445), la construction de
`receiptLines` (lignes du reçu réellement imprimé après confirmation de livraison) recalculait le
prix unitaire depuis le catalogue local `bpMap[l.bread_price]?.unit_price` au lieu d'utiliser
`l.unit_price`, le prix réellement facturé et **figé côté serveur** à la création de la ligne
(`backend/sales/models.py::InvoiceLine.save()`, CLAUDE.md §4). Pour une facture non remisée,
catalogue == prix facturé donc le défaut était invisible ; pour une Vente Soldée/Vente Cash (prix à
75 %, CLAUDE.md §5.1), le reçu affichait un P.U./sous-total de ligne au prix plein, incohérent avec
le total général (`orderTotal`, lui lu correctement de `inv.order_total`).

Reproduction effectuée par lecture de code et de l'API (`InvoiceLineSerializer` / `services.ts::
InvoiceLine.unit_price?: string`) ; aucun serveur de dev n'a été démarré dans cette session (le
défaut était déterministe à la lecture du code et confirmé indépendamment par `testeur-ventes` en
vérifiant BUG-107, avec étapes de reproduction déjà détaillées dans la fiche).

## Correctif appliqué
Fichier modifié : `frontend/src/pages/dashboard/Sales.tsx` (uniquement), fonction
`confirmDelivery()`.

Avant :
```ts
const receiptLines: ReceiptLine[] = (inv.lines || []).map(l => ({
  label: bpMap[l.bread_price]?.label || l.bread_price_display || l.bread_price,
  qty: l.quantity,
  unitPrice: bpMap[l.bread_price]?.unit_price || parseInt(l.bread_price_display || '0'),
}));
```

Après :
```ts
// BUG-111 : utiliser le prix réellement facturé et figé par le serveur (InvoiceLine.unit_price,
// backend/sales/models.py::InvoiceLine.save()) plutôt que le prix catalogue courant (bpMap),
// sinon le reçu d'une vente soldée affiche un P.U./sous-total de ligne au prix plein alors que
// le total général (inv.order_total) reste correct.
const receiptLines: ReceiptLine[] = (inv.lines || []).map(l => ({
  label: bpMap[l.bread_price]?.label || l.bread_price_display || l.bread_price,
  qty: l.quantity,
  unitPrice: l.unit_price != null ? parseFloat(l.unit_price) : (bpMap[l.bread_price]?.unit_price || parseInt(l.bread_price_display || '0')),
}));
```

`InvoiceLine.unit_price` est typé `string | undefined` dans `src/api/services.ts` (chaîne décimale
DRF, conforme à l'habitude Django pour les `Decimal`). Il est parsé avec `parseFloat` uniquement
pour l'affichage simple d'un champ `ReceiptLine.unitPrice: number` dans le reçu — aucun calcul
monétaire composé en aval dans ce composant n'utilise cette valeur de façon risquée pour la
précision. Le repli sur `bpMap`/`bread_price_display` est conservé si le champ serveur est
absent/vide, pour ne pas casser l'affichage sur une réponse API incomplète.

## Hors périmètre (volontairement non touché)
- `Clients.tsx` : non modifié, déjà correct (construit son reçu via `effectiveUnitPrice()`,
  confirmé par `testeur-ventes`).
- Défaut annexe signalé dans la fiche BUG-111 (carte de la file d'attente, `mapInvoice()` /
  rendu l.601-611 de `Sales.tsx`) : purement visuel sur la carte (le total de carte, basé sur
  `inv.order_total`, reste correct) — non corrigé ici, hors du périmètre strict donné (reçu
  réellement imprimé). À ouvrir en ticket séparé si jugé nécessaire par le coordinateur ou
  `testeur-ventes`.
- `backend/` non touché.

## Vérifications effectuées
- `cd frontend && npx tsc --noEmit` → aucune erreur.
- `cd frontend && npm run build` → succès (seul avertissement préexistant et sans rapport avec ce
  correctif : taille du chunk JS legacy > 500 kB).
- Aucun test E2E existant ne couvre ce parcours précis (`e2e/tests/04-facturation.spec.ts`,
  `08-facturation-serie.spec.ts` ne vérifient pas le prix unitaire affiché sur le reçu imprimé après
  livraison) ; aucun n'a été ajouté dans cette session (hors périmètre strict : seuls `Sales.tsx`,
  le registre et ce rapport étaient autorisés). Étapes de vérification manuelle détaillées dans la
  fiche BUG-111 du registre, à charge de `testeur-ventes`.

## Registre
`docs/qa/REGISTRE_BUGS.md` : BUG-111 passé `OUVERT` → `CORRIGÉ` (tableau de suivi ligne 122 + fiche
détaillée ~l.8728 avec section « Correction appliquée — dev-frontend, 2026-10-30 »). Conformément à
CLAUDE.md §7, je n'ai pas passé le ticket à `VÉRIFIÉ` : seul `testeur-ventes` (ouvreur) ou le
coordinateur peut le faire.

## Fichiers modifiés
- `D:\Projects\kiesse\frontend\src\pages\dashboard\Sales.tsx`
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md`
- `D:\Projects\kiesse\docs\qa\rapports\dev-frontend-2026-10-30-bug111.md` (ce rapport)
