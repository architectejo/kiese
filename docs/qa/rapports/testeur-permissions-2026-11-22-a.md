# Rapport testeur-permissions, 2026-11-22 (Dev A)

Périmètre : vérification des tickets CORRIGÉ BUG-503, BUG-504, BUG-505, BUG-362 (arbre de travail non commité).
Méthode : DB isolée (`DB_NAME` dans le scratchpad), sans `--parallel`, données fictives, code applicatif non modifié.

## Résultat
- 78 tests exécutés (nouveaux + 3 fichiers de non-régression de A + `core/tests/test_verif_matrice_c.py`) : 1 échec, 2 échecs attendus.
- L'unique échec est `IsolationExtra::test_node_less_non_hq_sees_nothing_cross_node` sur `/api/clients/contributions/` (module de B, BUG-506) : non compté contre A.
- Échecs attendus restants (légitimes) : BUG-506 volet création de compte sans `node` (`core/users`, B) et BUG-507 (À CLARIFIER).
- Verdict : BUG-503, 504, 505, 362 passés à VÉRIFIÉ.

## Retrait des 5 `@expectedFailure` de `test_verif_matrice_c.py`
- BUG-504 (`test_movement_on_foreign_stock_forged`), BUG-503 (`test_report_create_forged_node_by_gerant`), BUG-505 (`test_flour_history_node_param_not_honoured_for_non_hq`) : légitimes, passent.
- BUG-506 (`test_bug147_node_less_non_hq_account_cannot_reach_other_nodes`) : légitime, passe (stocks non créés, rien de lu).
- BUG-506 (`test_node_less_non_hq_sees_nothing_cross_node`) : retrait prématuré dans l'arbre de A (échoue tant que le module de B n'est pas fusionné). À surveiller à la fusion : le test passera alors, sans marqueur.
- Les commentaires de remplacement portent « BUG-5XX » (marqueur vague) : cosmétique.

## Contre-attaques ajoutées (`backend/core/tests/test_verif_bug503_504_505_362_a.py`, tous verts)
- BUG-504 : SORTIE de 10 sur le stock K2 (avec `node` absent, K2, K1) : 400/404, stock K2 intact ; PATCH/PUT d'un mouvement propre vers stock, `node` ou session étrangers : refus, `stock`/`node` inchangés ; détail/PATCH/DELETE d'un mouvement K2 par UUID : 404 ; `?node=K2` en liste : 0 ligne ; facturier/livreur : 403 ; siège (ADMIN, DIRECTION, COMPTABLE) : pas de 5xx et incohérence stock/`node` refusée.
- BUG-503 : PATCH/PUT avec `node=K2` sur un rapport propre : nœud inchangé ; GET/PATCH/DELETE/`validate` d'un rapport K2 par UUID : 404 ; `node` forgé (entier, chaîne, inexistant, `x`, null, vide, form-data) : aucun rapport K2, pas de 5xx ; `facturier` et `node_origin` forgés ignorés ; `?node=K2` en liste : vide ; siège : création possible avec `node`, 400 sans.
- BUG-505 : `?node=` en variantes (code, doublon, vide) : jamais de données P2 pour un gérant K1.
- BUG-362 : gérant/facturier/livreur sans nœud : détail par UUID K2 en 403/404 ; listes avec `?node=K2` vides ; PATCH/PUT/DELETE session, POST mouvement SORTIE, rapport, dépense, clôture, facture avec `node` K2 : 403 ; aucun stock K2 auto-créé ; siège sans nœud (ADMIN, DIRECTION, COMPTABLE) toujours lecture globale 200 ; gérant K1 inchangé (404 sur K2) ; anonyme 401 ; OPTIONS/HEAD sans 5xx.

## Observations (sans ticket)
- Le registre de BUG-503 cite `treasury/serializers.py`, non modifié : la correction est dans `FacturierReportViewSet.create` (copie des données avec `node` imposé avant validation). Annoté dans le registre.
- `NoNodeGuardMixin` laisse les méthodes d'écriture des vues `APIView` hors ModelViewSet (actions hors viewsets listés) aux permissions existantes : hors périmètre, aucun contournement observé dans les tests.

## Fichiers
- `d:\Projects\kiesse\backend\core\tests\test_verif_bug503_504_505_362_a.py` (nouveau)
- `d:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (4 tickets annotés VÉRIFIÉ)
