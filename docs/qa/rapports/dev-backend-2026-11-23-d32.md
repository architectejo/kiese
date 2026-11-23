# Dev backend d32 (2026-11-23) : BUG-941 à BUG-950

Tous passés à CORRIGÉ (vérification par le testeur). `@expectedFailure` retirés de `clients/tests/test_clients_v8.py` (assertions inchangées ; les doubles décorateurs ont aussi disparu).

| Ticket | Cause | Correction |
|---|---|---|
| 941 | `_push_client` : client connu du propriétaire = no-op | `sync/services.py::_apply_client_identity_push` : nom, téléphone, adresse, notes, plafond, taux, cotisation, type appliqués (validation stricte, rejet global si invalide) ; `updated_at` du push plus ancien que le Cloud = no-op ; dette, BP, pains jamais touchés ; catégorie recalculée si plafond modifié |
| 942 | `apply_pull_response` n'écrivait que dette + catégorie | applique plafond (borné) et identité ; catégorie cohérente avec le plafond appliqué ; pull (`sync/views.py`) renvoie en plus nom, téléphone, adresse (ajout compatible) |
| 943 | `serializer.save()` réécrivait toutes les colonnes | `ClientViewSet.perform_update` : ligne verrouillée, `update_fields` limité aux champs envoyés + catégorie |
| 944 | pas de journal | `log_activity` : plafond/taux, suppression client, `toggle_paid`, génération mensuelle, clôture/tarif de distribution, lignes caisse sociale (création/modification/suppression), commissions (création/modification/suppression) |
| 945 | transition vers RISK silencieuse | `Client.notify_risk_transition`, appelé par `recompute_client_debt` (push), PATCH et push/pull client |
| 946 | année non bornée | `SocialContributionSerializer.validate_year` 2000-2200 |
| 947 | `paid_at` incohérent | `validate` du sérialiseur : `is_paid` vrai pose `paid_at` (conservé si déjà payé), faux le vide (le PATCH direct reste permis : les tests 947 l'exigent) |
| 948 | PATCH sans contrôle | `validate` : `node` immuable, client de la boulangerie de la cotisation |
| 949 | PATCH node sans code | `perform_update` régénère code et `node_origin` comme `bulk_move` |
| 950 | `if manual_amount` | `is not None` |

Fichiers : `clients/views.py`, `clients/serializers.py`, `clients/models.py`, `commissions/views.py`, `sync/services.py`, `sync/views.py`, `sync/management/commands/sync_now.py`, `clients/tests/test_clients_v8.py`, `docs/qa/REGISTRE_BUGS.md`.

Risques / points à noter
- 941 : `updated_at` du Cloud avance aussi à chaque mouvement de dette (BUG-787) ; une modification d'identité poussée plus tard mais datée avant un mouvement récent est ignorée (comportement « dernier écrivain gagne » strict). Un push sans `updated_at` est toujours appliqué.
- 942 : plafond et identité du Cloud écrasent toujours ceux du poste (pas de garde `updated_at` côté pull).
- Contrat API : champs ajoutés à `GET /api/sync/pull/` (`first_name`, `last_name`, `phone`, `address`) ; erreurs 400 nouvelles sur PATCH cotisation (année, node, client). Aucun ticket frontend nécessaire.
- Aucune migration.
