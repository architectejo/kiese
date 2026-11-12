# Rapport dev-backend — 2026-11-12

## BUG-161 étape B3 (rotation 24 h : date de travail serveur) et BUG-189 (verrou de vacation, date UTC)

Statut : BUG-161 reste OUVERT (B4 à B6, F3 à venir) ; BUG-189 passe à CORRIGÉ (à vérifier par testeur-trésorerie).
Aucune commande git, aucune migration, aucun accès à `backend/db.sqlite3`, aucun fichier `frontend/` touché.

### Principe

`core/workday.py::work_date_for(node, instant=None)` est la source unique de la « date de travail » :
`business_date(node, instant)` si `node.team_rotation_enabled`, sinon la date LOCALE du calendrier
(`Africa/Kinshasa`), exactement comme `timezone.localdate()` aujourd'hui. `node=None` : date locale.
Deux aides additives : `work_time_info(node)` (`{work_date, server_now}`) et
`delivered_on_work_date_filter(node, work_date)` (lookups ORM d'appartenance d'un `delivered_at` à une journée).

### Cause de BUG-189

`treasury/signals.py` calculait `instance.delivered_at.date()`. `timezone.now()` renvoie un datetime UTC : `.date()`
donne la date UTC, alors que le `FacturierReport` est daté en local. Entre 00:00 et 01:00 à Kinshasa (UTC+1) le rapport
n'était pas retrouvé (verrou inopérant) et, avec `allow_backdated_sales`, une re-livraison du jour même était prise pour
rétroactive. Même famille de défaut corrigée partout où l'on utilisait `date.today()` (date du système, pas du projet).

### Fichiers modifiés

- `backend/core/workday.py` : `work_date_for`, `work_time_info`, `delivered_on_work_date_filter`.
- `backend/core/utils.py` : `validate_requested_date(..., node=None)` plafonne à `work_date_for(node)` (« date future » = après
  la journée de travail courante).
- `backend/treasury/signals.py` : date de livraison = `work_date_for(node, delivered_at)` ; `is_backdated` comparé à `work_date_for(node)`.
- `backend/treasury/services.py` : `regenerate_facturier_reports` filtre par `delivered_on_work_date_filter` (date locale hors
  rotation, bornes de relève en rotation) au lieu de `delivered_at__date`.
- `backend/treasury/views.py` : `generate` (nœud résolu avant la date, défaut = journée de travail, validation avec le nœud),
  `CashClosure.perform_create/perform_update`, `JournalEntry.perform_create` (défaut = journée de travail du nœud),
  `period_summary`, `DirectionCashCount` (`timezone.localdate()`), `monthly_report`/`monthly_total` (mois/année par défaut via
  la date de travail de l'utilisateur) : plus aucun `date.today()`.
- `backend/sales/views.py` : `_create_once` (`invoice_date` = `work_date_for(node)`, validation avec le nœud,
  `is_backdated = invoice_date < work_date_for(node)`, déficit du mois sur la journée de travail), `deliver` et `adjust`
  (date de travail et validation du nœud), `_combine_date_with_now_time(target_date, node=None)` (en rotation, l'horodatage
  reconstruit reste DANS la journée de travail visée), `_make_receipt_number(code, receipt_date)` (plus de `date.today()`),
  valeurs par défaut de `pending_deliveries`, `daily_summary`, `bread_summary` (`_default_work_date(user)`).
- `backend/production/views.py` : `ProductionSessionViewSet.create` (+ `_with_workday_defaults`) : en rotation, `date` et
  `team` absents du payload sont complétés par la journée de travail et l'équipe de service ; `BreadStockByDateView`
  (bascule live/snapshot sur `work_date_for`) ; `DailyOpeningConfirmationView` GET/POST (date par défaut = journée de travail ;
  en rotation POST refuse toute `date` différente de la journée de travail courante, 400, sans aucune écriture) ;
  `_build_daily_closure_report(node, report_date=None)` (défaut = journée de travail) ; `work_date`/`server_now` ajoutés.
- `backend/clients/views.py`, `backend/blockchain/views.py`, `backend/finance/views.py` : `date.today()` remplacé par
  `timezone.localdate()` (dépendance au fuseau du système, même défaut latent).

### Points vérifiés et non modifiés

- `_build_reconciliation_querysets` n'a pas de date par défaut (sans `date`, `date_from`, `date_to` : tout l'historique) ; aucune
  date « du jour » à rebaser, l'action `close` passe toujours `session.date`. Laissé tel quel pour ne pas changer le comportement.
- `shift_end_status` : la détection de fin de créneau (`today = localtime().date()`, créneaux A/B) reste celle d'avant (étape B5).
- `TeamAssignmentView` utilisait déjà `business_date` (inchangée).
- `treasury/services.py` `record_backdated_correction` et la note de réouverture utilisent `timezone.localdate()` : c'est le jour
  RÉEL de la saisie au livre de caisse (chaîne de hash), volontairement indépendant de la journée de travail.

### Contrat API (pour dev-frontend, additif)

- `GET /api/production/opening-confirmation/` et réponse de `POST` : `work_date` ("AAAA-MM-JJ") et `server_now` (ISO 8601 local).
- `GET /api/production/bread-stocks/by-date/` : `work_date` et `server_now`.
- `GET /api/production/daily-closure/` : `work_date` (journée de travail COURANTE du nœud, distincte de `date` = date demandée) et `server_now`.
- `GET /api/production/sessions/shift-end-status/` : `work_date` et `server_now` ajoutés **uniquement quand `Node.team_rotation_enabled`
  est vrai** (hors rotation, le corps reste strictement `{"pending_validation": ...}` : des tests existants comparent le corps exact).
  Hors rotation, le frontend garde donc son calcul actuel ; à terme il peut lire `work_date` de `opening-confirmation`/`by-date`.
- `POST /api/production/opening-confirmation/` : en rotation, `date` différente de la journée de travail courante -> 400
  `{"detail": "En rotation d'équipes, le stock de départ ne peut être confirmé que pour la journée de travail courante (AAAA-MM-JJ)."}`.
- `POST /api/production/sessions/` : en rotation, `date` et `team` deviennent facultatifs (valeurs serveur) ; hors rotation, toujours obligatoires.
- Les factures portent `invoice_date` = journée de travail (en rotation : la veille entre minuit et la relève). Aucun champ modifié.

### Tests (nouveaux fichiers, aucun test existant modifié)

- `backend/core/tests/test_bug161_b3_workday_dates.py` : `work_date_for` (00:30 locale = 23:30 UTC, relève 11:59/12:00, relève 00:00 =
  équivalence, nœud `None`), `work_time_info`, filtre de livraison, `validate_requested_date` avec nœud.
- `backend/treasury/tests/test_bug189_vacation_lock_local_date.py` : verrou à 00:30, midi, 23:30 locale (horloge simulée en UTC comme le
  vrai `timezone.now()`), non-rétroactivité du jour même avec `allow_backdated_sales`, rotation (03:00 / 13:00), regroupement des rapports.
  Vérifié : les tests de 00:30 ÉCHOUENT avec l'ancien code (`delivered_at.date()`) et passent avec le correctif ; ceux de midi passent dans les deux cas.
- `backend/sales/tests/test_bug161_b3_invoice_dates.py` : équivalence hors rotation (00:30, midi, futur/passé, `pending_deliveries`,
  `daily_summary`) ; rotation : vente à 03:00 = veille, 11:59 = veille, 12:00 = jour, date future, jour courant non rétroactif, rétroactif
  à J-2, `delivered_at` reconstruit dans la bonne journée, `adjust`.
- `backend/production/tests/test_bug161_b3_production_dates.py` : session (défauts serveur, payload explicite, équipe non désignée,
  hors rotation toujours obligatoires), stock par date (live/snapshot/futur), confirmation du stock de départ (défaut, rejet du passé et
  du futur en rotation, passé accepté hors rotation, snapshot et session de la veille intacts), rapport de clôture et `shift-end-status`.

### Résultats

Voir la section « Exécution » ci-dessous.

### Exécution

- Un seul processus, 353 tests ciblés (4 nouveaux fichiers + suites listées + suites voisines des zones modifiées : treasury bug083/086, sales bug083/bug177/verif ventes, production bug144/155/158/162/185-187, vérifications testeur-production) : OK (1 échec attendu préexistant), 1082 s.
- `makemigrations --check --dry-run` : « No changes detected » (aucune migration créée ni à appliquer).
- La suite complète est laissée au coordinateur.

### Risques et réserves

- Les 4 tests de trésorerie cités dépendent de l'heure réelle : confirmer par une exécution entre 00:00 et 01:00 (le nouveau fichier de test simule l'heure et couvre le cas).
- `shift-end-status` n'expose `work_date`/`server_now` qu'en rotation (contrainte de non-régression des tests à comparaison exacte) ; si le frontend veut la valeur dans tous les cas, utiliser `opening-confirmation`/`by-date`, ou autoriser la modification de ces tests.
- En rotation, `delivered_at` des ventes rétroactives est reconstruit dans la journée de travail visée (peut tomber le lendemain calendaire) : comportement voulu, à connaître pour les exports par date calendaire (`bread_summary` filtre toujours par date de livraison calendaire sur une `date` explicite).
- Aucun test de charge/concurrence sur les nouvelles branches ; les accès aux soldes (`select_for_update`/`F()`) n'ont pas été touchés.

## BUG-161 étapes B4 et B5 (stock de départ aux heures de rotation ; clôture à la relève)

Statut : BUG-161 reste OUVERT (étapes frontend, B6). Aucune migration, aucune commande git, aucun accès à `db.sqlite3`, `frontend/` non touché.

### B4
- `DailyOpeningConfirmationView` en rotation : une confirmation par journée de travail (toutes équipes), équipe = équipe désignée, `team_assignment_required` si aucune désignation, plus de choix d'équipe ; POST : équipe désignée (403 `TEAM_NOT_ASSIGNED` sans désignation, 400 si `team` différent).
- Chaînage : `qty_proposed` et `reste_du_hier` du rapport viennent du dernier snapshot du nœud toutes équipes (`DailyBreadStockSnapshot.last_snapshot_before`, `reste_du_hier_chained`, lecture seule), porté par l'équipe de service du jour. Hors rotation : `reste_du_hier` par équipe inchangé (risque BUG-120 : tests daily_closure_report / daily_stock_snapshot / BUG-120 verts).
- Garde (e) prouvée par test : snapshot, rapport et session de J intacts après confirmation puis modification du départ J+1.
- Nouveau helper `core/workday.py::team_for_work_date(node, work_date)`.

### B5
- `shift_end_status` en rotation : branche `_handover_shift_end_response` (journée de travail précédente, équipe désignée, relève = fin de journée, grâce 30 min, ordre chronologique, une session par appel). Clôture forcée factorisée dans `_force_close_session` (BUG-158/165 inchangés), utilisée aussi par la branche hors rotation.

### Contrat API (dev-frontend)
- `opening-confirmation` GET (rotation) : `+ rotation, team, team_assignment_required` ; `opening_team` = équipe désignée ; POST sans `team` accepté ; 403 `TEAM_NOT_ASSIGNED` ; 400 si `team` != désignée.
- `shift-end-status` (rotation) : `work_date` = journée concernée (à clôturer, ou courante si rien), `current_work_date`, `server_now` ; clés historiques `pending_validation`, `team`, `session`, `remaining`, `auto_closed` inchangées.

### Test existant modifié
`test_bug161_b3_production_dates.py` : 2 tests de POST d'ouverture en rotation reçoivent une désignation préalable (B3 laissait confirmer sans équipe désignée ; défaut corrigé par B4).

### Réserves
- Reste forcé = stock physique courant (inexact pour une journée très ancienne restée ouverte).
- Si le frontend ne désigne pas l'équipe avant la boîte de départ, le POST est refusé (403) : la désignation reste prioritaire côté UI (déjà le cas, F2).

## BUG-190, 191, 192, 193, 194, 196 (backend), 197

Statut : CORRIGÉ (à vérifier). Aucune migration, aucune commande git, `db.sqlite3` et `frontend/` non touchés, `treasury/` et `core/` non modifiés. `makemigrations --check --dry-run` : No changes detected.

- Fichiers : `backend/production/views.py` (sessions `create`/`_with_workday_defaults`, `_handover_shift_end_response`, `_close_leftover_session`, `_close_production_session(record_snapshot)`, rapport de clôture, `DailyOpeningConfirmationView.post`, `TeamAssignmentView.post`, `_body_not_object_response`), `backend/sales/views.py` (`_make_receipt_number`).
- Tests : `production/tests/test_bug190_196.py`, `sales/tests/test_bug197_receipt_unique.py` ; `@expectedFailure` retirés (BUG-190 à 194 et 197, ils passent réellement).
- Suites voisines lancées en un processus (230 tests : mes fichiers, b4, b5, b3 production, b2, bug155, daily_closure_report, vérifs testeur production, bug185/186/187, test_invoices, b3 invoice dates, vérif ventes B3, b2 team blocking) : tout vert après ajustement de `test_bug161_b3_production_dates` (relancé séparément, 21 OK).
- Tests existants modifiés (à signaler au coordinateur) : (1) `test_bug161_b3_production_dates::test_rotation_without_assignment_team_stays_required` (400 -> 403 `TEAM_NOT_ASSIGNED`, exigé par BUG-192) ; (2) deux caractérisations de `test_verif_bug161_b3_b5_testeur_production.py::StaleRestCharacterizationTests` rendues fausses par BUG-196 (désignation posée en base ; refus 400 `PREVIOUS_WORKDAY_OPEN` attendu).
- Risques : (a) la clôture silencieuse d'une session « restante » peut émettre une seconde notification d'anomalie (recoupement par date) ; (b) BUG-196 : un nœud dont une vieille session reste ouverte ne peut plus désigner d'équipe avant la clôture (auto 30 min via `shift-end-status`, déclenché par le polling du frontend ; sans connexion d'un utilisateur du nœud, rien ne clôture) ; (c) l'unicité des reçus repose sur le verrou d'écriture SQLite en environnement actuel (pas de contrainte en base : une contrainte unique exigerait une migration de données sur les doublons hérités, à proposer en ticket si souhaité) ; (d) la suite complète n'a pas été lancée (réservée au coordinateur).

## BUG-208 à 215 (ventes, vague 1 base réelle)

Statut : CORRIGÉ (à vérifier par testeur-ventes). Aucune migration, aucune commande git, `db.sqlite3`/`frontend/`/`treasury`/`production` non touchés.

- Fichiers : `backend/sales/serializers.py`, `backend/sales/views.py`, `backend/sales/tests/test_vague1_corrections_ventes.py` (nouveau).
- 208 : lignes validées (`bread_price` entier >= 1, `quantity` entier 1..100000) ; 400 avec `detail`. 209 : `payment_amount >= 0`. 213 : remboursement <= 0 refusé. 214 : sans client (hors NS/RG), CREDIT ou versement < commande -> 400.
- 210 (choix retenu, option la plus sûre §5.3) : taux appliqué = `client.commission_rate` (défaut Config) ; un `commission_rate` envoyé est validé dans {0 ; 0,25 ; 0,30} (sinon 400) mais ignoré.
- 211 : `bread_summary` utilise `delivered_on_work_date_filter` par nœud. 212 : non-HQ -> son nœud, `?node=` autre -> 403 ; HQ peut cibler/voir tout.
- 215 : `InvoiceViewSet` = Create+List+Retrieve+GenericViewSet ; PUT/PATCH/DELETE -> 405.
- Contrat API pour dev-frontend : (1) erreurs de validation de création : `detail` ajouté ; (2) `commission_rate` de la requête ignoré ; (3) nouveau 400 vente sans client à crédit/sous-payée ; (4) plus de PATCH/DELETE sur une facture ; (5) `bread_summary` : 403 si `node` étranger, 400 si date invalide.
- Les `@expectedFailure` de `test_vague1_db_ventes_2026_11_12.py` passent en « succès inattendu » : à retirer par testeur-ventes.

## BUG-200 à 207 (trésorerie, vague 1 base réelle) — dev-backend

Statut : tous CORRIGÉ (à vérifier par testeur-tresorerie). Tests : `backend/treasury/tests/test_vague1_corrections_treso.py` (nouveaux) ; les 17 `@expectedFailure` du fichier `test_vague1_db_testeur_tresorerie.py` ont été retirés (toutes les sondes passent). Suite `treasury` + `core.tests.test_bug149_reset_superuser` : 198 tests OK (1 échec attendu préexistant, `test_bug178_verification_2026_11_11.py:246`, non lié). `makemigrations --check --dry-run` : aucune migration. Aucune migration créée, aucune base touchée.

Fichiers : `treasury/views.py`, `treasury/serializers.py`, `treasury/services.py`.

- 200 : `CashClosureViewSet.get_permissions` renvoie `IsHeadquarters` pour validate/reject/push_to_cashbook ; le gérant garde create/update/destroy.
- 201 : bornes 0..100000 billets par coupure (clôture, bordereau, comptage direction), message 400 en français ; calcul de la clôture dans le même `atomic` que l'insertion. Lecture robuste : une clôture dont les montants dépassent la plage du DecimalField est exclue de list/retrieve, ses colonnes sont différées pour `destroy`, `suggested_ca` et le journal CA (la suppression par API redevient possible). La ligne réelle corrompue (K3, 2026-11-10) peut donc être supprimée par `DELETE /api/treasury/closures/<id>/` par le gérant K3 (non fait : interdit de toucher à la base).
- 202 : journal en ajout seul (PUT/PATCH/DELETE -> 405, choix le plus sûr car `running_balance` n'est calculé qu'à la création) ; création réservée gérant+ ; montants >= 0.
- 203 : totaux, `is_validated`, `validated_by` en lecture seule ; rapport validé : PATCH 400, DELETE 403. Non modifié : `generate` sur un rapport validé réécrit toujours les totaux (nécessaire au mécanisme de correction rétroactive BUG-083) sans lever `is_validated` — à trancher métier si besoin.
- 204 : nouveau format `CORR-<nœud>-<AAAAMMJJ clôture>-<rang 01..>` (19 car. pour K3) ; anciens numéros inchangés ; hash non modifié.
- 205 : `amount` > 0 obligatoire.
- 206 : `?node=` ignoré hors siège (liste/modif/suppression/`monthly_total`) ; revenu >= 0, taux 0..1, sacs >= 0 ; écriture réservée gérant+ (LIVREUR/FACTURIER : 403 ; lecture inchangée).
- 207 : `period_summary` renvoie des chaînes décimales à 2 décimales (`"18400.50"`), tri par code nœud.

Contrat API pour dev-frontend : (1) `period_summary` : `total_entries`/`total_exits` passent de nombre à chaîne (parser avec Number/Decimal) ; (2) journal de caisse : plus de PUT/PATCH/DELETE (405), POST réservé gérant+ ; (3) épargne : POST/PATCH/DELETE réservés gérant+ ; `?node=` sans effet pour un non-siège ; (4) rapports facturier : POST/PATCH ignorent les totaux (utiliser `generate`), PATCH refusé (400) si validé ; (5) clôture : champs `bills_*` bornés à 100000, 400 `{bills_x: [...]}` ; validate/reject/push_to_cashbook -> 403 pour un gérant (masquer ces boutons pour GERANT) ; (6) dépense : `amount` > 0.

Risque : une clôture corrompue en base reste invisible en liste jusqu'à suppression par l'API.

## BUG-217 à 227 (production, vague 1 base réelle) — dev-backend, 2026-11-12

Périmètre : `backend/production/` uniquement. Aucune migration (schéma inchangé ; `makemigrations --check` : aucun changement). Tests : `production/tests/test_vague1_corrections_production.py` (nouveaux) ; sondes du testeur `test_vague1_db_production_2026_11_12.py` : tous les `@expectedFailure` retirés (toutes passent).

- 217 : message de stock négatif lisible (quantité disponible lue sous verrou avant la sortie).
- 218 : `theoretical_yield` en `Decimal`, arrondi au franc (demi supérieur).
- 219 : `consumables_used` validé avant écriture (400 `{detail}`) ; `perform_create` atomique ; type de consommable inconnu -> 400 ; quantités <= 0 toujours ignorées.
- 220 : PATCH `flour_sacks_used` -> mouvement EXIT de farine du delta (négatif accepté, décision BUG-216), non lié à la session (ne fausse pas la surconsommation), journalisé. `consumables_used` toujours ignoré en PATCH.
- 221 : PATCH/DELETE d'une disposition régularisent `qty_disposed` (REMAINING n'a jamais d'effet), transaction + `log_activity`.
- 222 : mouvement de consommable : PATCH applique le delta, DELETE inverse l'effet (modèle, atomique, verrou). Limite : le CUMP n'est pas recalculé sur modification d'une ENTRY.
- 223 : choix métier retenu = somme de groupe nulle (§5.4). Nouvelle action `resolve_dispute` (siège/direction ou gérant émetteur ; `ALIGN_ON_RECEIVED` ou `ALIGN_ON_SENT` ; motif obligatoire ; journal + notification INFO aux deux boulangeries ; statut -> CONFIRMED, ce qui lève le blocage de clôture car les lignes ne présentent plus d'écart). Recomptage par le récepteur autorisé depuis DISPUTED (delta de stock). Transfert RESPONDED/CONFIRMED/DISPUTED : DELETE/PATCH refusés (400). Pas d'option « perte » (à valider avec le client si besoin).
- 224 : validations (siège sans nœud, auto-transfert, lignes vides/invalides, quantités entières strictes, doublons cumulés), création atomique, relecture sous verrou aux étapes répondre/confirmer.
- 225 : dates impossibles -> 400 sur les 4 routes (+ POST opening-confirmation, + `date_from`/`date_to` de reconciliation).
- 226 : `shift_end_status` classique traite aussi les sessions ouvertes des jours antérieurs (grâce 30 min puis clôture forcée), comportement du jour courant inchangé.
- 227 : `team-assignment` hors rotation = date calendaire (GET/POST) ; le POST reste accepté (rétro-compat) ; en rotation inchangé.

Tests existants modifiés (pas affaiblis) : 4 tests qui vérifiaient la journée de relève avant 12:00 sans activer la rotation activent maintenant `team_rotation_enabled` (`test_bug161_b2_team_assignment.py` x2, `test_verif_bug161_testeur_production.py` x2) ; BUG-216 : 3 sondes inversées.

Contrat API pour dev-frontend : (1) NOUVEAU `POST /api/production/transfers/<id>/resolve_dispute/` `{resolution: "ALIGN_ON_RECEIVED"|"ALIGN_ON_SENT", reason}` (gérant émetteur ou siège) — bouton « Résoudre le litige » à prévoir sur un transfert `DISPUTED` ; `confirm_reception` accepte aussi `DISPUTED` (recomptage) ; (2) `POST transfers/` : 400 explicite si lignes vides, quantité non entière, catégorie inconnue, auto-demande, compte siège ; DELETE/PATCH d'un transfert engagé -> 400 ; (3) `POST sessions/` : 400 si `consumables_used` invalide ou type inconnu ; (4) dates impossibles -> 400 `{detail}` ; (5) `team-assignment` : `work_date` = date calendaire hors rotation.

Exécutés en un processus : 311 tests production ciblés (suites voisines listées par le coordinateur + autres suites production) puis re-run des 2 fichiers modifiés (41 tests) : OK. Suite complète non lancée (consigne).

Risques : (a) `ConsumableMovement.save/delete` sur un mouvement existant a changé de sémantique (delta) — aucun appelant interne connu hors API/sync ; (b) `perform_create` de fournée désormais entièrement atomique : une panne tardive annule aussi les notifications ; (c) fournées de la veille non closes en mode classique seront clôturées automatiquement au prochain appel de `shift-end-status` (voulu, BUG-226).

## BUG-233 (régression BUG-215 sur BUG-052) + nettoyage `@expectedFailure` ventes — dev-backend, 2026-11-12

Périmètre : `backend/sales/` et tests. Aucune migration (`makemigrations --check` : aucun changement).

- (A) `InvoiceViewSet.partial_update` : PATCH rouvert pour `commission_exempt` seul (liste blanche stricte, 400 français pour tout autre champ), `IsGerant` (gérant+), PUT/DELETE 405. Recalcul du `commission_rate` (0 si exonérée ; sinon taux du client, 0 pour soldée/sans client/NS/RG/remboursement). BP/stock/totaux intacts. Transaction, verrou, `log_activity`. Tests : `sales/tests/test_commission_exempt_patch.py` (10).
- (B) `test_vague1_db_ventes_2026_11_12.py` : `@expectedFailure` retiré sur les 11 tests listés (logique inchangée) ; il n'en restait qu'UN autre (BUG-212, `test_bread_summary_ne_fuite_pas_vers_une_autre_boulangerie`), adapté pour attendre le 403 (sans `grand_total_qty`) puis décorateur retiré (le fichier n'a donc plus aucun `@expectedFailure` ni l'import). `test_patch_facture_livree_refuse` patche `payment_amount` (pas `commission_exempt`) : adapté pour accepter 400/403/405 (le refus est maintenant un 400 de liste blanche).
- Test existant adapté : `test_vague1_corrections_ventes.py::ModificationDirecteTests::test_put_patch_delete_interdits` attendait 405 pour un PATCH de paiement ; attend maintenant 400 (+ statut CANCELLED 400, paiement inchangé), PUT/DELETE toujours 405.
- Exécuté en un processus : `core.tests.test_permissions`, `test_commission_exempt_patch`, `test_vague1_db_ventes_2026_11_12`, `test_vague1_corrections_ventes`, `test_invoices`, `test_bug097_invoice_adjustment`, `test_bug177_ns_rg` : 157 tests, seul échec = le test adapté ci-dessus, puis re-run (14 tests) OK.
- Risques : les commissions déjà générées ne suivent pas un PATCH tardif (régénération manuelle de la période). Frontend : aucun changement requis.
