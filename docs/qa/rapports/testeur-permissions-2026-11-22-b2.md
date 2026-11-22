# Rapport testeur-permissions (pour le Dev B), 2026-11-22, ronde b2

Périmètre : Core, RBAC transversal, Chat, `kiese/` (plan `docs/PLAN_TESTS_CORRECTIONS_A_B_C.md` §1-§2).
Nouveau fichier de tests : `backend/core/tests/test_verif_permissions_b2_v2.py` (aucun test existant édité, aucun code applicatif modifié, données fictives).

## Résultat
- 57 tests : tous passent, dont **6 `@expectedFailure`** rattachés à des tickets ouverts (aucun succès inattendu).
- Fichier seul : `manage.py test core.tests.test_verif_permissions_b2_v2` : 57 tests, 6 échecs attendus.
- Suite `manage.py test core chat --noinput` : **676 tests, OK (2 ignorés, 7 échecs attendus : les 6 ci-dessus + BUG-507 existant)**, durée 2550 s.

## Angles couverts (nouveaux)
1. **Matrice avec valeur attendue par rôle** (anonyme + 6 rôles, ~50 lignes route x méthode) sur : `consumables/global` (HQ), `consumables/dispatch` (ADMIN/DIRECTION), `inventories` (liste, détail, `today`, `node/<ref>`, POST/PATCH gérant rattaché seulement, PUT/DELETE refusés), `movements` (GERANT+), `stocks`, `commissions/*` (`summary`, `payroll_listing`, `history`, `generate`, `close_period`, `mark_paid`, `set_manuel`), `deficit_report`, `bassins`, nœuds, utilisateurs, config, tarifs, catégories de dépenses, activités, notifications, colis, `reset-data` (superuser technique seulement), chat. Pas de 5xx, anonyme = 401 partout.
2. **IDs forgés** (UUID/pk d'un autre nœud) en GET/PUT/PATCH/DELETE pour 10 familles d'objets (clients, distributions, lignes, cotisations, sessions, stocks, inventaires, commissions, périodes, colis) par gérant, facturier, livreur K1 : 403/404, base inchangée. `node=K2` et `period=<période K2>` forgés dans le corps : ignorés. Filtres `?period=`, `?period__node=`, `?client=`, `?node=` sur commissions : aucune fuite. Mouvement K2 en lecture/PATCH/DELETE par un gérant K1 : 404 ; déplacement d'un mouvement K1 vers un stock K2 : refusé.
3. **Mass assignment** : `is_superuser`, `is_staff`, `is_active`, `must_change_password`, `can_access_all_nodes`, `is_headquarters`, `password`, `last_login` ignorés en POST/PATCH `/users/` par la direction ; DIRECTION ne peut ni créer/promouvoir un ADMIN ni toucher (patch, put, désactivation, suppression, reset) un ADMIN ; ADMIN ne peut ni se désactiver ni accorder `is_superuser` ; gérant/facturier/livreur ne changent ni rôle, ni nœud, ni équipe, ni statut via `/auth/me/` ou `/users/<soi>/` (403). Nœuds : écriture (`card_fee_fc`, `monthly_social_contribution`, `sac_value_fc`, `is_active`, `name`) refusée à COMPTABLE/GERANT/FACTURIER/LIVREUR ; DIRECTION valide négatif, NaN, Infinity, 1e40, texte (400). Config et tarifs : écriture DIRECTION+ seulement ; valeurs dégénérées jamais 500. Journal d'activité : lecture HQ seulement, aucune écriture. Notifications : création/modification HQ seulement, `node_origin` non forgeable.
4. **JWT / authentification** : refresh utilisé comme access (401), rôle et nœud relus en base à chaque requête (un jeton ne survit pas à une rétrogradation), refresh d'un compte désactivé refusé, reset de mot de passe neutralise les anciennes sessions (403 `must_change_password`, ancien mot de passe invalide), entrées de login dégénérées (null, 5000/50000 caractères, NUL, injection SQL) sans 500 (sauf BUG-702), même réponse pour compte inconnu et mauvais mot de passe, en-têtes `Authorization` farfelus et jeton en paramètre d'URL refusés, logout anonyme refusé, politique de changement de mot de passe (identique, trop court, proche du nom, ancien faux, champs manquants), changement via `/auth/me/` exige l'ancien mot de passe, aucun mot de passe dans le journal.
5. **Chat** : conversations de K2 (fil de nœud et message direct) illisibles, non écrivables et non marquables « lu » par K1 (404, aucune fuite dans la liste) ; fil Direction refusé aux non-HQ même avec une participation périmée (GET 404, POST 403) ; utilisateur muté vers un autre nœud perd l'ancien fil ; champs `sender`, `conversation`, `node_origin`, `created_at` forgés dans un message ignorés ; messages immuables (PUT/PATCH/DELETE 405/404) ; identifiants de conversation fantaisistes (`abc`, `../..`, `%00`, injection) toujours 404 ; un tiers ne rejoint pas un message direct existant ; annuaire sans e-mail ni téléphone ; anonyme 401 partout.
6. **Surface `/admin/`** : exige une connexion ; un ADMIN métier non `is_staff` n'y entre pas ; mais voir BUG-704.

## Constats sans ticket (comportement voulu, documenté)
- `GET /api/core/nodes/` est lisible par tout compte authentifié et expose `card_fee_fc`, `monthly_social_contribution`, `sac_value_fc`, `last_sync` des autres boulangeries (listes déroulantes) : jugé voulu.
- `GET /api/chat/users/` liste tous les utilisateurs actifs de toutes les boulangeries (nom, rôle, code nœud) : annuaire de messagerie, voulu ; DM inter-nœuds possibles.
- `/api/clients/clients/bassins/` est bien refusé au facturier/livreur (aucune fuite de CM/net) et borné au nœud du gérant.
- Les actions décorées de `permission_classes` dans un ViewSet dont `get_permissions()` est surchargé sont ignorées (voir BUG-705) : à garder en tête pour toute nouvelle `@action`.
- Nœud SIEGE : non retesté (BUG-517 / BUG-564 connus).

## Tickets ouverts (registre `docs/qa/REGISTRE_BUGS.md`)
| Ticket | Gravité | Propriétaire | Résumé | Test |
|---|---|---|---|---|
| BUG-703 | Majeur | B (commissions) | COMPTABLE contourne `set_manuel` : PATCH `manuel_adjustment` remplace le net à payer, sans journal | `MassAssignment::test_comptable_cannot_override_net_via_manuel_adjustment` |
| BUG-704 | Majeur | B (`kiese/`) | `/admin/login/` sans limitation de tentatives (contournement du throttle de login) | `AdminSurface::test_admin_login_is_throttled` |
| BUG-707 | Majeur | A (production) | DELETE d'un mouvement de consommable sans trace dans le journal d'activité | `MovementsRoles::test_movement_delete_leaves_audit_trace` |
| BUG-701 | Mineur | B (core) | POST colis sans montants -> 500 (concaténation de chaînes `'0.00'`) | `ForgedIds::test_colis_create_without_amounts_is_not_500` |
| BUG-702 | Mineur | B (core) | login anonyme avec `username` non-chaîne -> 500 dans le throttle | `JwtV2::test_login_non_string_username_is_not_500` |
| BUG-705 | Mineur, À CLARIFIER | B (commissions) | `history` / `payroll_listing` : décorateur IsGerant sans effet, HQ seulement | matrice (état figé) |
| BUG-706 | Mineur, À CLARIFIER | A (production) | COMPTABLE écrit des mouvements de stock (quantité, CUMP) de tout nœud | `MovementsRoles::test_comptable_cannot_write_stock_movements` |

Aucun ticket **bloquant** : aucune fuite inter-nœuds ni élévation de droits constatée sur ces angles.

## Fichiers
- Tests : `backend/core/tests/test_verif_permissions_b2_v2.py`
- Registre : `docs/qa/REGISTRE_BUGS.md` (lignes BUG-701 à BUG-707, après BUG-523)
