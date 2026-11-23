# architecte-sync d60 — BUG-1030 (2026-11-23)

BUG-1030 (majeur) : CORRIGÉ. `/api/sync/pull/` ne diffusait aucun paramètre propre à la boulangerie (Q-026).

## Contrat final du bloc `node_settings`

Réponse du pull, clé additive `node_settings`. Elle concerne le nœud authentifié par le jeton, et lui seul.
Aucun autre nœud, aucun champ sensible.

| Champ | Format | Nullable |
|---|---|---|
| default_commission_rate | chaîne décimale ("0.30") | oui (null = reprendre le taux global) |
| card_fee_fc | chaîne décimale | non |
| monthly_social_contribution | chaîne décimale | non |
| sac_value_fc | chaîne décimale | oui |
| handover_time | "HH:MM" | non |
| block_sales_after_closure | booléen | non |
| team_rotation_enabled | booléen | non |
| team_a_start_time, team_a_end_time, team_b_start_time, team_b_end_time | "HH:MM" | oui |

Application côté poste : `_apply_pulled_node_settings`, appelée par `apply_pull_response` (`sync_now.py`) avant le traitement des clients. Le poste cible le `Node` de `node_code`.
- Le cloud fait autorité : chaque champ présent et valide écrase la valeur locale.
- Une clé absente ne touche pas le champ. Un bloc absent ou non dict (cloud ancien) n'efface rien.
- Un champ invalide est ignoré seul, avec un `log.warning` sur le logger `sync`. Cas couverts : décimal hors bornes, NaN, booléen pris pour un nombre, heure mal formée, type hostile. Aucune exception, donc pas de 500.
- Plages acceptées : taux de 0 à 1 ; frais de carte et cotisation de 0 à 10 000 000 ; valeur du sac de 0 à 9 999 999 999. Valeurs quantifiées à 0,01.
- Le code, le nom, `last_sync`, `is_active` et les clés d'identité ne sont jamais écrits : seuls les champs de la liste ci-dessus sont lus. Le nœud local n'est jamais créé.
- Versionnage : une écriture (`UPDATE` ciblé + `updated_at`) n'a lieu que si une valeur change. Sinon la fonction ne fait qu'une lecture et retourne False.
- Un poste ancien qui ignore le bloc reste fonctionnel (clé additive).
- `Node` n'était pas déjà synchronisé par un autre mécanisme : grep dans `sync/`, aucune descente de `Node` hormis `last_sync` et `node_code`. Pas de doublon.

Fichiers modifiés : `backend/sync/views.py` (`_node_settings_block`, appel dans `PullView`), `backend/sync/management/commands/sync_now.py`, `backend/clients/tests/test_clients_v17.py` (décorateur `@expectedFailure` retiré du seul test BUG-1030, assertions inchangées), `docs/qa/REGISTRE_BUGS.md` (BUG-1030 CORRIGÉ). `clients/views.py` et `commissions/` n'ont pas été touchés.

## Tests

Nouveau fichier `backend/sync/tests/test_dev_b1030_node_settings.py` (13 tests) :
- contenu du bloc ;
- aucune valeur d'un autre nœud ;
- le poste reçoit ses valeurs et K2 reste intact ;
- identité jamais écrasée ;
- cloud ancien sans bloc ;
- bloc partiel ;
- valeurs hostiles ;
- champ invalide mêlé à un champ valide ;
- poste inconnu non créé ;
- rejeu idempotent ;
- aucun UPDATE si inchangé (`assertNumQueries(1)`, `updated_at` identique) ;
- modification cloud redescendue au pull suivant ;
- taux reçu appliqué à la création d'un client sur le poste (cohérence BUG-1103, 0,30 contre 0,25 global).

## Résultats RÉELS (log `$TEMP/d60.log`)

- Passe 1 : `sync.tests.test_dev_b1030_node_settings` + `clients.tests.test_clients_v17` : 32 tests, OK.
- Passe 2 : `sync.tests.test_verif_sync_v5`, `sync.tests.test_verif_charge_v4`, `clients.tests.test_clients_v14`, `test_clients_v15`, `test_clients_v16` : 79 tests, OK.
- `makemigrations --check --dry-run` : No changes detected.

`test_clients_v17` contient encore deux `@expectedFailure` (BUG-1027, autre agent). Ils n'ont pas été touchés.

Rien n'est commité.
