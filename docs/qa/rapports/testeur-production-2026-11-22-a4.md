# Rapport testeur-production (Dev A) - 2026-11-22, cycle a4

Périmètre : revérification des tickets production CORRIGÉ (540, 541, 562, 612, 620, 621, 622, 623, 624, 627) et contre-attaque sur les voisinages. Aucun code applicatif modifié.

## Tests
- Nouveau : `backend/production/tests/test_verif_a4_testeur_production.py` (43 tests, données fictives, base de test isolée, sans `--parallel`).
- Rejeu ciblé : ce fichier + `test_production_v2_a3`, `test_verif_bug612_a3`, `test_bug620_627_dev_a`, `test_bug540_541_562_6nn_dev_a`, `test_verif_bug522_c`, `test_verif_direct_consommables_c`, `test_verif_bug303_304_306_testeur_production` : **199 tests, OK, 6 échecs attendus** (BUG-625 x1, nouveaux 652 x2, 653, 654 x2).

## Tickets revérifiés : tous VÉRIFIÉS
| Ticket | Résultat |
|---|---|
| BUG-540 | envoi direct vers SIEGE (id, code, casse, espaces), nœud inactif, soi-même, 0, négatif, booléen, flottant, `1.0`, chaîne vide, liste, objet, chiffre Unicode, 2^31, 10^40 : 400, aucun stock déduit |
| BUG-541 | mêmes valeurs côté destinataire ; `dispatch/` déjà couvert (BoolNodeAsPk, FloatDestination : décorateurs retirés par le dev, verts) |
| BUG-562 | `1e400`, `1E+999999`, NaN, Infinity : 400 (tests du dev rejoués verts) |
| BUG-612 | demande (`from_node` flottant, Unicode, SIEGE), lignes, réponse, réception, envoi : 400 sans effet de stock |
| BUG-620 | voir ci-dessous |
| BUG-621 | `approved` : null, objet, `"null"`, `" "`, `"yes"`, `"vrai"`, 2, -1, 0.0, 1.0, liste, `"1"` arabe : 400 ; `" TRUE "` accepté ; multipart `"0"` 400 puis `"false"` = refus ; aucun stock déduit sur refus |
| BUG-622 | doublons de catégorie (POST/PATCH), PATCH et PUT de la date/équipe vers une session existante, déplacement par le siège vers un nœud déjà occupé : 400 |
| BUG-623 | plafond exact 4 000 000 x 500 FC = 2 000 000 000 accepté ; +1 pain (nouveau POST du jour cumulé, PATCH) refusé ; deux lignes dont la somme dépasse refusées sans trace ; ligne CARRYOVER + PATCH reste <= int32 ; quantités 10^40, 2^63, NaN, booléen : < 500 |
| BUG-624 | PATCH/DELETE d'une demande en attente : fournisseur, facturier, livreur 403 ; tiers 404 ; demandeur, siège OK ; champs figés (from/to/initiated_by, statut, flow, lignes) inchangés ; envoi direct engagé (RESPONDED) non modifiable ni supprimable par personne |
| BUG-627 | demande vers SIEGE ou nœud inactif : 400 |

### Les 3 tests BUG-620 ajustés par le dev : non affaiblis
Fichier non suivi par git (pas de `git diff` possible), comparé à l'énoncé du ticket et au rapport a3. Les assertions portent toujours sur : refus 400 d'une validation partielle ou d'une catégorie inconnue, aucun crédit du récepteur, transfert resté RESPONDED, puis somme du groupe = 100 après validation COMPLÈTE (demande et envoi direct). Le changement (400 au lieu de CONFIRMED immédiat) est l'une des deux issues permises par le ticket. Les pains non reçus restent « en transit » (K1 -7, groupe 93) jusqu'à validation complète : état identique à tout transfert RESPONDED en attente. Les autres diffs de tests (`test_verif_bug522_c` : fournisseur 403 sur PUT = BUG-624 ; `test_verif_bug303_304_306` : BUG-319, livraison sans ligne ; `test_verif_direct_consommables_c` : retrait des `@expectedFailure` 540/541) sont légitimes et ne retirent aucune assertion.

### Somme du groupe après confirmation complète
Rejouée sur : demande 2 lignes, envoi direct 2 lignes, 3 catégories avec séquence de litiges (le manquant est le seul écart du groupe pendant le litige, 100/100/50 à la fin), sur-réception 2 000 000 000 puis exact, litige tout à 0 (DISPUTED, clôture bloquée, `ALIGN_ON_RECEIVED` restitue K1, groupe 100, re-validation refusée 400), validation par le siège. Toujours nulle.

## Nouveaux angles verts (sans anomalie)
Ligne `quantity_received` absente = 0 = litige ; doublons id int/chaîne, `bread_price` null, corps vides ou mal typés : 400 sans effet ; double validation ; émetteur d'un envoi direct, tiers, facturier, livreur : 403/404 ; confirmation d'une demande en attente ou annulée refusée ; 3e boulangerie ne voit rien (liste, détail, résolution : 404) ; envoi : doublons cumulés = stock exact accepté puis stock épuisé 400 ; comptes siège sans boulangerie : 400 ; notes non texte 400 ; corps non objet < 500 ; fournée : unicité équipe/date cumulée, isolation par nœud (404 en lecture/PATCH/DELETE), consommables hostiles < 500, dates invalides 400, sacs hors bornes 400 ; dispositions : isolation, rôles, prix unitaire négatif refusé, suppression restitue le stock, REMAINING n'y touche pas.

## Nouveaux tickets
- **BUG-652** (Mineur) : `respond_to_request` ignore une catégorie absente de la demande (`continue`) et déduit les quantités demandées ; une réponse positive toute à 0 est acceptée.
- **BUG-653** (Mineur) : `POST sessions/` accepte une date future (J+400).
- **BUG-654** (Mineur) : chiffres Unicode (« ٣ ») acceptés comme quantités (transfert, réception, envoi, ligne de fournée) et comme `flour_sacks_used`, alors que `_strict_pk` les refuse.
- BUG-625 (À CLARIFIER) : précisé, le COMPTABLE peut aussi `PATCH` une demande de transfert en attente (200). BUG-626 inchangé (à B).

## Observation non ouverte
`respond_to_request` accepte une quantité supérieure au stock (stock négatif) alors que `send/` la refuse (déjà noté en a3, à arbitrer).
