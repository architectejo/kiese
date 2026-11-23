# dev-backend d53 (2026-11-23) - BUG-1012
- (A) test_bug216... renommé test_bug688_inventaire_physique_negatif_refuse (400 + message). Mouvements négatifs inchangés. À CLARIFIER client : stock physique négatif.
- (B) formes exponentielles refusées (7E0, 2E+9, 2.000E+9, 0E+999999, 1e3) dans les 2 tests listés. '+7' échouait car la regex BUG-896 n'admettait pas '+' : production/views.py `[-+]?`.
- Résultat : 159 tests (3 fichiers + a7_v7 + a6_v6 + d13_bugs_652_654_626) OK, 1 expected failure préexistant ; makemigrations --check : No changes detected. Log : $TEMP/d53.log.
- Non commité.
