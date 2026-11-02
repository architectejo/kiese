# Rapport dev-backend — Correction BUG-070 (2026-10-23)

## Ticket traité
**BUG-070** (Majeur → CORRIGÉ) — `FinancialYearViewSet.summary()` : N+1 sur les
`CommissionPeriod` (2 requêtes séparées `.aggregate()` + `.count()` par période, boucle Python).

## Cause
`backend/finance/views.py::FinancialYearViewSet.summary()` itérait `for period in
qs.order_by(...)` et, pour chaque `CommissionPeriod`, exécutait un `.aggregate()` puis un
`.count()` séparé sur `ClientCommission.objects.filter(period=period)` — 194 requêtes mesurées
par testeur-charge pour 96 périodes (8 nœuds × 12 mois), 538,8 ms médiane. Défaut invisible dans
les mesures précédentes (BUG-064/BUG-066) car le script de charge original ne seedait aucune
`CommissionPeriod`/`ClientCommission` (queryset vide, boucle jamais exécutée).

## Correction
Remplacement par une seule requête groupée :
```python
agg_rows = ClientCommission.objects.filter(period__in=periods).values('period').annotate(
    total_orders=Sum('order_value'),
    total_cm=Sum('commission_gross'),
    total_net=Sum('net_payable'),
    total_debt=Sum('deduction_debt'),
    client_count=Count('id'),
)
agg_by_period = {row['period']: row for row in agg_rows}
```
Les résultats sont réassociés en mémoire aux objets `CommissionPeriod` déjà chargés
(`periods = list(qs.order_by('month', 'node__code'))`). Format de réponse JSON strictement
identique (mêmes clés, mêmes valeurs `str(Decimal)`, mêmes zéros par défaut via `.get(...) or 0`).

**Fichier modifié** : `D:\Projects\kiesse\backend\finance\views.py` (import `Count` ajouté ligne 4 ;
méthode `summary()` réécrite).

## Mesures
Script de mesure isolé (base SQLite temporaire, jamais `db.sqlite3` réel), reconstruit à partir du
script décrit par testeur-charge dans son rapport (8 nœuds × 12 mois × 2 ans = 192
`CommissionPeriod`, 1 920 `ClientCommission`, `is_paid=True`) :
- **Avant** (mesure testeur-charge, BUG-070) : 538,8 ms médiane (min 435,4/max 747,3),
  194 requêtes SQL, 96 périodes pour l'année demandée.
- **Après** (mesure dev-backend, même volume) : **30,9 ms médiane** (min 28,1/max 38,5),
  **3 requêtes SQL** (indépendant du nombre de périodes), 96 lignes retournées, contenu vérifié
  (ex. `{'node_code': 'B1', 'month': 1, 'client_count': 20, 'total_orders': '5666428', ...}`).

Script scratchpad (hors dépôt) :
`C:\Users\MUABIL~1\AppData\Local\Temp\claude\d--Projects-kiesse\8fca5c01-a750-49dc-ad35-bcecf262b57d\scratchpad\mesure_bug070.py`.

## Tests
`python manage.py test finance sales production treasury commissions` → **136 tests, 2 échecs**,
strictement les deux déjà connus et hors mandat (**BUG-068**, date codée en dur dans les tests
trésorerie, décalage de date système) :
- `treasury.tests.test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario`
- `treasury.tests.test_reports_closures.CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses`

Aucune régression nouvelle liée à BUG-070.

`python manage.py makemigrations --check --dry-run` : dérives pré-existantes détectées, **sans
rapport avec ce ticket** (ni avec `finance`, module non touché par ces modèles) :
- `production` : `0013_alter_breadtransfer_transfer_status_and_more` (`transfer_status`,
  id de `breadtransferline`/`consumablecount`).
- `clients` : `0007_remove_socialcontribution_unique_social_contribution_and_more`
  (migration de `unique_together` vers `UniqueConstraint`).
- `treasury` : `0011_remove_dailysavings_unique_daily_savings_node_date_and_more` (idem).

`backend/finance/views.py` ne modifie aucun modèle : ces dérives existaient déjà avant ma
correction. Signalé ici pour le coordinateur, à tracer séparément si pas déjà fait — je n'ai créé
aucune migration (fichiers autorisés : `backend/finance/views.py`,
`docs/qa/REGISTRE_BUGS.md` uniquement).

## Impact API / frontend
**Aucun.** Format de réponse JSON de `GET /api/finance/years/summary/` inchangé (mêmes clés,
mêmes types `str`, même tri). Aucun ticket `dev-frontend` nécessaire.

## Ticket
BUG-070 passé à **CORRIGÉ** dans `docs/qa/REGISTRE_BUGS.md` avec fiche de correction détaillée
(cause, correctif, mesures avant/après, tests, migrations). Non passé à VÉRIFIÉ (conformément à
CLAUDE.md §7) — en attente de vérification indépendante par testeur-charge ou le coordinateur.

## Risques / suite
- Les 3 dérives de migrations pré-existantes (production/clients/treasury) ne sont pas de mon
  mandat sur ce ticket ; à vérifier si déjà trackées dans le registre, sinon un ticket dédié
  devrait être ouvert.
- BUG-068 (date codée en dur, tests trésorerie) reste ouvert, hors périmètre de cette session.
