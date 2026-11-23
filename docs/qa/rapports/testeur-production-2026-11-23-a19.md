# testeur-production a19 (cycle 20 partie A, 2026-11-23)

Nouveaux tickets : 5 (BUG-1015 a BUG-1019 ; 1013/1014 pris par l'autre testeur).

1. BUG-1012 : VERIFIE. `production/tests/test_verif_production_a19_v19.py` (V1012) : comptage, inventaire et push de comptage negatifs refuses (BUG-688) ; mouvements negatifs/nuls REST toujours acceptes (BUG-216) ; `qty` d'opening-confirmation : `7E0`, `1e3`, `2E+9`, `0E+999999`, `7e0`, `+7E0` en 400 sans effet sur BreadStock, `+7`, `7.0`, ` 7 `, `007`, 7.0 acceptes ; hostiles (bool, null, ASCII/non ASCII, listes, `7.5`) en 400 ; grandes chaines (5000 chiffres) 400 en moins de 2 s. Les 3 tests adaptes (vague1_db, bug317, bug319_322) passent (102 tests, 306 s sous charge) et testent toujours l'essentiel (formes valides, limites 2e9, hostiles).
2. Balayage regex/helper REST vs push (matrice 17 formes x lignes de fournee, dispositions, prix, mouvements, comptages, transferts, sacs, opening, dispatch). Identiques et testes (A19Parity) : lignes et dispositions (y compris `7E0`, `1e3`, non ASCII, bool), negatifs de lignes/dispositions, consommables decimaux (comptage/mouvement), transferts sur les formes communes. Incoherences, toutes `@expectedFailure` :
   - BUG-1015 (Mineur) transferts REST refusent `+7`, `7.0`, `00007`, `-0` ; le push les accepte.
   - BUG-1016 (Mineur) espaces non ASCII (NBSP, U+3000) acceptes par transferts REST et opening, refuses ailleurs.
   - BUG-1017 (Mineur) push : `null` converti en 0 (disposition, ligne de transfert, sacs) ; REST 400.
   - BUG-1018 (Mineur) `1_0` = 10 accepte presque partout, refuse par opening et transferts REST.
   - BUG-1019 (Moyen) mouvement de consommable negatif accepte en REST (decision BUG-216) mais rejete au push (minimum 0) : divergence poste/cloud.
3. Partie A : cycle non propre (5 tickets mineurs/moyen de coherence, aucun bloquant, pas de perte de stock ni d'ecart de somme du groupe).

Run : `manage.py test production.tests.test_verif_production_a19_v19` : 15 tests OK (6 expected failures = 5 tickets). Log $TEMP/a19.log.
