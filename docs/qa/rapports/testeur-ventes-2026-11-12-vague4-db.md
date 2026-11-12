# Rapport testeur-ventes — vague 4 sur la base réelle (K1) — 2026-11-12

Périmètre : décision client « Rapport Journalier = jour calendaire » (BUG-271 backend, BUG-272 frontend), vue Ventes et Trésorerie. API `localhost:8000` + UI `localhost:5173`, K1 uniquement, comptes `zz_ventes_*`, clients `ZZTEST Ventes n`. Aucun code applicatif modifié, aucun migrate/SQL, pas de reset, aucun git. Rotation K1 : constatée `False` à l'arrivée, activée (une écriture du seul drapeau `team_rotation_enabled` par le shell Django, faute de compte gérant K1 connu), remise à `False` à la fin (vérifié).

## Méthode
- Live (rotation active, 18:11 locale, équipe A désignée pour la période du jour) : séries de ventes, rétroactif, livraisons, concurrence, plafond, etc.
- Horloge simulée (base de test) pour tout ce qui dépend de l'heure (03:00, 00:05, relève 12:00, minuit) : impossible à rejouer en direct.
- Playwright (`--output` perso, délais longs) à 360 et 1440 px.
- Tests : `backend/sales/tests/test_vague4_calendaire_ventes_2026_11_12.py` (14 tests : 11 OK + 3 `@expectedFailure` BUG-273/274/275), `test_vague2_db_ventes_2026_11_12.py` (9 OK), `e2e/tests/15-ventes-vague4-calendaire-db.spec.ts` (4 OK : reçu et désignation, pos et bureau).

## Décision calendaire : résultats
| Point | Résultat |
|---|---|
| Vente à 03:00 = jour calendaire, reçu `K1-20261112-0001` ; vente de 23:50 la veille = `K1-20261111-0001` (séries par date) | OK (test) |
| Relève 12:00 : change l'équipe (B -> A), ni la date ni la série de numéros | OK |
| Numéros uniques après suppression d'une facture expirée (compteur + boucle d'unicité) | OK |
| Équipe d'une vente rétroactive = équipe de service à l'heure de la vente (11/11 15:00 -> B ; 11/11 03:00 -> période du 10/11 -> A) ; sans désignation : équipe du compte, jamais de blocage | OK (test et live : vente datée de la veille acceptée, future refusée 400) |
| Blocage rotation sans équipe désignée : 403 `TEAM_NOT_ASSIGNED` pour vente, vente occasionnelle, remboursement, vente avec `invoice_date` = aujourd'hui ; livreur ne désigne pas (403) ; après désignation : 201, équipe désignée portée (pas celle du compte) | OK |
| À 03:00 la désignation du 12/11 (relève 12:00) ne vaut pas pour la période du matin : blocage puis désignation ; `work_date` = jour calendaire, `shift_date` = période | OK |
| Nœud sans rotation : aucun blocage, équipe du compte, reçu `K9-20261112-0001` à 03:00 | OK |
| Rapport facturier : un rapport par (équipe, date) pour A et B le même jour calendaire (cash A 500 / B 1 000 ; crédit A 2 500 / B 1 500), régénération idempotente (toujours 2) | OK |
| Clôture de caisse : une par (nœud, date) ; entrées = A + B (1 500), écart 0 ; seconde clôture même date -> 400 ; clôture du jour suivant acceptée | OK |
| Rapport journalier consolidé (jour D, deux équipes) : FACTURE/JR 6 pains 3 000 FC, CM 750 (25 %), NS 3 pains 1 500, RG 1 pain 500, VENTE SOLDE 2 pains 750 ; la veille vide ; API identique au calcul interne | OK |
| Reçu UI : date du jour, équipe, RCCM/Id.Nat/N° Impôt, BP avant/après, « Solde arrêté ce jour », sans débordement à 360 et 1440 px | OK |
| Boîte de désignation (lecture simulée « non désignée », aucune écriture) : « Service du … (relève de 12h00) », plus de « Journée de travail du », sans débordement à 360 et 1440 px | OK |
| Boîte « Stock de départ de la relève » (apparue en rotation) à 360 px : lisible, boutons accessibles | OK (capture `docs/qa/captures/ventes-vague4-stock-depart-releve-*.png`) |

## Tickets ouverts
- BUG-273 (Mineur, À CLARIFIER) : deux facturiers de la même équipe = deux rapports pour (équipe, date) ; la décision dit un par (équipe, date).
- BUG-274 (Mineur) : `pending_deliveries` filtre `invoice_date` = aujourd'hui : une facture en attente créée à 23:55 disparaît de l'écran livreur à minuit (livrable par id, mais non listée ; expirera à 12 h).
- BUG-275 (Mineur, À CLARIFIER) : `daily_summary` range par `invoice_date`, `bread_summary` / rapport facturier / clôture par `delivered_at` ; un même jour affiche des chiffres différents selon l'écran dès qu'une facture est livrée après minuit ou datée du passé (constaté en base réelle avec une vente datée du 11/11 livrée à 18:14 le 12/11).
Tests des trois : `@expectedFailure` avec la référence.

## Non-régression vague 2 (live K1, rotation active, puis base de test)
Plafond : BP = plafond 50 000, paiement 0 -> 403 avec message français ; paiement < commande -> 403 ; paiement = commande -> 201 ; juste sous (30 000 + 20 000 = 50 000) -> 201 (annulée ensuite, BP rétablie à 30 000). Remboursement 400 : BP 1 000 -> 600, commande 0, taux CM 0. Épargne : BP -2 000 -> -5 000 (dépôt 3 000). VENTE SOLDE (10 x 500) : 3 750 FC, CM 0, BP inchangée ; VENTE CASH soldée : 3 750 payés, CM 0. NV, RG (livrable, BP inchangée), NS (livraison refusée 400, annulation rétablit la BP), vente occasionnelle au comptant : OK. Prix forgé ignoré (1 000 = 2 x 500) ; `node=K2` ignoré (facture K1). Livraison par livreur et par facturier. Concurrence : 6 factures simultanées sur K1-0084 (3 facturiers A/B alternés), 6 numéros distincts, BP 1 000 -> 2 500 exacte. Base de test : suite vague 2 (9 tests) OK ; suites dev `test_vague1_corrections_ventes`, `test_bug161_b2_team_blocking`, `test_bug161_b3_invoice_dates` (41 tests) OK.

## Rejeux
- BUG-210 : `commission_rate` envoyé `1.00` / `-0.50` -> 400 ; `0.30` -> 201 mais taux appliqué 0,25 (taux du client) ; sans champ -> 0,25. Corrigé confirmé.
- BUG-233 : PATCH `commission_exempt` par facturier et livreur -> 403 ; PUT/DELETE refusés. Le chemin gérant (200, liste blanche) n'est pas rejouable en direct (aucun compte gérant K1 connu) : couvert par `test_vague2_db_ventes_2026_11_12::DroitsEtContratTests` (OK).

## Point ouvert « daily_summary et ventes soldées en CREDIT » (chiffres, pas de ticket)
Base réelle K1, avant/après livraison (client K1-0085, BP constante 20 200) :
- VENTE SOLDE à crédit (10 x 500, 3 750 FC dus à 75 %, 0 payé) : CASH 49 650 -> 49 650 ; CREDIT 103 050 -> 106 800 (+3 750) ; BP du client inchangée.
- VENTE CASH soldée (3 750 payés) : CASH 49 650 -> 53 400 (+3 750) ; CREDIT inchangé ; BP inchangée.
Le CREDIT de `daily_summary` inclut donc le manquant d'une vente soldée alors qu'aucune dette n'est créée (la perte est une décote, pas une créance). Règle à fixer par le coordinateur / l'auditeur comptable.

## Observations (sans ticket)
- Hors rotation et en rotation, une facture NS à crédit augmente la BP du client (20 200 -> 21 700) et la restitue à l'annulation : conforme à BUG-177/180 (« NS CREDIT = order_total - paiement »).
- Environnement : Vite très lent à froid (premier `goto` 240 s ; test relancé) ; la boîte « Stock de départ de la relève » apparaît plusieurs secondes après le chargement et masque la page : le test attend désormais son bouton « Plus tard ». Les tests Django cumulés de ce fichier prennent plusieurs minutes (machine chargée).
- Effets de bord en base réelle : ~25 factures K1 supplémentaires (ZZTEST Ventes 1 à 8, annulées ou livrées), une vente occasionnelle et une NV sans client, une facture d'épargne (K1-0083 BP -5 000). Aucun client réel touché.

## Verdict
Les règles calendaires de la décision 2026-11-12 sont respectées pour les ventes, la trésorerie (rapport facturier, clôture) et l'interface (360 et 1440 px). Trois points mineurs ouverts (BUG-273, 274, 275), aucun bloquant ni majeur. BUG-271 et BUG-272 conformes côté ventes/trésorerie ; statut `VÉRIFIÉ` laissé au coordinateur après vérification de testeur-production.
