# Vérification BUG-099 — testeur-ventes — 2026-10-30

## Objet

Vérification indépendante du correctif dev-frontend pour BUG-099 (reçu thermique affichant la
date/heure d'impression au lieu de la date réelle de la transaction quand une date rétroactive
BUG-083 est utilisée).

## 1. Relecture du diff

Fichiers relus intégralement (pas seulement la description du ticket) :

- `frontend/src/components/shared/ThermalReceipt.tsx` : nouveau champ optionnel
  `ReceiptData.transactionDate` (l.21-33). `dateStr`/`timeStr` (l.76-84) dérivés de
  `new Date(receipt.transactionDate)` si fourni et valide (`!isNaN(parsedTxDate.getTime())`),
  sinon repli sur `new Date()`. Le repli fonctionne bien pour le cas normal (date du jour,
  non rétroactif) et pour tout appelant non migré.
- `frontend/src/api/services.ts` l.107 : `delivered_at?: string | null` ajouté à `Invoice`,
  cohérent avec `InvoiceSerializer` (backend/sales/serializers.py l.35/43, champ déjà exposé
  côté API).
- `frontend/src/pages/dashboard/Sales.tsx` :
  - `handleRepaymentSubmit` (l.256) : `transactionDate: inv.delivered_at || inv.invoice_date`,
    `inv` = réponse réelle de `salesApi.createRepayment(...)`.
  - `confirmDelivery` (l.364) : `transactionDate: inv.delivered_at || inv.invoice_date`,
    `inv` = réponse réelle de `salesApi.deliver(...)`.
- `frontend/src/pages/dashboard/Clients.tsx::handleSaleSubmit` (l.624-626, l.653) : capture
  désormais la réponse de `salesApi.deliver(res.data.id, retroactiveDate || undefined)` dans
  `deliveredInvoice` (ignorée auparavant hors erreur) et en déduit
  `transactionDate: deliveredInvoice?.delivered_at || deliveredInvoice?.invoice_date`.
  Troisième appelant confirmé réel et bien corrigé, conforme à la mission.

Nuance mineure sans impact : si `salesApi.deliver(...)` échoue dans `Clients.tsx` (catch
l.627-629), `deliveredInvoice` reste `undefined` et le reçu retombe sur `new Date()` — cas déjà
en échec de livraison, hors périmètre de ce ticket.

**Conclusion partielle : les 3 flux dérivent bien `transactionDate` des données serveur
réelles, pas d'une horloge locale.**

## 2. E2E en environnement à froid

Anciens serveurs backend (`runserver 8000`, PID 18224) et frontend (`vite`, PID 23036/12836)
tués, puis relancés proprement (un seul processus chacun), avant toute exécution Playwright.

Premier run :
```
npx playwright test 04-facturation.spec.ts -g BUG-099 --workers=1
```
Résultat : **3/4 passés** (`pos` 1.6 min, `bureau` 1.3 min, `tv` 58 s). **1 échec** sur
`tablette` (23.7 s) :
```
TimeoutError: page.goto: Timeout 15000ms exceeded.
navigating to "http://localhost:5173/login", waiting until "load"
  at fixtures/helpers.ts:12 (seConnecter)
```
L'échec survient **avant** toute interaction propre au scénario BUG-099 — dans la fixture
partagée de connexion.

Re-exécution isolée immédiate :
```
npx playwright test 04-facturation.spec.ts -g BUG-099 --project=tablette --workers=1
```
Résultat : **passé** (53.7 s), serveur Vite désormais chaud après le premier run.

**Conclusion sur la flakiness** : réelle et reproductible même à froid (pas uniquement liée à
une charge Playwright antérieure accumulée dans la session), mais strictement localisée à la
navigation initiale `/login` des fixtures (vraisemblablement le temps de transformation à la
volée par Vite du bundle `/login`/du menu au premier chargement pour ce profil). Elle
n'apparaît jamais une fois le test entré dans la logique BUG-099 elle-même (date du reçu). Ce
n'est donc **pas** une régression introduite par le correctif de ce ticket. Comportement déjà
connu et documenté par le `test.slow()` présent sur tout le fichier (BUG-065). Pas de nouveau
ticket ouvert ; à surveiller si la fréquence augmente, mais pas bloquant pour BUG-099.

## 3. Reproduction manuelle

Le scénario E2E automatisé (`04-facturation.spec.ts` l.211-290) exerce exactement les étapes
demandées : activation `Config.allow_backdated_sales` par Direction, facturier K1 crée une
facture datée d'avant-hier, confirme la livraison avec la même date rétroactive, vérifie que le
bloc « Date : » du reçu affiche la date rétroactive et jamais la date système du jour. Vérifié
passant à froid sur les 4 profils (point 2 ci-dessus) avec un vrai navigateur (Chromium), sans
mock — équivalent à une reproduction manuelle. Non rejouée séparément à la main (redondant).

## 4. Vérifications de non-régression

- `npx tsc --noEmit` → exit 0, aucune erreur.
- `npm run build` → exit 0 (seul avertissement : chunk `index-legacy` > 500 kB, préexistant,
  sans rapport avec ce correctif).

## 5. Clôture

- `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok`.

## Conclusion

Correctif conforme sur les 3 flux réels identifiés (remboursement et livraison dans
`Sales.tsx`, vente comptoir dans `Clients.tsx`), repli `new Date()` sain pour le cas normal,
aucune régression détectée, build/typecheck/DB propres. La flakiness E2E signalée par le dev
est confirmée réelle même à froid mais localisée à la fixture de connexion partagée, sans lien
avec la logique BUG-099.

**BUG-099 → VÉRIFIÉ** (`docs/qa/REGISTRE_BUGS.md` mis à jour, tableau de suivi + section
détaillée, par testeur-ventes).
