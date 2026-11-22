# Rapport testeur-permissions (Dev B), 2026-11-22, ronde b3

Fichier de tests : `backend/core/tests/test_verif_permissions_b3_v3.py` (29 tests, données fictives, aucun code applicatif modifié).
Résultat : 28 OK + 1 `@expectedFailure` (BUG-760). Premier passage complet : 29 tests ; seule la classe `ClientsBulk` a été relancée après correction du test.

## Vérification des corrections
| Ticket | Résultat | Preuves |
|---|---|---|
| BUG-701 colis sans montants | VÉRIFIÉ | 201 et total 0 sans montants ; 1500,50 avec montants ; `rice_value='abc'` -> 400 ; `node` forgé ignoré pour le gérant |
| BUG-702 username non chaîne | VÉRIFIÉ | liste, nombre, objet, booléen -> 400 `{"detail"}` ; `null` sans 500 |
| BUG-703 manuel_adjustment | VÉRIFIÉ | PATCH et PUT par les 6 rôles : valeur ignorée, base inchangée ; POST création ignore aussi le champ ; `set_manuel` fonctionne pour DIRECTION (journalisé, net = ajustement), 403 pour COMPTABLE/GERANT/FACTURIER/LIVREUR ; un PATCH COMPTABLE légitime ne modifie pas un ajustement existant |
| BUG-704 throttle admin | VÉRIFIÉ | 10 échecs par compte puis 429 ; variantes de casse/espaces/tabulation partagent le compteur ; `X-Forwarded-For` forgé sans effet (le middleware lit `REMOTE_ADDR`) ; plafond 30 par IP sur comptes distincts ; réussite non comptée et remise à zéro ; compte bloqué même avec le bon mot de passe ; GET non bloqué ; `username` absent/liste/400 caractères sans 5xx ; le login API n'est pas affecté |
| BUG-705 | REJETÉ, accepté | décision « siège seul » cohérente avec le code |
| BUG-706 `IsGerantWriteNoAccountant` | VÉRIFIÉ | movements : COMPTABLE GET 200, POST/PATCH/PUT/DELETE refusés (le mouvement subsiste) ; ADMIN, DIRECTION, GERANT non refusés ; FACTURIER/LIVREUR 403 partout ; anonyme 401 ; gérant K1 ne voit pas un mouvement K2 (404) |
| BUG-707 journal sur DELETE | VÉRIFIÉ | entrée `ActivityLog` créée (gérant, direction) |

Le registre a été mis à jour : BUG-701, 702, 703, 704, 706, 707 passent à VÉRIFIÉ ; 705 reste REJETÉ.

## Nouvelles routes examinées
- `clients/bulk_move`, `bulk_delete`, `import_excel` : anonyme 401, FACTURIER/LIVREUR/GERANT 403, ADMIN/DIRECTION/COMPTABLE 400 sur corps vide. `ids` hostiles (`'abc'`, `[None]`, objets, UUID inconnus, entier) : aucun 5xx. Fichiers non Excel (texte, vide, signature ZIP seule) : 400.
- `consumables/dispatch` : 403 sauf ADMIN/DIRECTION ; quantités `NaN`, `1e999`, listes, nœud inconnu : aucun 5xx. `consumables/global` : 200 uniquement pour ADMIN/DIRECTION/COMPTABLE ; paramètres farfelus sans 5xx.
- `inventories` : `node` forgé dans le corps ignoré ; `node/<K2>` refusé au gérant K1 ; références farfelues sans 5xx ; FACTURIER/LIVREUR 403.
- Recherche clients (`KIESE_FOLD`) : injection SQL, `%`, `_`, NUL, 300 caractères accentués sans 5xx ; le gérant K1 ne trouve pas un client K2 ; le facturier le trouve (exception voulue).
- Clients : PATCH `credit_limit`, PUT, DELETE par facturier 403 ; gérant K1 sur un client K2 : 404 ; `node` forgé dans un PATCH ignoré.

## Nouveau ticket
| Ticket | Gravité | Résumé | Test |
|---|---|---|---|
| BUG-760 | Mineur | `DELETE /api/clients/clients/<id>/` sur un client référencé (ligne de distribution sociale, factures, commissions) -> 500 (`ProtectedError` non interceptée). `bulk_delete` gère bien ce cas. | `ClientsBulk::test_single_client_delete_with_protected_relation_not_500` (`@expectedFailure`) |

Aucun ticket bloquant : aucune fuite inter-nœuds ni élévation de droits.

## Constats sans ticket
- `bulk_move`, `bulk_delete`, `import_excel` sont ouverts au COMPTABLE (`IsHeadquarters`), alors que la docstring dit « Direction centrale uniquement ». C'est cohérent avec la hiérarchie (le COMPTABLE peut déjà supprimer et modifier un client à l'unité via `IsGerant`). À confirmer avec le client si le COMPTABLE doit pouvoir supprimer ou déplacer des clients en masse. Le test fige l'état actuel (200).
- Le COMPTABLE peut toujours PATCH ou DELETE une commission (champs `order_value` et `deduction_*`, `IsHeadquarters`), donc changer le net à payer sans passer par `set_manuel`. C'est une écriture légitime de recalcul, à ne pas confondre avec BUG-703. À clarifier avec le client.
- Le throttle admin utilise un cache par processus (risque déjà signalé par dev-backend). Un attaquant peut verrouiller un compte admin en échouant 10 fois (déni de service ciblé) ; accepté.
- La plage 760+ est utilisée ; l'autre testeur a pris 780 à 784.

## Commande
`cd backend; export ...; ./.venv/Scripts/python.exe manage.py test core.tests.test_verif_permissions_b3_v3 --noinput` (durée d'environ 3 minutes, due surtout aux 40 tentatives de login admin avec hachage).
