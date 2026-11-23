# Rapport auditeur-comptable (Dev C) - cycle 5 - 2026-11-22

Etat : branche dev-b, SQLite. Code applicatif non modifie, donnees fictives.
Tests : `backend/finance/tests/test_audit_c_cycle5_v5.py` (20 tests, tous verts) ; `finance.tests.test_audit_c_cycle2_c` rejoue sans `@expectedFailure` (18 verts) : 38 tests OK.

## 1. Verification de BUG-821 / 822 / 824

| Ticket | Angles rejoues | Resultat |
|---|---|---|
| BUG-821 | Ajustement + et - d'une RG : aucune CM ; ajustement le jour suivant ; client mixte (vente reguliere 2 000 + RG ajustee) : CM sur 2 000 seulement (500), quantite 4 ; ajustement d'une vente reguliere : toujours compte (3 000 / 6 pains) ; RG ajustee absente du CA | VERIFIE |
| BUG-822 (commissions) | Chaine -3 puis +1 : total_breads 8, valeur 4 000, CM 1 000 ; regeneration idempotente (1 seule ligne, memes valeurs) ; DOC 1 qty_500 = total_breads ; retour du mois suivant seul : pas de ligne, pas de quantite negative | VERIFIE |
| BUG-824 | 10 -> 7 -> 12 ; ajustement multi-lignes ; NS sans effet ; plancher a 0 ; categorie Meilleur client suit le seuil dans les deux sens ; autre client intact | VERIFIE |

Les trois tickets passent a VERIFIE dans le registre.

## 2. Recoupements

| Controle | Resultat |
|---|---|
| Somme des `order_value` des commissions = CA du compte de resultat (avec ajustement negatif) | Egal (5 600) |
| Net a payer = CM - retenue dette - social - cartes - autre - report ; REMISE 0,25 % (4,50 sur 1 800) | Conforme, tous montants a 2 decimales, aucune derive |
| Retenue dette = `current_debt` apres ajustement (800) | Egal |
| Retenue unique BUG-737, 2 boulangeries, avec ajustement : dette 2 500 et social 2 000 retenus une seule fois, 2e ligne a 0 ; CM cumulee = 25 % de 2 500 | Conforme |
| BP client = somme(commande signee - versement signe) des factures livrees (avec ajustements) | Egale |
| N / N-1, DOC 1 (cycle 4) : aucun changement de code constate dans finance/ | Non rouverts |

Remarque : le dev-backend signale 3 echecs trésorerie (`test_verif_tresorerie_c5_v4`) lors d'un run combine ; hors perimetre, non reproduits ici (aucun test treasury lance), a confirmer par le testeur trésorerie.

## 3. Nouveaux tickets
0 nouveau ticket (plage BUG-880+ inutilisee). BUG-870, 748, 738, 742, 783, 808 non retraites.

## 4. Limites
SQLite seul ; la concurrence (verrous) n'est pas exercee ; `data_kiese/` non utilise.
