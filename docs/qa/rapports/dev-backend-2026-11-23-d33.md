# Dev backend d33 (2026-11-23)

## BUG-951 (CORRIGE)
Cause : la garde du push d'identite comparait a `Client.updated_at`, que chaque mouvement de dette fait avancer.
Correction : nouveau champ `Client.identity_updated_at` (nullable, migration additive `clients/0011_client_identity_updated_at`, defaut NULL), pose par les editions d'identite (`ClientViewSet.perform_update`, `_apply_client_identity_push`). Garde = `identity_updated_at` ; s'il est NULL, `updated_at` seulement tant qu'aucun mouvement de dette n'existe (sinon le proprietaire fait autorite).
Fichiers : clients/models.py, clients/views.py, sync/services.py, migration 0011.

## BUG-952 (CORRIGE)
`apply_pull_response` : si `is_synced=False` ET `identity_updated_at` renseigne (edition locale non poussee), plafond et identite du Cloud sont ignores (dette toujours appliquee, categorie recalculee sur le plafond local) ; l'edition sera poussee ensuite. (`is_synced=False` seul ne suffit pas : un client simplement cree localement l'est aussi.)
Fichier : sync/management/commands/sync_now.py.

## BUG-954 (CORRIGE)
`SocialContributionViewSet.perform_update` (journal si `is_paid` change) et `perform_destroy` (journal de suppression), messages francais. Fichier : clients/views.py.

Tests : marques `@expectedFailure` retirees pour 951/952/954 (assertions inchangees) dans clients/tests/test_clients_v9.py ; BUG-953 reste A CLARIFIER (marque conservee).
Risque : clients sans edition tracee ayant deja des mouvements de dette : push d'identite plus ancien accepte (autorite du proprietaire).
