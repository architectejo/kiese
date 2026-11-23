# Rapport dev-backend D12 (Dev B) - 2026-11-22

Tickets traités : BUG-761, BUG-762 -> CORRIGÉ (non vérifiés).

- BUG-761 : `sync/models.py::NodeAuthToken.issue_for_node` remplace la ligne OneToOne existante (atomic + select_for_update : nouveau hash, révocation levée, issued_at rafraîchi). Ancien jeton -> 401, nouveau -> 200. Pas de migration.
- BUG-762 : helper `core/mixins.py::get_json_object(request)` (400 français `{"detail": ...}`), utilisé dans commissions (set_manuel, mark_paid, generate), treasury (closures validate, reject), clients (bulk_delete, bulk_move).
- Tests : marques @expectedFailure retirées sur test_BUG_761 et test_BUG_762 (import `expectedFailure` laissé en place, inutilisé).

Risques : la rotation efface `last_used_at` ; un jeton révoqué par l'admin puis réémis redevient actif (comportement voulu).

## Ajouts (message coordinateur)
- BUG-751 : doublon de 762, même helper, + `bulk_create_month`. CORRIGÉ.
- BUG-752 : lignes de distribution close immuables (création, modification, suppression) -> 400. CORRIGÉ.
- BUG-753 : refresh_indices / auto_populate_lines atomiques, bornes 10^8 (`_check_line_columns`) -> 400 français. CORRIGÉ.
- Marques @expectedFailure retirées dans test_clients_v4 et test_commissions_v4 (imports laissés).

## Tests
- Run large (core b4_v4 + sync + commissions + clients + treasury c6_v5, 826 tests) : 1 échec `sync.tests.test_verif_charge_v3...test_course_generate_deux_boulangeries_double_retenue` (test d'interleaving par threads ; passe seul, OK ; run fait en parallèle d'un autre run, machine chargée -> flaky, à surveiller) ; 2 « unexpected success » = les 2 tests BUG-751 commissions, dont la marque a été retirée ensuite.
- Run ciblé après tous les correctifs (clients v4, commissions v4, core b4_v4) : 108 tests OK. `makemigrations --check` : aucun changement.
