# Dev backend d30 - 2026-11-23

Tickets CORRIGÉ : BUG-935, BUG-936 (backend/sync/services.py::_check_facturier_report).
- 935 : rôles admis FACTURIER/GERANT/COMPTABLE/DIRECTION/ADMIN, même nœud que le rapport.
- 936 : facturier inactif accepté (même nœud, rôle admis) ; inconnu/forgé/autre nœud/livreur refusés.
- BUG-937 : décision coordinateur appliquée, test c10 `test_facturier_d_une_autre_equipe_refuse` retiré.
- Tests c10/c11 contradictoires adaptés : `test_facturier_non_facturier_refuse` (liste réduite au livreur), `test_929_forge...` (sans inactif ni comptable). À valider par le testeur.
- Suites lancées : c11, c10, d27, sync v5 (70 tests, OK après adaptation), makemigrations --check OK.
