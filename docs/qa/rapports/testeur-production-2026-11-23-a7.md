# Testeur production (Dev A) - cycle 5 a7 (2026-11-23)

Tests : `backend/production/tests/test_verif_production_a7_v7.py` (+ a6_v6, v2_a3) : 90 tests OK, 12 échecs attendus (BUG-684, 686 x6, 687 x3, 688 x2). Log : `$TEMP/a7.log`.

Verdicts : VÉRIFIÉ = BUG-654 (reliquat ligne, clos), 680, 681, 682, 683, 685 (lecture de code, non exécuté).
Levée de `@expectedFailure` sur BUG-625 (403 obtenu) ; ticket resté À CLARIFIER, note au registre.

Nouveaux tickets : BUG-686 (chiffres non ASCII : mouvements, comptages, inventaire, dispatch, unit_price_sold), BUG-687 (dates futures : comptages, confirmation de départ), BUG-688 (quantité physique négative d'un comptage).
Sans défaut : `is_synced` repasse à False sur PATCH de mouvement, fournée, disposition ; `bread-stocks/by-date` refuse déjà le futur.
Observation : dates en chiffres arabes acceptées (normalisées, sans effet).
