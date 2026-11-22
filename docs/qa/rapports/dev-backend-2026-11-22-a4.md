# Rapport dev-backend 2026-11-22 (a4)

Tickets : BUG-524 et BUG-525 -> CORRIGÉ (vérification par testeur-production).

Fichiers : production/views.py, production/management/commands/recompute_cump.py, production/tests/test_bug524_525_a.py (nouveau, 11 tests), production/tests/test_verif_bug364_365_c.py (@expectedFailure retirés ; test 999999 : 200 -> 400).

Avant : 7 échecs + 4 erreurs sur les deux fichiers de tests. Après : 105 tests ciblés OK ; suite complète voir résultat final ; check et makemigrations --check propres (aucune migration).

Autres endpoints au même défaut : corrigés (production) flour_history, ConsumableCountViewSet.perform_create. À signaler : flour_history `month`/`year` non numériques -> 500 probable (non traité) ; clients/views.py:317 et :499, commissions/views.py:57-58 (`int(months)`), finance/views.py (node_id), blockchain/views.py:98/125/136, sales/views.py:1209 (`int(node_param)`) : non touchés (hors périmètre / modules de B).
Risque : à instant égal, l'ordre de rejeu par (prix, quantité) est un choix arbitraire mais reproductible ; l'ambiguïté reste signalée.
