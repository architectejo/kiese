# Testeur ventes (Dev A) : cycle a3, nouveaux angles (2026-11-22-a3)

Périmètre : `backend/sales/`, impact sur `Client.current_debt` et `BreadStock`, revue de code de `ThermalReceipt.tsx`.
Fichier de tests : `backend/sales/tests/test_ventes_a3_v2.py` (99 tests, données fictives, base isolée dans le scratchpad, sans `--parallel`).
Aucun code applicatif modifié. Pas de commit.

## Vérification des tickets ventes CORRIGÉ
Aucun ticket ventes `CORRIGÉ` non vérifié n'était en attente (BUG-527, 508, 363, 519 déjà VÉRIFIÉ par testeur-ventes C).
BUG-610, 611, 613 (dev-backend, audit numérique, CORRIGÉ) : mes tests `test_deliver_lines_invalides` et `test_adjust_parametres_invalides` / `test_adjust_quantite_decimale_ou_booleenne_non_tronquee` passent (booléens, flottants, géants, chaînes énormes, `1.9`, `True` refusés en 400 sur `deliver` et `adjust`). Statut laissé au testeur d'origine de ces tickets (dev-backend les a écrits eux-mêmes, je n'ai pas rejoué leur fichier `test_bug6nn_numeriques_dev_a.py`).

## Angles couverts (tous verts sauf les défauts ci-dessous)
- BP cumulatif (plusieurs ventes, changement de mois avec horloge simulée 30/09 -> 01/10), jamais remis à zéro.
- Plafond 50 000 FC aux bornes (49 999 / 50 000 / 50 001 ; paiement = commande -1 / = / +1), plafond 0, plafond propre au client, refus sans écriture (ni BP, ni stock, ni numéro de reçu), notification, déficit net du mois avec CM déduite.
- Vente solde (75 %, CM 0, BP inchangée, blocage calculé sur le prix à 75 %, arrondi par ligne), client épargne (dépôt, BP négative, vente sur BP négative), remboursement (sans ligne, ignore lignes et `is_soldee` envoyés, pas de stock, pas de chiffre d'affaires), paiements négatifs (sortie de caisse, jamais de contournement du plafond), NV, RG, NS (crédit/comptant, stock intact, non livrable), vente sans client.
- Paramètres invalides : `payment_amount` (NaN, Infinity, exposants, `1e400`, booléens, listes, 100 000 caractères...), `quantity`, `bread_price`, `lines`, `client`, énumérations, dates, `node` (facturier et siège), corps non objet, mass-assignment (statut, BP, reçu, facturier... ignorés), filtres/pagination, identifiants d'URL, PATCH `commission_exempt`.
- Rôles et isolation : `node` forcé ignoré (facturier, gérant), livreur sans création/annulation/ajustement, anonyme 401 partout, autre boulangerie 403/404 sur toutes les actions, listes/`bread_summary`/`daily_summary` sans fuite, facturier peut facturer un client d'une autre boulangerie (remarque.md), compte sans boulangerie, utilisateur inactif.
- Livraison (facturier, gérant ou livreur du même nœud), double livraison séquentielle (déstockage et `total_breads_received` une seule fois), expiration 12 h (11 h 59 livrable, 12 h 01 -> Non servi, idempotente, isolée par nœud, ne touche pas NS/remboursements/livrées), livraison partielle (soldée, sans client, zéro partout refusé, ligne à zéro), annulation (BP et stock restaurés, journalisé), ajustement (plafond du net, lignes cumulées d'un même pain).
- 5 séquences aléatoires (70 opérations chacune : création, remboursement, annulation, livraison totale/partielle, non servi, expiration, ajustement) comparées après CHAQUE opération à un modèle indépendant de `current_debt` et du stock : **toutes vertes**.
- Numéros de reçu uniques (tous types, par boulangerie, format `AAA-AAAAMMJJ-NNNN`).
- Concurrence (TransactionTestCase, threads) : annulation + livraison simultanées -> état cohérent ; 5 livraisons simultanées -> voir BUG-650.

## Résultats
- Fichier `test_ventes_a3_v2.py` : 1er passage 99 tests, 16 échecs + 1 succès inattendu. Triage : 11 attentes de test erronées corrigées (`facturier_display` vide sans nom, 403 au lieu de 404 pour un facturier qui ajuste, compte sans boulangerie 403, notification en double, `1_000` / chiffres arabes / `1.0` / `2026-1-1` acceptés par Python/DRF et valides, test de jointure à corriger : les jointures de `select_related` n'existent qu'à la compilation, il faut lire `str(qs.query)`), 11 défauts réels (tickets ci-dessous), `@expectedFailure` posés. 2e passage ciblé sur les tests modifiés : 58 tests, 4 échecs résiduels (`'9'*400` en `bread_price`, `2026-1-1` valide, chiffres arabes, concurrence) triés de même.
- Série complète `manage.py test sales --noinput` : voir la dernière section.

## Tickets ouverts
| Ticket | Gravité | Sujet |
|---|---|---|
| BUG-640 | Majeur | BP client lue sans `select_for_update` (création, remboursement, ajustement) : plafond contournable et reçu faux en concurrence PostgreSQL |
| BUG-641 | Majeur (à confirmer PostgreSQL) | `_lock()` : `FOR UPDATE` + `select_related` sur FK nullable -> `LEFT OUTER JOIN` : 500 probable à chaque livraison / non servi sur PostgreSQL |
| BUG-642 | Majeur | `cancel()` non atomique, sans verrou : double restitution possible |
| BUG-648 | Majeur | annulation d'une facture déjà ajustée (-1) : BP -300 FC et stock -1 (client crédité à tort) |
| BUG-643 | Mineur | `deliver` `delivered_at=2026-02-30` -> 500 (`parse_date` ValueError) |
| BUG-644 | Mineur | `bread_price` >= 2**63 -> 500 à la création |
| BUG-645 | Mineur | `?search=` de 100 000 caractères -> 500 (SQLite) |
| BUG-646 | Mineur | facture possible pour client désactivé et pain désactivé |
| BUG-647 | Mineur | `cancel` accepte NOT_SERVED (réécrit en CANCELLED) et CANCELLED (200 + journal) |
| BUG-649 | Mineur | `adjust` +1 accepté sur facture NOT_SERVED |
| BUG-650 | Mineur | `deliver` sans retentative sur « table is locked » (double clic SQLite desktop : 5 x 500) |
| BUG-651 | Mineur (frontend) | `ThermalReceipt.tsx` : commission avec décimales, « NOUVELLE DETTE » pour BP négative |

BUG-540/541/562 non touchés. Stock insuffisant : aucun refus, le stock devient négatif (comportement observé, cohérent avec la décision client sur le stock négatif, pas de ticket).

## Observations sans ticket
- Python/DRF acceptent `1_000` (soulignés) et chiffres Unicode dans un montant : sans conséquence monétaire, noté.
- Les reçus : toutes les mentions §5.2 sont exposées par l'API (`receipt_number`, `node_display`, `created_at`, `team`, client, lignes, `order_total`, `payment_amount`, `commission_rate`, `debt_before`, `debt_after`) ; `ThermalReceipt.tsx` imprime entête légal (ID.Nat, Impôt, RCCM), date/heure, facturier + équipe, client, lignes, versement, commission, BP avant/après, « Solde arrêté ce jour ».
- Aucun banc de rendu : le contrôle du composant est par lecture de code.

## Série complète `manage.py test sales --noinput`
- Base isolée (scratchpad), sans `--parallel` : **Ran 530 tests** en 6 833 s ; 15 `expected failures` (les 15 tickets BUG-640 à BUG-650 de ce cycle), 1 échec, 1 erreur.
- L'échec était `test_deliver_delivered_at_illisible` (mon test : `[]` et `{}` sont ignorés comme « absents » par `deliver`, donc livraison normale ; attente corrigée, test rejoué : OK, BUG-643 en `expected failure`). Fichier à 99 tests, 15 `@expectedFailure` ; aucun succès inattendu.
- L'erreur n'est PAS dans mon fichier : `sales/tests/test_bug6nn_numeriques_dev_a.py::DeliverServedLines::test_nan_inf_float_id_and_huge_are_400_not_500` (dev-backend, BUG-610) lève `AttributeError: type object 'Status' has no attribute 'PENDING_DELIVERY'` (le statut s'appelle `Invoice.Status.PENDING`). Le test ne peut pas passer tant qu'il n'est pas corrigé : BUG-610 ne peut pas être VÉRIFIÉ sur la foi de ce fichier ; à corriger par dev-backend (je ne modifie pas ses tests).
