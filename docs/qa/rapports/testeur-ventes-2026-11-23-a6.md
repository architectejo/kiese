# Rapport testeur-ventes a6 (2026-11-23)

Tests : `backend/sales/tests/test_verif_ventes_a5_v5.py` (35, dont BUG-664 à 673 passés) et `backend/sales/tests/test_verif_ventes_a6_v6.py` (27 : 26 verts + 1 `@expectedFailure` BUG-890). Aucun code applicatif modifié.

## Verdicts
- VÉRIFIÉS : BUG-664, 665, 666, 667, 668, 669, 670, 672, 673.
- BUG-671 : reste À CLARIFIER.

## Sondes a6 (toutes vertes)
- daily_summary avec Non servi : cash = versement conservé, CREDIT négatif, count = livrées seules, mélange livrée + non servi exact, autre jour exclu, double « non servi » sans double compte, sans versement : pas de ligne.
- bread_summary net : +5/-3 sur 10 = 12 pains / 3 600 FC ; ajustement d'une autre catégorie net par prix.
- Compteur `total_breads_received` : livraison double comptée une fois, non servi après ajustement en attente = 0, plancher 0, livraison partielle = pains livrés.
- Plafond sans client : égal conservé, inférieur conservé, négatif 400, daily_summary plafonné ; avec client le surplus réduit la BP (-2 000).
- delivered_at : même jour accepté, veille refusée sans effet (statut et stock inchangés), futur non accepté.
- 672 : pas de notification hors période close ; pas de 500 (facture en attente, sans client). 673 : NS ignoré aussi, RG de vente normale conservé.

## Nouveau
- BUG-890 (Mineur) : `adjust` sur facture EN ATTENTE crée un ajustement LIVRÉ ; après annulation de la mère il reste dans `bread_summary` (-2 pains) et `daily_summary` (CREDIT -600, count 1). BP et stock, eux, sont bien restaurés.

## Observation (pas de ticket)
- `ConcurrenceSqlite::test_quatre_annulations_simultanees_une_seule_restitution` a échoué une fois (quatre 400, aucun 200) dans le run combiné de 644 s, puis 3 fois sur 3 en isolé. Sous charge, instable ; à surveiller.
- Le run complet des deux fichiers dure environ 11 minutes (classe de concurrence).
