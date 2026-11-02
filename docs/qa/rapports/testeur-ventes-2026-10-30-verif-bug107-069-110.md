# Vérification indépendante BUG-107 / BUG-069 / BUG-110 — testeur-ventes, 2026-10-30

Mission : vérification indépendante de 3 tickets passés à `CORRIGÉ` par `dev-frontend` le
2026-10-30 (mission conjointe BUG-107/BUG-069/BUG-110/BUG-052), sur `frontend/src/pages/dashboard/
Sales.tsx` et `frontend/src/pages/dashboard/Clients.tsx`. Aucun code applicatif modifié
(conformément à CLAUDE.md §7.2) — uniquement lecture de code, exécutions de vérification
(`tsc`, `build`, scripts Node/Python ponctuels non committés) et mise à jour de
`docs/qa/REGISTRE_BUGS.md`.

## Méthode

- Relecture ligne à ligne des diffs réels (pas de confiance au seul texte du rapport
  dev-frontend) pour les 3 tickets, dans les deux fichiers cités.
- `cd frontend && npx tsc --noEmit` puis `npm run build` — exécutés moi-même.
- Vérification numérique brute-force (Node + l'interpréteur réel du projet,
  `backend/.venv/Scripts/python.exe`) pour BUG-107, afin de ne pas se contenter d'une relecture
  visuelle de la formule.
- Pas de lancement de `npm run dev`/`runserver` dans cette session : la vérification de BUG-069/
  BUG-110 ne nécessitait pas d'inspection réseau dynamique pour conclure avec un niveau de
  confiance suffisant (changement de paramètre HTTP natif DRF déjà éprouvé, et branchement de
  prop déjà typé/`tsc`-vérifié) ; `backend` et `frontend` n'étaient pas déjà démarrés par un autre
  agent au moment de la vérification (`netstat` sur 8000/5173 vide).

## BUG-107 — Aperçu local Vente Soldée (75 %) — formule vérifiée exacte, mais défaut adjacent trouvé

- `effectiveUnitPrice()` dans `Sales.tsx` (l.244, `Math.round(bp.unit_price * 0.75)`) et dans
  `Clients.tsx` (l.217, même formule avec paramètre `soldee` explicite) appliquent exactement la
  même règle que `backend/sales/models.py::InvoiceLine.save()`
  (`SOLDEE_PRICE_RATIO = Decimal('0.75')`, `ROUND_HALF_UP`, arrondi **par ligne**).
- Vérification brute-force (`node -e`, 0 à 200 000 FC, tous les entiers) comparant `Math.round(x*0.75)`
  à une émulation de `ROUND_HALF_UP` : **0 écart**, y compris sur tous les cas d'arrondi exact à
  0,5 (ex. 150 FC → 112,5 → 113 des deux côtés). `0.75 = 3/4` est exactement représentable en
  binaire flottant, donc aucune dérive de précision n'est possible ici (contrairement à un ratio
  type `0.3`).
- Confirmation croisée avec les deux runtimes réels du dépôt (`node` et
  `backend/.venv/Scripts/python.exe`) sur un échantillon de prix pairs/impairs
  (333, 150, 115, 250, 501, 1 FC) : résultats identiques des deux côtés sur chaque valeur.
- Remise appliquée PAR LIGNE avant sommation dans les deux fichiers (`reduce` qui appelle
  `effectiveUnitPrice(bp)` ligne par ligne), conforme au serveur (une ligne = un arrondi, puis
  somme des `line_total` déjà arrondis).
- **Défaut distinct découvert, non couvert par le fix** : dans `Sales.tsx::confirmDelivery()`
  (construction du reçu réellement imprimé après confirmation de livraison, l.441-445), le prix
  unitaire par ligne est repris du catalogue (`bpMap[l.bread_price]?.unit_price`) et non du prix
  réellement facturé renvoyé par le serveur (`l.unit_price`, champ pourtant présent dans l'API).
  Pour une facture Vente Soldée livrée via la file d'attente de `Sales.tsx`, le reçu imprimé
  affiche donc un P.U./sous-total de ligne au prix plein, incohérent avec le total général affiché
  juste en dessous (lui correct, lu de `inv.order_total`). `Clients.tsx` n'a pas ce défaut (son
  reçu est construit directement depuis `effectiveUnitPrice()`, sans retomber sur le catalogue).
  **Nouveau ticket ouvert : BUG-111** (Majeur — document client incohérent, mais sans impact sur
  les montants réellement enregistrés côté serveur).
- **Décision : BUG-107 laissé à `CORRIGÉ`, pas passé à `VÉRIFIÉ`.** La formule elle-même, objet
  exact du ticket (« aperçu local AVANT soumission »), est conforme et vérifiée indépendamment ;
  mais l'objectif métier plus large (« le reçu doit refléter exactement ce que le serveur
  facture ») n'est pas pleinement atteint sur `Sales.tsx` tant que BUG-111 n'est pas traité — les
  deux sujets sont trop proches (même fonctionnalité, même fichier) pour clore l'un sans mentionner
  l'autre.

## BUG-069 — `page_size=10` sur la recherche prédictive de `Sales.tsx` — VÉRIFIÉ

- Confirmé par lecture directe : `Sales.tsx` l.209,
  `clientsApi.list({ search: debouncedClientSearch, page_size: '10' })`.
- Affirmation du rapport dev-frontend sur `Clients.tsx` (« pas le même défaut ») vérifiée
  indépendamment, pas acceptée sur la foi du texte : `Clients.tsx::loadClients()` alimente
  directement le tableau paginé principal de l'écran (bouton « Voir plus »), aucune liste de
  suggestions bornée (`.slice(0, 8)`) nulle part dans ce fichier, un seul site d'appel à
  `clientsApi.list`. Un `page_size` bas y aurait été une régression (clients correspondants
  mais invisibles) — confirmé exact.
- `npx tsc --noEmit` et `npm run build` : passent sans erreur.
- **BUG-069 passé à `VÉRIFIÉ`** dans le registre (table + fiche détaillée).

## BUG-110 — branchement `printerWidthMm` — VÉRIFIÉ (volet frontend)

- `Sales.tsx` l.741 et `Clients.tsx` l.1830 : les deux usages de `<ThermalReceipt .../>` portent
  désormais `printerWidthMm={window.kiese?.printerWidthMm ?? 80}` — confirmé par lecture directe,
  un seul site d'appel dans chaque fichier, aucun usage résiduel au défaut implicite.
- `frontend/src/types/kiese.d.ts` : `printerWidthMm?: 58 | 80` déjà déclaré (BUG-077), compatible
  avec la prop `ThermalReceipt`. Hors Electron, `window.kiese` est `undefined` → `?? 80` retombe
  proprement, sans plantage (confirmé par le typage et l'absence d'autre dépendance non protégée).
- `npx tsc --noEmit` et `npm run build` : passent sans erreur.
- Non exécuté (hors périmètre testeur-ventes) : vérification visuelle réelle sur poste desktop
  packagé en 58mm — reste à la charge de `testeur-materiel`, comme déjà indiqué par le ticket.
- **BUG-110 passé à `VÉRIFIÉ`** pour le volet frontend dans le registre (table + fiche détaillée).

## Nouveau ticket ouvert

- **BUG-111** (Majeur, OUVERT) — `Sales.tsx::confirmDelivery()` : le reçu imprimé après livraison
  affiche le prix catalogue (pas le prix réellement facturé) pour une facture Vente Soldée/Vente
  Cash. Voir fiche détaillée dans `docs/qa/REGISTRE_BUGS.md`. Reproduction précise, piste de
  correction documentée (non appliquée), à charge de `dev-frontend`.

## Commandes exécutées

```
cd frontend && npx tsc --noEmit        # OK, aucune erreur
cd frontend && npm run build           # OK, build réussi (warnings préexistants, sans rapport)
node -e "<brute-force Math.round vs ROUND_HALF_UP, 0..200000>"   # 0 écart
backend/.venv/Scripts/python.exe -c "<SOLDEE_PRICE_RATIO sample>" # identique au calcul Node
```

## Fichiers modifiés par cette mission

- `docs/qa/REGISTRE_BUGS.md` : statuts BUG-069 et BUG-110 passés à `VÉRIFIÉ` (table + fiches),
  fiche BUG-107 complétée (laissé `CORRIGÉ`, constat détaillé), nouvelle fiche et ligne de table
  pour `BUG-111`.
- Aucun fichier applicatif modifié.
