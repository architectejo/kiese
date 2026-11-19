# Rapport testeur-production — 2026-11-19
Vérification BUG-303, BUG-304, BUG-306 (API). Détail et preuves : section « Vérification testeur-production » de docs/qa/REGISTRE_BUGS.md.
Tests : backend/production/tests/test_verif_bug303_304_306_testeur_production.py (36 tests : 33 OK, 2 expectedFailure BUG-309, 1 sauté concurrence SQLite). Base isolée via DB_NAME.
Résultat : BUG-303, 304, 306 (API) VÉRIFIÉS ; BUG-309 ouvert (sacs négatif = HTTP 500).

## Addendum : BUG-309 VÉRIFIÉ
Sacs invalides (négatif, NaN/Infinity, texte, booléen, null/vide, >100000, >2 décimales, liste/objet) -> 400 français en POST et PATCH, valeur inchangée ; 0 et valeurs valides acceptés ; `remaining` fractionnaire refusé (entier 3.0 accepté). Modification du test de troncature par le dev validée. 52 tests OK (1 sauté : concurrence SQLite), aucune régression 303/304/306. Tests : V309SacsValidationTests.

## Addendum : BUG-309 VÉRIFIÉ
Sacs invalides (négatif, NaN/Infinity, texte, booléen, null/vide, >100000, >2 décimales, liste/objet) -> 400 français en POST et PATCH, valeur inchangée ; 0 et valeurs valides acceptés ; `remaining` fractionnaire refusé (entier 3.0 accepté). Modification du test de troncature par le dev validée. 52 tests OK (1 sauté : concurrence SQLite), aucune régression 303/304/306. Tests : V309SacsValidationTests.
