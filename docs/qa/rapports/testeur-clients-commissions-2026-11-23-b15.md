# Testeur clients/commissions, ronde b15 (2026-11-23)

Fichier de tests : `backend/clients/tests/test_clients_v11.py` (54 tests, 4 `@expectedFailure`). Données fictives, SQLite, code applicatif non modifié.
Log : `$TEMP/b15.log`.

## Contre-vérification de la correction d40
Les trois tickets étaient déjà passés VÉRIFIÉ par c15 (testeur-tresorerie) ; contre-vérification indépendante, notes ajoutées sur les lignes du registre.

- BUG-981 : stamp poste à +2 h / +10 h appliqué ET trace `HORLOGE_POSTE_EN_AVANCE` avec les valeurs écrasées (90000 -> 60000) ; tolérance 5 min (+4 min : rien, +6 min : trace) ; clé `identity_updated_at` future aussi tracée ; aucun changement réel ou champ invalide : pas de trace ; rejeu x3 : une seule ligne ; stamp serveur posé (pas de poisoning) ; dette jamais touchée. Résiduel : BUG-995.
- BUG-982 : 5 pushs obsolètes = 1 conflit (occurrences 5) + 1 notification ; deux clients = 2 notifications ; conflit résolu puis nouvel obsolète = renotifié ; préfixes de codes (`K1-9001` / `K1-90010`) non confondus ; rejeu à valeurs identiques : ni conflit ni notification.
- BUG-984 : variantes MAJUSCULES / sans tirets / accolades = même client, le premier gagne dans les deux ordres. Autres modèles du lot : `_preflight` normalise l'id des 15 modèles à PK UUID avant le handler ; DebtMovement (4 variantes = comptabilisé une fois, montant différent = rejeté + conflit `MOUVEMENT_IMMUABLE_MODIFIE`), Invoice, SocialContribution : un seul enregistrement, aucun double comptage. Lignes de facture à PK entière : hors sujet. Aucun problème réel, pas de ticket.

## Balayage partie B
| Axe | Résultat |
|---|---|
| Commissions vs sync | `ClientCommission`/`CommissionPeriod` ne sont jamais poussées ni redescendues, conformément à SYNC.md §1 l.58 (calcul au cloud) ; `generate` est réservé au siège (`IsHeadquarters`) : pas d'incohérence de paie multi-boulangeries entre postes (BUG-737 s'applique sur une seule base). Mais la paie dépend des factures poussées : **BUG-993** (date de facture perdue). |
| Caisse sociale close / BUG-953 | Reste À CLARIFIER. Angles voisins constatés (même question client) : suppression d'une cotisation payée en année close = 204, `bulk_create_month` = 200, push sync `is_paid=false` = ACCEPTED ; la distribution close refuse toujours réouverture, `auto_populate_lines`, `refresh_indices`. |
| Import Excel | NFC/NFD et casse = même client (dédoublonné), doublons internes comptés une fois, 3 000 lignes en 4,95 s, codes uniques `K1-`, apostrophes/tirets/emoji OK, non-Excel = 400, gérant/facturier/livreur = 403, dry-run sans écriture. Observation (pas de ticket) : la création se fait ligne par ligne hors transaction ; un échec en cours de route laisse un import partiel, mais le rejeu est idempotent. |
| Recherche (KIESE_FOLD) sous charge | 5 000 clients : `elodie`/`ELODIE`/`Élodie`/`élod` = 100 résultats exacts en 132-150 ms ; 20 recherches par code : max 158 ms, code exact en tête ; téléphone partiel OK ; termes hostiles (`%`, `_`, SQL, NUL, emoji, 200 caractères) : jamais de 500. |
| Permissions croisées | Gérant K1 vs client K2 : détail/PATCH/DELETE/recalculate_category/history = 404, bulk_move/bulk_delete = 403, cotisation et commission K2 invisibles (404), mark_paid/set_manuel refusés, generate/payroll_listing = 403, création de cotisation pour client K2 = 400, déplacement par PATCH node ignoré, filtres `node`/`search` sans fuite. Facturier K1 voit le client K2 mais ne le modifie pas (403) et n'accède ni aux commissions ni aux cotisations. Aucun défaut. |
| Pull d'un poste neuf, 5 000 clients | Serveur : 0,20 s, 1,32 Mo, une seule réponse, pas de N+1 (requêtes identiques à 5 000 et 200 clients), ids uniques, curseur `since_client_debt` : second pull vide, un client modifié redescend seul. Application sur poste existant : 10,1 s pour 5 000 lignes (SQLite). Pas de pagination : acceptable à cette volumétrie (risque noté : 50 000 clients = 13 Mo et timeout client de 30 s), pas de ticket. **BUG-994** : sur base vide aucun client n'est créé. |

## Tickets ouverts (3)
- **BUG-993** (Majeur) : `invoice_date` jamais transportée par le push de facture : date du jour du push, donc mauvaise période de commission.
- **BUG-994** (Majeur) : `apply_pull_response` ignore les clients inconnus : un poste neuf ne reçoit aucun client.
- **BUG-995** (Mineur) : le 2e écrasement par un poste en avance ne conserve pas les valeurs écrasées (dédoublonnage du conflit).

## Résultat
Voir la ligne finale du log (54 tests : tous verts hors 4 `@expectedFailure` : 993 x2, 994, 995).
