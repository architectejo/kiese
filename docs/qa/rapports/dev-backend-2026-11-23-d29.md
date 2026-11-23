# Dev backend d29 (2026-11-23)
Corriges : BUG-915 (reliquat), 929 (partiel), 930, 931, 932, 933, 934.
Fichiers : backend/clients/views.py, backend/sync/services.py, tests c10_v9 et clients_v7 (marques expectedFailure retirees).
Tests : 119 tests des 6 modules cibles, OK (1 expected failure restant) ; makemigrations --check : aucun changement.
Point ouvert : BUG-929 volet equipe, contradiction entre deux tests c10 ; role GERANT refuse comme facturier.
