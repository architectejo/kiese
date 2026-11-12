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
