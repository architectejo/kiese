# Rapport dev-backend — BUG-066 — 2026-10-23

## Mission
Corriger BUG-066 (Majeur, OUVERT) : `FinancialYearViewSet.comparative()` (`backend/finance/views.py`)
restait à 921-1025 ms médiane / 32 requêtes SQL malgré la correction BUG-064 (index sur `Invoice`
uniquement).

## Analyse
Relecture de `_income_statement_for_year()`, `_cashflow_for_year()`, `_balance_sheet_for_year()` :
- `_income_statement_for_year()` faisait 4 `.aggregate()` séparés pour le revenu par catégorie de
  pain (`InvoiceLine.filter(invoice__invoice_date__year=, invoice__status='DELIVERED')` puis
  `.filter(bread_price__category=...)` × 4) et 4 autres séparés pour le COGS par type de
  consommable (`ConsumableMovement.filter(created_at__year=, movement_type='ENTRY')` puis
  `.filter(stock__consumable_type=...)` × 4) — 8 requêtes qui rescannent chacune la même jointure.
  Appelée 2 fois dans `comparative()` (année N et N-1) = 16 requêtes.
- `_cashflow_for_year()` faisait 2 `.aggregate()` séparés (`total_in`, `total_out`) sur le même
  queryset au lieu d'un seul avec deux clés.
- Vérification empirique (`qs.query`) : Django traduit bien `__year=` en `BETWEEN` (plage directe)
  pour un `DateField`/`DateTimeField` — un index classique sur la colonne de date **est** utilisable,
  contrairement à ce qu'affirmait la fiche d'ouverture du ticket. Les tables `ConsumableMovement`,
  `LocalExpense`, `ClientCommission` n'avaient toutefois aucun index sur leurs colonnes de date/type
  filtrées.
- Le scénario de charge existant (`backend/scripts/charge/volumetrie.py`) ne seed pas
  `ConsumableMovement`/`LocalExpense`/`ClientCommission` : la quasi-totalité du gain mesuré vient
  donc de la fusion des requêtes sur `InvoiceLine`, pas des nouveaux index (qui restent nécessaires
  pour la volumétrie réelle, non couverte par ce script).

## Corrections appliquées
1. `backend/finance/views.py` :
   - `_income_statement_for_year()` : les 4 agrégats de revenu fusionnés en un seul
     `.aggregate(revenue_300=Sum('line_total', filter=Q(bread_price__category='MINI')), ...)` (1
     requête, `SUM(CASE WHEN ...)` côte à côte) ; même fusion pour les 4 coûts de consommables.
   - `_cashflow_for_year()` : `total_in`/`total_out` fusionnés en un seul `.aggregate()`.
   - Aucun changement de comportement ni de format de réponse (mêmes clés, mêmes valeurs
     `Decimal`) — vérifié par les tests `finance` existants (`income_statement`, `cashflow`,
     `balance_sheet`, `comparative`).
2. Index ajoutés (`Meta.indexes` + migration dédiée par app, modèle `Invoice` non touché) :
   - `production.ConsumableMovement` : `['movement_type', 'created_at']`
     (`production/migrations/0012_bug066_consumablemovement_index.py`).
   - `treasury.LocalExpense` : `['date']`
     (`treasury/migrations/0010_bug066_cashbook_localexpense_indexes.py`).
   - `treasury.CashbookEntry` : `['date', 'created_at']` (même migration que ci-dessus).
   - `commissions.ClientCommission` : `['period', 'is_paid']`
     (`commissions/migrations/0003_clientcommission_comm_clico_period_paid_idx.py`).
   - Chaque migration est isolée au seul `AddIndex` : `makemigrations` proposait par ailleurs,
     sur ces mêmes apps, la dérive préexistante BUG-057 (`AlterField id`/`transfer_status`,
     `unique_together`) — délibérément exclue de ces migrations (hors mandat, ticket séparé déjà
     ouvert).

## Mesures (script `backend/scripts/charge/volumetrie.py --days 10 --invoices-per-day-per-node 300
--n-clients 700`, base SQLite temporaire isolée, jamais `db.sqlite3`, 24 000 factures/48 077
lignes/8 nœuds/700 clients)
| Endpoint | Avant (testeur-charge) | Après (dev-backend) |
|---|---|---|
| `Finance — comparative()` | 921,1 — 1 025,0 ms médiane / 32 requêtes | **341,5 ms** médiane (min 330,9/max 365,3) / **18 requêtes** |

Les 6 autres endpoints mesurés par le même script restent tous < 100 ms (recherche client 84,6 ms,
liste factures filtrée 95,1 ms, liste non filtrée 78,2 ms, commissions summary 9,0 ms, production
reconciliation 23,3 ms, livre de caisse 31,9 ms) — aucune régression.

## Tests
- `python manage.py test finance sales production treasury commissions` : 136 tests, **2 échecs
  préexistants et sans rapport** avec cette correction :
  - `treasury.tests.test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario`
  - `treasury.tests.test_reports_closures.CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses`
  Cause : date codée en dur (`'2026-10-22'`) dans ces deux tests, qui correspondait à « aujourd'hui »
  au moment de leur écriture. `Invoice.invoice_date` est `auto_now_add` (vraie date du jour,
  2026-10-23 dans cette session) : le filtre par date codée en dur ne retrouve plus les factures
  créées dynamiquement par le test. Reproduit en isolant `test_full_day_scenario` seul (1 test, même
  échec) — confirme l'absence de lien avec les index/requêtes modifiés ici. Signalé ci-dessous pour
  ticket séparé, non corrigé (hors fichiers autorisés pour BUG-066, et un dev-backend ne modifie pas
  un test hors mandat).
- `python manage.py makemigrations --check --dry-run` : affiche uniquement la dérive BUG-057
  préexistante (`production`/`clients`/`treasury`) — aucune dérive nouvelle.

## Ticket ouvert
Un nouveau ticket (date codée en dur `'2026-10-22'` dans
`treasury/tests/test_cashbook_level3.py`/`treasury/tests/test_reports_closures.py`) est documenté
dans la fiche de correction BUG-066 du registre (`docs/qa/REGISTRE_BUGS.md`), à charge de
`testeur-tresorerie` ou `dev-backend` sur mandat dédié. Pas de ticket `dev-frontend` : aucun contrat
d'API changé.

## Statut
BUG-066 passé à **CORRIGÉ** dans `docs/qa/REGISTRE_BUGS.md` (fiche détaillée ajoutée). Je ne l'ai
PAS passé à VÉRIFIÉ — seul `testeur-charge` ou le coordinateur peut le faire, par re-mesure
indépendante.

## Fichiers modifiés
- `backend/finance/views.py`
- `backend/production/models.py` + `backend/production/migrations/0012_bug066_consumablemovement_index.py`
- `backend/treasury/models.py` + `backend/treasury/migrations/0010_bug066_cashbook_localexpense_indexes.py`
- `backend/commissions/models.py` + `backend/commissions/migrations/0003_clientcommission_comm_clico_period_paid_idx.py`
- `docs/qa/REGISTRE_BUGS.md`

## Risques / points d'attention pour la suite
- Le gain mesuré (921→341 ms) tient surtout à la fusion des requêtes sur `InvoiceLine`. À l'échelle
  d'un exercice complet (~876 000 factures/an), le ticket d'ouverture recommandait d'envisager une
  dénormalisation (agrégats mensuels/annuels pré-calculés) si le volume réel dépasse largement ce
  qui a été testé ici (10 jours) — non traité dans ce ticket (hors périmètre, à rouvrir si
  nécessaire après mesure réelle).
- Les nouveaux index sur `ConsumableMovement`/`LocalExpense`/`ClientCommission` n'ont pas pu être
  validés sous charge réelle faute de données dans le script existant pour ces tables — comportement
  attendu correct (vérifié par `EXPLAIN`/traduction `BETWEEN` de Django et par les tests unitaires
  `finance`), mais pas mesuré en volumétrie comme `InvoiceLine`.
- Ticket date codée en dur (voir ci-dessus) à ouvrir formellement par le coordinateur/testeur
  concerné ; non bloquant pour BUG-066 mais à traiter avant que la suite ne redevienne rouge chaque
  jour qui passe.
