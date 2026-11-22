# dev-backend (Dev B) - 2026-11-22 b3

## Tickets CORRIGÉS (à vérifier par Dev C)
- BUG-531 (bloquant) : `clients/views.py::bassins` borné à `user.node_id` pour un non-siège (`node` ignoré), compte sans boulangerie -> `rows` vide, `node` invalide -> 400 `{"detail"}`, `month`/`year` non entiers -> 400.
- BUG-532 : nouveau helper `core/mixins.py::parse_node_param` (entier 1..2^31-1, sinon 400 français), appliqué à `deficit_report`, `bassins`, `periods/history`.
- BUG-530 : `commissions/views.py::history` : `node` via helper, `months` non entier ou < 1 -> 400 (Edit ciblé sur cette seule fonction).

## Tests
`clients/tests/test_bug531_532_bassins_isolation.py` (8), `commissions/tests/test_bug530_history_params.py` (3) ; avec `test_bug521_deficit_report_isolation` : 16 tests OK. Suites complètes non lancées (consigne).

## Autres @action de ClientViewSet
Relues : `merge`/`move` etc. lisent `node` dans le corps via `Node.objects.get(pk=...)` (HQ) ; non modifiées. À signaler : `move_clients` avec `node` non entier/géant n'a pas été sondé.

## Risques / remarques
- `history` reste réservé au siège (get_permissions renvoie IsHeadquarters pour l'action, malgré `IsGerant` déclaré) : comportement préexistant, non modifié.
- Un autre agent édite commissions/views.py : vérifier qu'il n'y a pas de conflit.
- Pas de commit.
