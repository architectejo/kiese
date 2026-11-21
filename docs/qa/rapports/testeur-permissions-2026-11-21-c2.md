# Rapport testeur-permissions (Dev C) - verification BUG-506 - 2026-11-21 (c2)

## Verdict
BUG-506 : **VERIFIE** (correctif Dev B, commit e347918), avec reserve : la garde `node_id` vide dans les `get_queryset` de production / treasury / sales (Dev A) reste ouverte. Deux tests attendus-en-echec la portent encore.

## Relecture du diff, contournements cherches
| Piste | Resultat |
|---|---|
| POST /users/ GERANT/FACTURIER/LIVREUR sans `node` ou `node: null` (ADMIN et DIRECTION) | 400 sur `node`, rien cree |
| PATCH `node: null`, `node: ''`, `node: null` + role | 400, noeud conserve |
| PUT complet avec `node: null` | 400. PUT sans `node` : champ non envoye, `data['node'] if 'node' in data else target.node` conserve l'existant |
| Changement de role ADMIN/DIRECTION/COMPTABLE vers un role boulangerie sans `node` | 400 ; avec `node` : 200 |
| ADMIN/DIRECTION/COMPTABLE sans noeud (siege) | non casses : creation 201, `node: null` en PATCH sur DIRECTION 200, lecture globale OK |
| Deplacement d'un gerant vers un autre noeud | 200 (non regresse) |
| Noeud supprime ensuite (`on_delete=SET_NULL`) | le compte devient orphelin ; la garde `is_node_less_non_hq` renvoie `none()` : 0 objet sur clients, contributions, distributions, lignes, periodes, commissions, notifications, colis |
| Orphelin cree hors API (ORM) : 3 roles | 0 objet en liste, detail UUID K2 refuse, creation client / cotisation forcee sur K2 sans effet, filtre `?period__node=<K2>` sans effet, /users/ 403 |
| Autres routes de creation d'utilisateur | aucune dans le code applicatif (seulement `core/testing.py`, `seed_from_excel.py`, scripts) ; pas de creation via chat / sync / import clients |
| Utilisateur desactive (`is_active=False`) | hors perimetre du correctif ; un compte avec noeud valide mais desactive n'est pas orphelin ; non traite |

Observation (pas un ticket) : la suppression d'un noeud par la direction produit des orphelins (SET_NULL) ; ils sont sans donnees visibles, et `check_users_sans_noeud` les liste. Une `PROTECT` ou un refus de suppression d'un noeud ayant des utilisateurs serait plus net, a l'appreciation de Dev B.

## Tests ecrits
`backend/core/tests/test_verif_bug506_c.py` : 12 tests (`Bug506Verif`) couvrant le tableau ci-dessus et la commande `check_users_sans_noeud` (lecture seule : etat de la table `User` identique avant et apres ; liste actifs et inactifs ; n'inclut ni comptes avec noeud ni siege ; message "Aucun compte sans boulangerie." quand vide).

`backend/core/tests/test_verif_matrice_c.py` : marque `@expectedFailure` retiree de `IsolationExtra::test_non_hq_user_cannot_be_created_without_node` (passe). Conserves : `IsolationExtra::test_node_less_non_hq_sees_nothing_cross_node` et `IsolationProduction::test_bug147_node_less_non_hq_account_cannot_reach_other_nodes` (garde production/treasury/sales, Dev A).

## Resultats
`manage.py test core clients commissions` : 667 tests, **OK** (3 ignores, 6 echecs attendus, aucun succes inattendu, aucun echec).
Verification de `check_users_sans_noeud` : sur base de test (test unitaire ci-dessus), conforme.

## Tickets
Aucun nouveau ticket. BUG-506 passe a VERIFIE (ligne du registre editee), reserve Dev A consignee sur la meme ligne. Prochain numero libre non consomme par cette verification (>= 512 a re-verifier).

## Restrictions respectees
Aucun code applicatif modifie, pas de commit/push, desktop/ non touche.
