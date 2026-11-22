# Rapport dev-backend, 2026-11-22 (d6)

Tickets CORRIGÉS : BUG-731 (réouvert), 760, 780, 781, 782, 784. BUG-783 : À CLARIFIER (non codé).
Détail, cause et tests : section « Dev-backend d6 » de `docs/qa/REGISTRE_BUGS.md`.

Fichiers : `backend/sync/services.py`, `backend/sync/views.py`, `backend/sync/desktop_client.py`, `backend/sync/management/commands/sync_now.py`, `backend/commissions/views.py`, `backend/clients/views.py`. Aucune migration.

Tests : `sync` + `commissions.tests.test_commissions_v2` : 243 tests OK (5 expected failures restants, dont BUG-783). `core...ClientsBulk` + `clients` : 280 tests, BUG-760 vert ; 1 « unexpected success » dans `clients/tests/test_clients_v3.py::CaisseV3Tests::test_montant_exposant_gigantesque_400` (fichier d'un autre testeur, `@expectedFailure` à retirer par lui). `makemigrations --check` : aucun changement.

Risques : verrou `select_for_update` sans effet sous SQLite (filet par `created_at`/`pk` ajouté) : rejouer BUG-782 sous PostgreSQL. Le curseur de pull est en mémoire + `sync_pull_cursor.json` : supprimer ce fichier force un pull complet.

COMPTABLE sur commissions : À CLARIFIER (tests existants lui font écrire `deduction_*` et supprimer), rien codé.
