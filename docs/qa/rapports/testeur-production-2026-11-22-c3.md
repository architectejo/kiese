# Rapport testeur-production (Dev C) 2026-11-22 c3
Vérification BUG-364 et BUG-365 : VÉRIFIÉS. Nouveaux tickets : BUG-524 (CUMP selon l'ordre de deux entrées de même instant après stock négatif), BUG-525 (reconciliation ?node=ZZZ -> 500).
Tests : backend/production/tests/test_verif_bug364_365_c.py ; lot de 98 tests (3 exécutions) : OK, 2 échecs attendus (BUG-524, BUG-525).
Analyse de la limite : stock >= 0, deux entrées de même instant : moyenne pondérée commutative, ordre sans effet (testé). Stock négatif : l'ordre change le CUMP (200 vs 162,5).
