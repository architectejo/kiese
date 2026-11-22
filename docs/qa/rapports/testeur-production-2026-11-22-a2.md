# Rapport testeur-production, 2026-11-22-a2

Verification de BUG-508, BUG-363, BUG-512 : **VERIFIES**. Nouveau ticket BUG-513 (Mineur, OUVERT).

- git diff : seuls 5 marqueurs `@expectedFailure` retires dans `test_verif_bug501_510_a.py`, aucune assertion modifiee.
- Nouveau fichier `backend/production/tests/test_verif_bug508_363_512_a2.py` (10 tests, 9 verts + 1 `@expectedFailure` BUG-513). Avec `test_verif_bug501_510_a` et `test_bug185_186_187` : 48 tests, seul echec = BUG-513.
- Contre-attaques : prix 50/150/250/300/500 avec 4 changements de tarif ; RG soldee/simple, vente normale ; perte exacte et stable ; re-save de ligne ; nouvelle facture apres changement ; surconsommation 2e/3e declaration, sacs decimaux, repli sur cumul, pas de faux positif.
- Revue : plus de relecture catalogue pour valoriser une ligne de vente passee. Restent : valorisation production/reste d'un jour passe (BUG-513, `produit.fc` 30 000 -> 40 000 apres tarif 400) et `finance/views.py` l.309/386 (hors module).
- Migration 0011 relue, non rejouee sur donnees reelles. Base isolee via DB_NAME, sans --parallel.
