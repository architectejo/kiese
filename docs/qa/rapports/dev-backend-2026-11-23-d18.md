# Dev-backend d18 (2026-11-23)

Corrigés (CORRIGÉ, à vérifier par le testeur) : BUG-654 (reliquat ligne de fournée), BUG-680, BUG-681, BUG-682, BUG-683.
À CLARIFIER, non codé : BUG-684.

Fichiers : backend/production/views.py, backend/production/serializers.py ; marques `@expectedFailure` retirées (assertions inchangées) dans backend/production/tests/test_verif_production_a6_v6.py, sauf BUG-684.

Tests : test_verif_production_a6_v6 + test_dev_d13_bugs_652_654_626 + test_dev_d15_demande4 : 50 tests OK (1 échec attendu = BUG-684). makemigrations --check : aucun changement. Suite complète non lancée (consigne).

Risques : le PATCH de comptage recalcule `gap` sur `system_quantity` figé à la création ; le contrôle de date en PATCH utilise le noeud de l'instance. Aucun changement de contrat frontend (400 supplémentaires seulement).
