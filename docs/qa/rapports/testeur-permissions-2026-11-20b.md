# Rapport testeur-permissions, 2026-11-20 (b) : vérification BUG-316

## Verdict
BUG-316 : **VÉRIFIÉ**. Aucune réouverture, aucun nouveau bug.

## Méthode
Base isolée via `DB_NAME` (scratchpad, jamais `backend/db.sqlite3`) ; base de test Django en mémoire. Code relu : `SocialDistributionViewSet._can_set_tarif_and_close`, `_check_direction_fields`, `perform_create`, `perform_update` (`backend/clients/views.py`).
Nouveau fichier : `backend/core/tests/test_verif_bug316_testeur_permissions.py` (11 tests, tous verts), en complément des 7 tests de `test_verif_bug313_314_testeur_permissions.py::Bug316TarifEtCloture`.

## Résultats de la matrice
| Cas | Résultat |
|---|---|
| Gérant K1 : PATCH tarif / is_closed modifiés | 403, `detail` en français (« ...réservés à la direction. »), base inchangée |
| Gérant K1 : PUT avec tarif ou is_closed modifié | 403 identique |
| Comptable : PATCH et PUT modifiés | 403 identique (rôle HQ non direction, bien exclu) |
| Gérant / comptable : PUT inchangé, PATCH `tarif: "700.00"` (même valeur numérique) | 200, pas de faux 403 |
| Création par gérant/comptable avec tarif=4242, is_closed=true | tarif 700 et ouverte (valeurs ignorées) ; `node` forgé K2 : créée en K1 ou refusée, jamais en K2 |
| ADMIN, DIRECTION : PATCH tarif+is_closed, PUT sur K2 | 200, valeurs en base mises à jour |
| Facturier, livreur : PATCH, PUT, POST | 403, rien modifié ni créé |
| Anonyme | 401 |
| Autre nœud : gérant K1 sur distribution K2 (PATCH/PUT) et gérant K2 sur K1 | 404, tarifs inchangés ; gérant K2 sur sa propre distribution : 403 |

## Suites complètes (base isolée)
`python manage.py test clients core commissions` : **Ran 417 tests in 1374 s, OK (skipped=1)** (406 de dev-backend + 11 miens). Lancement terminé avant de rendre la main.

## Sorties des anciens lancements (fichiers de tâches de la session)
Je n'ai pas pu rattacher chaque fichier à un lanceur précis ; état relevé :
- 148 tests (sélection ciblée) : OK (skipped=1).
- 400 tests : OK (expected failures=1).
- 461 tests : OK (skipped=1).
- 406 tests (clients core commissions) de dev-backend avant correction : FAILED (failures=6, skipped=1), puis 406 OK (skipped=1) après correction (1696 s).
- Quelques lancements à 0 octet ou « exited with code 1/127 » (commande mal formée ou interrompue, sans sortie de tests) : non exploitables.
Aucun lancement de mes sessions n'est encore actif.

## Points d'attention (hors verdict)
- Le test historique `test_gerant_can_close_but_it_is_via_patch_flag` (313/314) accepte (200, 400, 403) : il est devenu non discriminant ; le comportement réel est couvert par les tests 316.
- Question client toujours ouverte : le gérant doit-il pouvoir clôturer ? (le code l'interdit désormais).
- Volet frontend (panneau tarif visible du gérant) : non jugé, traité par dev-frontend.
