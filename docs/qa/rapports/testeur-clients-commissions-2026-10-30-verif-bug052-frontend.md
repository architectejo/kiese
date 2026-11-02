# Rapport — Vérification indépendante du volet frontend de BUG-052

- Agent : testeur-clients-commissions
- Date : 2026-10-30
- Portée : `frontend/src/pages/dashboard/Sales.tsx`, `frontend/src/pages/dashboard/Clients.tsx` (le volet backend était déjà `VÉRIFIÉ`)

## Méthode

1. Lecture directe du code (pas confiance au rapport de `dev-frontend`) :
   - `Sales.tsx` : état `venteSoldee` (préexistant) et nouvel état `commissionExempt` (l.115-119), calcul de prix (l.244), reset (l.253), payload (l.396-399), UI des deux cases (l.814-850).
   - `Clients.tsx` : état `sansCommission`/`venteSoldee` (l.209-211), calcul de taux (l.606), BP (l.609-611), payload (l.650-653), UI des deux cases (l.1787-1817).
2. Vérification explicite de l'indépendance :
   - Aucun `onChange`/`onClick` d'une case ne touche l'état de l'autre dans les deux fichiers (contrairement à l'ancien code de `Clients.tsx` qui, selon le rapport de `dev-frontend`, avait une exclusion mutuelle — confirmé absente dans le code actuel).
   - Les deux cases restent cochables simultanément sans blocage UI.
3. Vérification du payload :
   - `Sales.tsx` : `...(venteSoldee ? { commission_rate: '0.00', is_soldee: true } : {})` et `...(commissionExempt ? { commission_exempt: true } : {})` — deux spreads strictement séparés.
   - `Clients.tsx` : `...(venteSoldee ? { is_soldee: true } : {})` et `...(sansCommission ? { commission_exempt: true } : {})` — même séparation, plus `commission_rate` calculé côté client pour l'aperçu (`(sansCommission || venteSoldee) ? 0 : saleClient.commissionRate`), sans effet de bord sur `is_soldee`.
   - Confirmé : `commissionExempt`/`sansCommission` n'écrit ni ne lit jamais `is_soldee`, et réciproquement.
4. Scénario de bout en bout via les tests backend déjà écrits par `dev-backend` (reproduisent exactement les deux payloads envoyés par l'UI) :
   ```
   backend/.venv/Scripts/python.exe manage.py test sales.tests.test_invoices.CommissionExemptTests -v 2
   ```
   → 5/5 `OK`. En particulier :
   - `test_commission_exempt_forces_zero_commission_at_full_price` : équivalent du payload envoyé par « Vente sans commission » seule cochée → `unit_price` inchangé (500, prix catalogue plein), `commission_rate=0.00`, `order_total` plein, BP suit normalement (`debt_after = debt_before + order_total - payment_amount`, vérifié dans `test_commission_exempt_bp_follows_order_total_normally`).
   - `test_is_soldee_and_commission_exempt_are_independent_and_combinable` : équivalent du payload envoyé par les deux cases cochées ensemble → `unit_price=375` (-25% catalogue), `commission_rate=0.00`, `current_debt` inchangée (BP gelée par `is_soldee`).
   - Ces deux comportements système sont bien ceux déclenchés par les payloads réels construits par le frontend.
5. Vérification build/types :
   ```
   cd frontend && npx tsc --noEmit    → aucune erreur
   npm run build                      → succès (warnings de taille de chunk préexistants, sans rapport)
   ```
6. Vérification des libellés affichés (lecture littérale) :
   - `Sales.tsx` : « Vente Soldée / Vente Cash — -25% sur le prix catalogue, 0% commission, manquant non imputé en BP » (orange) vs « Vente sans commission (25%) — geste commercial ponctuel, prix et BP inchangés » (bleu), + note combinée quand les deux sont cochées.
   - `Clients.tsx` : mêmes libellés et même note combinée dans la modale « Enregistrer commande ».
   - Le « (25%) » dans « Vente sans commission (25%) » reprend littéralement remarque.md l.190 (« vente sans commission de 25 % ») — ce n'est pas une confusion introduite par le frontend, c'est la formulation métier elle-même ; les textes d'aide et les couleurs différencient clairement les deux cases pour un facturier non averti.

## Résultat

Aucun défaut trouvé. Les deux cases sont bien indépendantes et combinables dans `Sales.tsx` et `Clients.tsx`, le payload envoyé à `salesApi.create()` contient `commission_exempt: true/false` sans jamais toucher `is_soldee` par effet de bord, et les comportements système « CM=0 seul » / « CM=0 + is_soldee combinés » sont exactement ceux prouvés côté backend.

`BUG-052` passé à **VÉRIFIÉ** intégralement (backend et frontend) dans `docs/qa/REGISTRE_BUGS.md` :
- Ligne de synthèse (tableau) mise à jour.
- Fiche détaillée : en-tête mis à jour, nouvelle section « Vérification (frontend) » ajoutée sous la section « Correction (frontend) » existante.

## Fichiers consultés (lecture seule, aucun fichier applicatif modifié)

- `D:\Projects\kiesse\frontend\src\pages\dashboard\Sales.tsx`
- `D:\Projects\kiesse\frontend\src\pages\dashboard\Clients.tsx`
- `D:\Projects\kiesse\backend\sales\tests\test_invoices.py`
- `D:\Projects\kiesse\backend\sales\views.py`
- `D:\Projects\kiesse\backend\sales\models.py`
- `D:\Projects\kiesse\backend\sales\serializers.py`

## Fichier modifié

- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (registre des bugs uniquement, conformément à la règle testeur CLAUDE.md §7)
