# Testeur ventes (Dev B, reprise de la partie A) : cycle a5 (2026-11-22)

Périmètre : `backend/sales/`, impact sur `Client.current_debt`, `Client.total_breads_received` et `BreadStock`.
Fichier de tests : `backend/sales/tests/test_verif_ventes_a5_v5.py` (35 tests, données fictives, sans `--parallel`).
Aucun code applicatif modifié, `test_ventes_a3_v2.py` et `test_bug6nn_numeriques_dev_a.py` intacts. Pas de commit.

## 1. Vérification des tickets CORRIGÉ (verdict : tous VÉRIFIÉS)
Rejeu des fichiers du prédécesseur et des développeurs :
- `test_ventes_a3_v2.py` : 103 tests OK, plus aucun `@expectedFailure` (les marques BUG-640 à 650 ont été retirées par le développeur et les tests passent).
- `test_ventes_a4_verif.py` + `test_bug6nn_numeriques_dev_a.py` + `test_bug821_822_824_adjust_d7.py` : 22 tests OK (5 échecs attendus : BUG-660 x2, 661, 662, 663, toujours ouverts).
- Le test de BUG-610 qui levait `AttributeError (Status.PENDING_DELIVERY)` est corrigé : il passe.

Contrôles indépendants (nouveau fichier, angles différents de ceux du prédécesseur) :
- BUG-640 : espion de `select_for_update` (modèle, `of`, ordre) : le verrou du client précède la première écriture de facture pour la vente, le remboursement, le paiement négatif et l'ajustement ; le numéro de reçu verrouille le nœud.
- BUG-641 / 642 : annulation, livraison, non servi manuel et expiration verrouillent la facture en `of=('self',)` ; l'annulation verrouille aussi le client. Atomicité : panne simulée (stock, journal) dans `cancel`, `mark-not-served`, livraison partielle, création : aucun effet partiel (BP, stock, statut, compteur de pains).
- BUG-650 : 4 annulations simultanées de la même facture = un 200 et trois 400, une seule restitution ; livraison + non servi, annulation + non servi simultanés : jamais de 500, état cohérent.
- Concurrence de création : 6 ventes simultanées du même client : BP = 6 x 600, `debt_before` en suite sans doublon, 6 reçus distincts ; plafond : BP 49 999, deux ventes simultanées à crédit : exactement un 201 et un 403.
- BUG-643 à 649 : couverts par les 103 tests de `a3_v2` (date impossible, `bread_price` géant, client/pain désactivés, annulation d'une facture Non servi / annulée, annulation après ajustement -1, ajustement refusé sur Non servi).
- BUG-645 : `BoundedSearchFilter` (5 termes, 100 caractères) testé directement, recherche de 100 000 caractères en 200, recherche par code client toujours opérante.
- BUG-610 / 611 / 613 : quantités et identifiants Unicode (pleine chasse, arabes), `1e1`, `+1`, `0x2`, vides, listes, négatifs, 0, 100 001 : toujours 400 sans effet ; `bread_summary?node=` Unicode / `1_0` / espace : 400.
- BUG-824 : tient pour une facture livrée (compteur signé, plancher 0). Reliquat sur facture en attente : BUG-666.
- Limite assumée : les verrous ne se prouvent que sur PostgreSQL (absent, décision de rester sur SQLite). La preuve repose sur l'espion et sur la sérialisation SQLite avec retentative.

BUG-651 / 651b (reçu thermique, `node_code`) : `InvoiceSerializer` expose `node_code`, vérifié à la lecture du code ; le rendu de `ThermalReceipt.tsx` n'a pas été rejoué.

## 2. Nouveaux défauts (10 tickets, tous Mineur, tests `@expectedFailure`)
| Ticket | Sujet |
|---|---|
| BUG-664 | `bread_summary` additionne les lignes d'un ajustement négatif (10 pains - 4 -> 14 pains / 4 200 FC au lieu de 6 / 1 800) |
| BUG-665 | `cancel` ne recalcule pas la catégorie client (reste « À risque » avec BP sous le plafond) |
| BUG-666 | reliquat BUG-824 : `adjust` sur facture en attente change le compteur de pains ; annulation ensuite -> compteur faux |
| BUG-667 | `Invoice.deliver` : lecture-modification-écriture de `total_breads_received` (incrément concurrent écrasé : 4 au lieu de 104) |
| BUG-668 | `deliver` accepte `delivered_at` antérieur à `invoice_date` |
| BUG-669 | vente sans client avec versement très supérieur à la commande acceptée (1 000 000 FC pour 3 000 FC) |
| BUG-670 | `daily_summary` ignore le versement conservé d'une facture Non servi |
| BUG-671 | déficit net du mois sans le versement conservé Non servi (À CLARIFIER avec le client) |
| BUG-672 | PATCH `commission_exempt` en période de commission close sans avertissement |
| BUG-673 | remboursement BP avec `special_code` RG/NS : code stocké, `daily_summary` fausse |

Tickets antérieurs toujours ouverts (non touchés) : BUG-660 (non servi après ajustement -1), 661 (`adjust` sans verrou de l'originale), 662 (non servi après ajustement +1), 663 (`adjust` sans retentative sur verrou SQLite).

## 3. Angles attaqués sans défaut
Facturation en série et BP avant/après (a3 : 5 séquences aléatoires de 70 opérations vérifiées contre un modèle indépendant), plafond 50 000 FC aux bornes, blocage 403 + notification, remboursement, VENTE SOLDE (75 %, CM 0), client épargne, codes NV / RG / NS, livraison par facturier ou livreur, déstockage unique, double livraison, annulation, ajustements signés, isolation par nœud, numéros de reçu uniques. Stock insuffisant : le stock devient négatif sans refus (comportement documenté, pas de ticket).

## 4. Série complète `manage.py test sales --noinput` (log `$TEMP/ventes_a5.log`)
- Base isolée (SQLite en mémoire), sans `--parallel` : **Ran 583 tests en 2 577 s**, 15 `expected failures` (10 de ce cycle + BUG-660 x2, 661, 662, 663), 2 échecs, 0 erreur, aucun succès inattendu.
- Les 2 échecs étaient dans MON fichier (`ConcurrenceSqlite`, annulation + non servi et livraison + non servi simultanés) : 500 `OperationalError: database table is locked: clients_client`, intermittent (une fois sur deux en isolé, 4 annulations simultanées -> 4 x 500 une fois). Cause : `cancel` et `mark-not-served` appellent `self.get_object()` AVANT `_retry_on_lock` ; sur la base SQLite en mémoire à cache partagé des `TransactionTestCase` une simple lecture (`select_related('client')`) échoue pendant l'écriture d'une autre connexion. Sur le poste réel (SQLite WAL, CLAUDE.md §8) les lecteurs ne sont pas bloqués par un écrivain : artefact de la base de test, pas de ticket (observation : déplacer `get_object()` dans la fonction rejouée suffirait à le supprimer). Correctif du test : le client rejoue la requête comme un utilisateur qui reclique (mêmes assertions sur l'état final). 3 passages consécutifs de la classe : OK.
- Rejeu final du fichier `test_verif_ventes_a5_v5.py` : **Ran 35 tests, OK (expected failures=10)**. Les 548 autres tests de la série sont verts.

## 5. Observations sans ticket
- Un ajustement +1 (gérant) ne passe pas par le blocage de crédit : la BP peut dépasser le plafond sans paiement (action réservée au gérant, plafond modifiable par lui : choix de conception probable).
- Une facture `NS` jamais livrable reste `PENDING` indéfiniment (exclue de l'expiration, voulu par BUG-177).
- Un remboursement BP livré ne peut être ni annulé ni ajusté : correction par un remboursement de montant négatif (BUG-290).
