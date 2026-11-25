# dev-backend 2026-11-25 : stabilisation des tests après Q-017 / Q-018

Périmètre : tests uniquement, aucun code applicatif modifié. Lancement avec `KIESE_TEST_CLOCK_SHIFT=1`.

## Résultat
- Les 15 modules de `production` en échec dans k2.log (77 FAIL + 14 ERROR) repassent tous au vert (rejoués par lots : 107 tests, 249 tests, 46 tests ; seul `expectedFailure` attendu).
- Aucun vrai défaut applicatif détecté, aucune contradiction métier.

## Causes et corrections
1. Nœuds créés par `Node.objects.create` sans `team_rotation_enabled=False` (403 `TEAM_NOT_ASSIGNED`) :
   - `production/tests/test_production_v2_a3.py` (Base partagée : K1/K2/K3 ; corrige test_audit_comptable_cloture_a, test_verif_a4, test_dev_d15_demande4, test_bug540_541_562, test_verif_production_a6/a7/a8/a17/a19/a20/a21, etc.).
   - Même correction préventive (une seule ligne `Node.objects.create(...)` par nœud, ajout de `team_rotation_enabled=False`) dans les bases partagées : `core/tests/test_permissions_regression_2026_11_19.py`, `test_verif_isolation_a_c.py`, `test_permissions.py`, `test_permissions_verif_2026_10_22.py`, `test_verif_permissions_b5_v5.py`, `b6_v6.py`, `b7_v7.py`, `test_verif_bug506_c.py`, `finance/tests/test_isolation_finance_a.py`, `production/tests/test_dev_i3_flour_month_stats.py`, `test_verif_direct_consommables_c.py`, `treasury/tests/test_bug085_hash_is_correction.py`, `test_ledger.py`, `blockchain/tests/test_integrity.py`, `chat/tests/test_chat_bug307.py`, `test_chat_permissions.py`. Non rejoués (voir plus bas).
2. Horaires de scénarios avant midi (journée midi à midi, Q-018) :
   - `test_bug327_daily_closure_clients.py` : `_aware` décale de +5 h (8..12 h devient 13..17 h, ordre conservé).
   - `test_verif_bug325_327_testeur_production.py` : heures de scénario décalées (défaut 10 h devient 14 h, etc.).
   - Tests de frontière « minuit » réécrits en frontière « midi » (attente modifiée EXPLICITEMENT d'après Q-018) : `test_bug356_closure_non_servi_statut.py::test_jour_de_travail_et_minuit` (11:59 -> jour J, 12:00 -> jour J+1) ; `test_verif_bug325_327...::test_jour_de_travail_frontiere_minuit` renommé `..._frontiere_midi`.
3. `test_global_consumables_direction.py::test_next_day_allowed` : le test simulait « demain » en patchant `production.consumables_direction.timezone.localdate`, or le code utilise désormais `core.workday.work_date_for` ; patch déplacé sur cette fonction.

Fichiers modifiés (en plus de la liste préventive ci-dessus) : `production/tests/test_production_v2_a3.py`, `test_bug327_daily_closure_clients.py`, `test_bug356_closure_non_servi_statut.py`, `test_verif_bug325_327_testeur_production.py`, `test_global_consumables_direction.py`.

Tests corrigés : 91 (77 FAIL + 14 ERROR du log k2) ; tous rejoués verts.

## Non rejoués / en attente
- Séries `core clients commissions sync chat` (k1) et `sales treasury finance blockchain` (k3) toujours en cours à la fin de ma session (aucun résultat final). Les corrections préventives des bases partagées (point 1) n'ont donc pas été validées par rejeu ; à relancer par module après leur fin.
- Nœuds restants créés sans `team_rotation_enabled=False` et non touchés (tests de rotation, de suppression/protection de nœud, de défauts 417, de migration) : à ne modifier qu'en cas d'échec constaté. Non traités aussi : `production/tests/test_verif_production_a14_v14.py:545`, `a18_v18.py:97`, `test_verif_bug319_322...:659`, `test_verif_bug161...:145` (non listés en échec dans k2).
- Autres modules de `production` qui n'étaient pas en échec dans k2 : non rejoués après la modification de `test_production_v2_a3.Base` (risque faible : seul `team_rotation_enabled` passe à False, comme `make_node`).
