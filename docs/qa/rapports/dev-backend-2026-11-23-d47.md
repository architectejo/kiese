# dev-backend d47 (2026-11-23) : BUG-998

Statut : BUG-998 CORRIGÉ (édition ciblée du registre). Aucun commit, aucune migration.

## Correction
- `sync/views.py::PullView` : clients ACTIFS de toutes les boulangeries (+ les siens même inactifs, + déjà facturés) pour tout poste de boulangerie ; le nœud SIEGE garde le périmètre restreint. Colonnes client uniquement (aucune facture/mouvement/commission). Sous-requête `pk__in` au lieu de JOIN+DISTINCT, tri `(updated_at, id)`.
- Pagination : 5 000 clients max par réponse (`PULL_CLIENT_PAGE_SIZE`), `has_more`, `client_after_id` (curseur composite avec `since_client_debt`). Additif : un poste ancien ignorant `has_more` reste fonctionnel. `client_after_id` invalide : 400.
- `sync_now` et `desktop_client._pull_only` : boucle de pull jusqu'à `has_more=false` (200 pages max) ; le curseur persiste `client_after_id`.
- `apply_pull_response` : mises à jour en bloc (`_apply_pulled_client_batch` : verrou + `bulk_update` par lots de 500). Sémantique BUG-780/952/941/951 inchangée ; `is_synced` et `updated_at` intacts.
- Code client déjà pris localement : pas de doublon, `SyncConflictLog` `CODE_CLIENT_EN_CONFLIT` + notification une seule fois par client.
- `Migration0010` (test_verif_bug289_295) : base jetable + routeur temporaire, mêmes vérifications.

## Tests
- `test_BUG_998_*` sans `@expectedFailure`, assertions inchangées.
- Inversions de tests figés (raison : CLAUDE.md 5.1 / remarque.md) : `test_clients_v11::test_pull_ne_descend_pas_...` -> `test_pull_descend_les_clients_actifs_des_autres_noeuds_meme_sans_facture` (suit `has_more`) ; `test_clients_v12::test_etat_actuel_pull_sans_client_des_autres_noeuds` -> `test_pull_avec_clients_actifs_..._apres_BUG_998` ; `sync/tests/test_verif_charge_v4::test_pull_ne_fuit_pas_...` -> `test_pull_descend_les_clients_actifs_d_une_autre_boulangerie_BUG_998`.
- Nouveaux `clients/tests/test_clients_v12.py::Pull998` (inactifs, SIEGE, pas d'autre donnée, pagination ex-aequo, after_id invalide, conflit de code unique, édition locale préservée).

## Perf (mesures du run intermédiaire)
Rejeu 5 000 clients : 14,7 s -> 5,6 s. Pull 5 000 clients : 0,36 s, 2,05 Mo ; nombre de requêtes constant (test N+1 vert).

## Risques / à noter
- 8 boulangeries x milliers de clients : premier pull d'un poste = plusieurs pages de 5 000 (~2 Mo chacune).
- Poste ancien ignorant `has_more` : rattrape page par page, une par cycle ; ex-aequo d'`updated_at` rares à la frontière d'une page (non rattrapés pour un ancien poste).
- Frontend : aucun changement de contrat cassant.
