# Régression trésorerie sur le commit 528875c (testeur-tresorerie, 2026-11-19)

## Environnement
- venv `backend\.venv`, base isolée via `DB_NAME` (fichier dans le dossier temporaire de session, jamais `backend/db.sqlite3`) ; base de test Django en mémoire.
- Aucun code applicatif modifié. Aucune permission refusée.

## Résultats
| Exécution | Résultat |
|---|---|
| `manage.py test treasury blockchain` (suite existante, 226 tests) | OK, 1 échec attendu préexistant (`expectedFailure`), 1660 s |
| `treasury.tests.test_regression_528875c_2026_11_19` (15 nouveaux tests) | OK, 15/15, 300 s |

**Aucune anomalie : aucun BUG-NNN ouvert** (prochain numéro libre : BUG-313).

## Nouveaux tests
Fichier : `backend/treasury/tests/test_regression_528875c_2026_11_19.py`.
Journée de référence (calculée à la main), boulangerie R1 :
- Équipe A : vente cash 40 x 500 = 20 000, puis sorties -3 000 (Retrait d'épargne), -1 500 (Emprunt boulanger), -500 (Manquant d'équipe).
- Équipe B : vente cash 2 x 500 = 1 000. Dépense locale 700.
- Cash A = 15 000 (crédit A = 5 000, variation de BP des sorties), cash B = 1 000, total 16 000, caisse nette = 15 300.

Couverture :
- Rapport facturier A/B avec paiements négatifs ; motifs conservés ; somme des rapports = somme algébrique des paiements livrés.
- Clôture gérant : 15 300 net ; billets 10 000+5 000+200+100 = 15 300, écart 0 ; sans les 100 : écart -100 ; PATCH des billets recalcule l'écart ; 8 coupures (1x20 000 + 2x10 000 + 3x5 000 + 4x1 000 + 5x500 + 6x200 + 7x100 + 8x50 = 63 800, net 63 500, écart +300).
- Clôture à caisse nette négative (R2 : -2 500, aucun billet, écart +2 500) : écriture au livre en **sortie** (entrée 0, sortie 2 500), solde 15 300 puis 12 800, pièces `VC-R1-AAAAMMJJ` / `VC-R2-AAAAMMJJ`.
- Hash SHA-256 inchangé : formule v3 réécrite à la main dans le test, identique à `block_hash` ; chaînage `previous_hash` (genèse puis hash du bloc 1) ; `CashbookHead` (compte 2, dernier hash, code R2).
- Vérification : `integrity_check` (treasury) et `run_check` (blockchain) donnent le même verdict, sain, puis altération directe de `exit_amount` détectée par les deux ; suppression SQL directe des écritures détectée par l'ancre `CashbookHead` (`head_problem`) des deux côtés.
- Livre en lecture seule (POST/PUT/PATCH/DELETE = 405) ; double versement refusé (400).
- BUG-306 : même journée avec et sans fournée en cours (boulangeries R1 et R3) donne des chiffres identiques (15 000 / 5 000 / 1 000 / 0 / 16 000 / 15 300 / 0). La fournée reçoit 42 pains, `qty_produced` = 42, total 21 000 FC, écart de sacs équipe A = 20 000 - 2 x 210 000 = -400 000, sans effet sur le cash.
- BUG-304 : reste d'hier (10 pour A, 5 pour B la veille) = -5 en pains, -2 500 FC ; la lecture de `daily-closure` ne crée aucun rapport, clôture ni écriture ; la clôture reste à 15 300.
- Journée complète : rapports, clôture, validation, versement, vérification de chaîne, tous cohérents.
- Concurrence : 4 versements simultanés de clôtures de 4 boulangeries (3 000 + 4 000 + 5 000 + 6 000) via `promote_closure_to_cashbook` : le test s'est exécuté sur SQLite sans verrouillage (non sauté), 4 `previous_hash` distincts, solde final 18 000, `CashbookHead` à 4. Le test est conçu pour se sauter en documentant l'erreur si SQLite répond « database is locked ».

## Observations (sans ticket)
1. **Sans rotation d'équipes, une livraison de l'équipe B incrémente la fournée « en cours » de l'équipe A** (42 pains pour 40 vendus par A). Conforme au code de `find_open_batch_for_sale` (seule la rotation filtre par équipe) ; sans effet sur les montants de caisse, mais `breads_produced_by_category` du rapport de A reflète 42. A trancher par `testeur-production` / coordinateur (équipe de la livraison ou équipe en service).
2. Le crédit du rapport facturier compte les sorties négatives (5 000 pour A). C'est la décision BUG-290 (variation de BP), déjà verrouillée par `sales/tests/test_bug290_*`.
3. Le test PATCH des billets accepte 15 500 ou 15 700 : la sémantique PATCH sur les billets omis (remis à zéro ou conservés) n'est pas spécifiée ; à préciser si elle compte.
4. Durée : la suite treasury+blockchain dure 28 min sur ce poste (les 15 nouveaux tests : 5 min) ; à surveiller pour l'intégration continue.
