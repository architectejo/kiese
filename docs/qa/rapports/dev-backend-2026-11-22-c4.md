# Rapport dev-backend — 2026-11-22 (c4)

## Tickets passés à CORRIGÉ
- **BUG-560** : (a) `?node=` invalide sur treasury `journal/`, `journal/monthly_report/`, `savings/`, `savings/monthly_total/` (siège) -> 400 `{"detail"}` via `resolve_node_param` (helper `_hq_node_filter_id` dans `treasury/views.py`). (b) doublon `POST treasury/reports/` : `perform_create` contrôle (node, facturier, team réelle, date) avant `save` -> 400 « Vous avez déjà un rapport… », aucun doublon.
- **BUG-561** : `blockchain/views.py::run_check` : corps non objet (liste, nombre, chaîne) -> 400.
- **BUG-563** : `treasury/versements.py` : `Node.objects.exclude(code='SIEGE')` pour le siège. Décision : les nœuds inactifs réels ne sont pas exclus (une boulangerie désactivée peut encore avoir à verser) ; à confirmer si le client veut l'inverse.

## Tests
- Nouveau : `backend/treasury/tests/test_bug560_561_563.py` (5 tests ; 4 échouent sans la correction, passent avec).
- `python manage.py test treasury blockchain finance --noinput` : 388 tests OK (expected failures=2, préexistants).
- `core.tests.test_verif_c5_routes_noeuds_c` : 67 tests, 4 « unexpected success » = les marques à retirer.
- `check` : OK ; `makemigrations --check --dry-run` : No changes.

## Marques `@expectedFailure` à retirer par le testeur (dans `backend/core/tests/test_verif_c5_routes_noeuds_c.py`)
- `test_BUG_560_treasury_journal_savings_node_param`
- `test_BUG_560_duplicate_report_is_not_500`
- `test_BUG_561_run_check_list_body`
- `test_BUG_563_versements_hq_sees_real_bakeries_only`

## Impact / risques
- Contrat d'API : uniquement des 500 devenus 400 `{"detail"}` ; versements ne liste plus SIEGE (compteurs corrigés). Pas d'impact frontend attendu.
- `?node=<code>` (ex. `p1`) sur les listes `journal/` et `savings/` reste refusé en 400 par django-filter (comportement préexistant, seule la clé primaire est acceptée sur ces listes).
- Aucun commit, aucun push. Registre : les 3 tickets en CORRIGÉ (jamais VÉRIFIÉ).
