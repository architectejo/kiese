# Testeur ventes (Dev A), 2026-11-23-a5

Vérification de BUG-660 à 663 (commit 65232c5). Machine chargée : tests ciblés, un processus à la fois, DB_NAME dans le scratchpad.

## Vérifiés
BUG-660, 661, 662, 663 : VÉRIFIÉ.
- `git diff HEAD~3` de `test_ventes_a4_verif.py` : seules 5 lignes `@expectedFailure` retirées, aucune assertion modifiée.
- Rejeu : `test_ventes_a4_verif` + `test_bug821_822_824_adjust_d7` + `test_verif_ventes_a6_v6` = 45 tests OK.
- Nouveau fichier `backend/sales/tests/test_verif_ventes_a7_v7.py` : 13 tests « Non servi / ajustements » OK ; 6 tests de concurrence OK (hors BUG-1001).

Angles couverts : ajustements multiples +/- puis Non servi manuel et expiration 12 h (idempotente) ; versement de l'originale conservé ; remboursement sur ajustement -1 ; ajustement après annulation / non servi (400) ; non servi deux fois ou après annulation (409) ; ajustement -100 % puis non servi (stock et BP jamais négatifs) ; vente sans client ; VENTE SOLDE ; livraison partielle puis ajustement (net 3) ; plafond 50 000 FC libéré après non servi ; prix figé malgré changement du catalogue ; journal. Concurrence (SQLite) : 3 ajustements -1 sur 2 pains (exactement 2 x 201, 1 x 400, état 0/0), +/- simultanés, 2 non servi (200 + 409), non servi + annulation + ajustement (aucun blocage, état 0/0), expiration + ajustement. Ordre de verrous facture puis client : aucun interblocage.

## Rouverts
Aucun.

## Nouveaux
- BUG-1001 (Mineur, OUVERT) : `get_object()` est appelé avant `_retry_on_lock` dans `adjust`, `mark-not-served`, `cancel`, `deliver` : un verrou SQLite à cet endroit donne un 500 (observé en intermittent sur `mark-not-served` + `adjust` simultanés, views.py l.1104). 3 tests `@expectedFailure` déterministes (`RetentativeGetObject`).
- BUG-1002 (Mineur, À CLARIFIER) : Non servi conserve le versement de l'originale mais annule celui d'un ajustement (cohérent avec `cancel`, pas avec « versement conservé »). Comportement actuel documenté par test.

Registre : 660 à 663 passés à VÉRIFIÉ (lignes de tableau et fiches), 1001 et 1002 ajoutés après BUG-1000 (éditions ciblées). Aucun code applicatif modifié.
