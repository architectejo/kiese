# Testeur Clients et Commissions, ronde b11 (2026-11-23)

Fichier de tests : `backend/clients/tests/test_clients_v8.py` (48 tests, 20 `@expectedFailure`, OK). Données fictives. Code applicatif non modifié. SQLite conservé.

## Vérifications (rapport dev-backend d29)
| Ticket | Résultat | Preuve |
|---|---|---|
| BUG-915 (reliquat `bulk_create_month`) | VÉRIFIÉ | `V915Verif` : montant non ASCII (arabe, pleine chasse, persan, devanagari), NaN, Infinity, négatif, 1e999, bool/liste/dict, hors borne : 400 sans rien créer ; montants ASCII, entiers JSON, null/vide, 99 999 999,99 : acceptés ; rejeu idempotent. |
| BUG-933 | VÉRIFIÉ | `V933Verif::test_BUG_933_*` : montant absent, null, vide, blancs, liste, dict, false : REJECTED, dette inchangée. |
| BUG-934 | VÉRIFIÉ | `V933Verif::test_BUG_934_*` : 0,004 / 0,005 / 1,001 / 1E-3 / float sous-centime rejetés ; 0,01, -0,01, 12,5, 7, 1E+2, 999999999999,99 acceptés ; zéro exact accepté sans trace ; cumul hors plage refusé. |

## Scénarios nouveaux couverts
- (a) Balayage REST (17 valeurs hostiles x champs) sur clients, cotisations, distributions, lignes, commissions, `set_manuel`, `generate`, `bulk_move`, `bulk_delete` : aucun 500, aucune valeur hostile acceptée ni non finie stockée.
- (b) `current_debt` : séquences mixtes REST + push, rejeu, ordre inversé, deux postes, bascule NORMAL/RISK : somme exacte (Decimal), dette d'ouverture conservée.
- (c) Lot complet : clés en ordre inverse, rejeu même batch et nouveau batch, client rejeté (dépendants rejetés puis repris), lot par morceaux dans le désordre, doublons dans un lot : idempotent et convergent.
- (d) Journal et notifications : contrôles positifs (création, `mark_paid`, `close_period`) + actions non tracées (tickets ci-dessous).
- (e) Deux postes : non-propriétaire rejeté, pull incrémental avec deux modifications simultanées (la dernière gagne, une seule ligne).

## Tickets ouverts (BUG-941 à BUG-950), tous `@expectedFailure`
| Ticket | Sévérité | Résumé | Test |
|---|---|---|---|
| BUG-941 | Majeur | Push `Client` du nœud propriétaire (téléphone, plafond, nom) : ACCEPTED mais jamais appliqué (SYNC.md 5.1 : dernier écrivain gagne) | `DeuxPostes::test_BUG_941_*` |
| BUG-942 | Majeur | Le pull n'applique ni le plafond ni l'identité sur le poste (catégorie RISK du Cloud appliquée avec l'ancien plafond local) | `DeuxPostes::test_BUG_942_*` |
| BUG-943 | Majeur | `PATCH` client : écrasement de `current_debt` / `total_breads_received` modifiés pendant la requête (perte d'une livraison) | `DebtMixed::test_BUG_943_*` |
| BUG-944 | Mineur | Aucune trace `log_activity` : modification plafond/taux, suppression unitaire client, cotisation payée (`toggle_paid`), génération mensuelle, clôture irréversible de distribution, lignes, commissions (modification, suppression) | `Journal::test_BUG_944*` (8) |
| BUG-945 | Mineur | Pas de notification quand un client devient « à risque » par push `DebtMovement` ou baisse de plafond (la livraison REST et `recalculate_category` notifient) | `DebtMixed::test_BUG_945*` (2) |
| BUG-946 | Mineur | Année d'une cotisation sans borne en REST (0, 1, 1999, 32767 acceptés ; push 2000+, `bulk_create_month` 2000-2100) | `SweepRest::test_BUG_946_*` |
| BUG-947 | Mineur | `is_paid` posé par `PATCH` : `paid_at` vide ; remis à faux : `paid_at` conservé | `SweepRest::test_BUG_947*` (2) |
| BUG-948 | Mineur | Le siège peut, par `PATCH`, rattacher une cotisation à un client d'une autre boulangerie ou changer son `node` (incohérence client/boulangerie) | `SweepRest::test_BUG_948*` (2) |
| BUG-949 | Mineur | `PATCH node` par le siège ne régénère pas le code (`K1-0001` reste sur K3, contrairement à `bulk_move`) | `SweepRest::test_BUG_949_*` |
| BUG-950 | Mineur | `bulk_create_month` avec `amount` = 0 explicite : remplacé par la cotisation par défaut (0 traité comme absent) | `V915Verif::test_BUG_950_*` |

## Observations non ticketées
- `Config.get_instance()` journalise et notifie « Configuration mise à jour » à sa création : bruit possible dans le journal et les notifications sur une base neuve (les tests l'excluent).
- DRF convertit un nom numérique (`last_name: 12`) en chaîne : comportement standard, non retenu.
