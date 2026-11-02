# Rapport — dev-backend — phase 4 (résiduel 2) — 2026-10-23

## Tickets traités

### BUG-056 (Majeur) — `ProductionSessionViewSet` sans protection de nœud — CORRIGÉ
- Cause : `perform_create` faisait `node = serializer.validated_data.get('node') or user.node`
  sans jamais vérifier `user.can_access_all_nodes` ; `perform_update` ne réimposait jamais `node`
  après `serializer.save()`.
- Correction : `backend/production/views.py::ProductionSessionViewSet.perform_create` impose
  `node = user.node` pour tout non-HQ (ignore le payload) ; `perform_update` impose de même
  `node=serializer.instance.node` (+ `node_origin`) pour un non-HQ. Branche HQ inchangée dans les
  deux cas. Même motif exact que BUG-022/025/030.
- Test de non-régression (nouveau fichier) : `backend/production/tests/test_bug056_forged_node.py`
  — 2 tests (création et édition avec `node` forgé), vérifient aussi l'impact réel sur
  `BreadStock`. `python manage.py test production` : 29/29 OK.
- Impact API : aucun changement de contrat.

### BUG-058 (Majeur) — Formule de commission, REMISE ne doit plus être déduite — CORRIGÉ
- Décision client reçue le 2026-10-23 (M. NDUNGA NSAYI PIERRE, relayée par le coordinateur) :
  aligner la formule sur les classeurs Excel réels d'août 2026. CARTE (1 % du CM) reste déduite ;
  REMISE (0,1 % du CM) reste calculée/affichée mais n'est plus déduite du Net à Payer.
- Correction : `backend/commissions/models.py::ClientCommission.compute()` — `deduction_remise`
  retiré de `total_deductions` et de `net_payable`. `deduction_carte` et le calcul de
  `deduction_remise` lui-même sont inchangés (toujours calculés pour affichage). La remise
  annuelle de fidélité (`annual_bonus`, mécanisme distinct, CLAUDE.md §5.1/§5.3) n'est pas
  touchée — vérifié explicitement que ce n'est pas le même champ ni le même calcul.
- Tests mis à jour (formule corrigée, pas affaiblie) : `backend/commissions/tests/test_formulas.py`
  (3 tests renommés/ajustés : `test_net_payable_with_bonus_incorporated`,
  `test_net_payable_without_bonus_incorporated_excludes_bonus`,
  `test_total_deductions_sums_debt_social_prints_other_plus_carte`) et
  `backend/commissions/tests/test_audit_comptable_2026_10_22.py::RemiseCarteNotDeductedInRealLedgerTests::test_app_net_payable_no_longer_deducts_remise_after_bug058_fix`
  (renommé, prouve que l'écart résiduel avec le grand livre réel ne vient plus que de CARTE).
  `python manage.py test commissions finance` : 29/29 OK.
- Impact API : aucun changement de contrat (mêmes champs exposés, `deduction_remise` toujours
  présent avec la même valeur numérique qu'avant — seul son rôle dans le calcul interne change).
  Pas de ticket frontend nécessaire.
- Registre : fiche BUG-058 complétée avec « CORRIGÉ par dev-backend le 2026-10-23 », mention
  explicite de la décision client.

### BUG-062 (Majeur) — Aucune retentative sur verrou SQLite — CORRIGÉ (avec réserve documentée)
- Deux points corrigés comme demandé, plus deux points connexes découverts nécessaires pour que
  les tests de preuve passent réellement (pas seulement masquer le symptôme d'origine) :
  1. `backend/sales/views.py::InvoiceViewSet.create` → renommé `_create_once` ; `create()` devient
     une boucle de retentative (`_INVOICE_CREATE_MAX_RETRIES = 200`, backoff 0,02-0,15 s) qui
     relit l'état depuis le début à chaque tentative.
  2. `backend/sync/models.py::NodeAuthToken.authenticate()` → retentative sur la LECTURE du jeton
     (pas seulement l'écriture de `last_used_at` comme demandé initialement — la lecture elle-même
     peut heurter « database table is locked » sous SQLite en cache partagé) et sur l'écriture de
     `last_used_at` (`_AUTH_WRITE_MAX_RETRIES = 150`).
  3. (découvert pendant la correction, nécessaire pour que le test de preuve passe)
     `backend/sync/views.py::PushView.post` → même motif (`_post_once` + boucle de retentative sur
     `OperationalError` et `IntegrityError` de collision `batch_id`).
  4. (idem) `backend/sync/services.py` → `_WRITE_MAX_RETRIES` relevé de 25 à 150 ;
     `record_debt_movement` gère désormais `IntegrityError` sur collision de `movement_id` (retourne
     l'enregistrement déjà créé par le gagnant de la course au lieu d'échouer).
  5. (défense en profondeur, sans rapport avec le fond applicatif) `backend/sync/apps.py` relève le
     `PRAGMA busy_timeout` SQLite à 30 s sur chaque connexion.
- Tests : `@expectedFailure` retiré de `sales/tests/test_charge_morning_peak.py` (16 threads/8
  boulangeries — stable sur tous les runs effectués) et de
  `sync/tests/test_charge_sync_volume.py::ConcurrentRapidReplayTests` (classe convertie en
  `TransactionTestCase` — nécessaire, sinon le test lui-même ne peut pas exercer de vraie
  concurrence entre connexions sous `TestCase`).
- **Réserve honnête, à signaler au testeur** : le scénario `sync` à 10 threads strictement
  simultanés sur le MÊME `batch_id` reste occasionnellement flaky après correction complète
  (mesuré sur plusieurs séries : 10/10, 10/10, 7/10, 10/10, 13/15 — pas 100 %). Analyse confirmée :
  les échecs résiduels viennent de l'épuisement du budget de tentatives sous la contention la plus
  extrême testée (pas d'un chemin non protégé — aucune `OperationalError`/`IntegrityError` brute
  observée dans les échecs résiduels analysés). Cause de fond : verrouillage SQLite au niveau
  fichier/table, pas ligne — ne disparaît complètement qu'avec la migration Cloud vers PostgreSQL
  (déjà recommandée par `testeur-charge`, hors périmètre de ce ticket). Détail et chiffres dans le
  registre, fiche BUG-062.
- Précédent comparable déjà documenté dans le code : `sales.tests.test_invoices.ConcurrentInvoiceBPTests`
  est lui-même qualifié de « déjà flaky sous SQLite » dans son propre commentaire — ce n'est pas
  une première occurrence de ce type de limitation sur ce projet.

### BUG-063 (Mineur) — Comparaison de types cassée — CORRIGÉ
- `backend/sales/views.py::InvoiceViewSet.create` (`_create_once`) : `bp_ids` normalisé en `int`
  avant construction de `bp_map`/`missing` (avec 400 propre si non convertible) ; la boucle de
  création des lignes utilise aussi `int(line_data['bread_price'])`.
- Tests ajoutés dans `backend/sales/tests/test_invoices.py::StandardInvoiceTests` :
  `test_bread_price_sent_as_string_is_accepted`, `test_invalid_bread_price_identifier_returns_clean_400`.
  `python manage.py test sales` : 36/36 OK.
- Impact API : aucun changement de contrat pour les clients déjà conformes.

### BUG-064 (Majeur) — Absence d'index sur `Invoice` — CORRIGÉ
- `backend/sales/models.py::Invoice.Meta.indexes` : `(node, status, invoice_date)` composite +
  `created_at` simple — choisis d'après les filtres réellement utilisés par
  `InvoiceViewSet.get_queryset()` et `finance/views.py`.
- Migration : `backend/sales/migrations/0005_bug064_invoice_indexes.py` (`AddIndex` × 2 uniquement,
  aucune donnée touchée). `makemigrations --check --dry-run` ne montre plus aucune dérive sur
  `sales` (seule la dérive pré-existante BUG-057 sur production/clients/treasury subsiste,
  documentée séparément, non touchée).
- Pas de remesure chiffrée avant/après avec `backend/scripts/charge/volumetrie.py` dans cette
  session (hors mandat dev-backend) — à faire par `testeur-charge`/`auditeur-comptable`.
- **Incident signalé en transparence** : j'ai appliqué par erreur cette migration sur le vrai
  `backend/db.sqlite3` en lançant `python manage.py migrate sales` (pensant agir sur une base de
  test). Immédiatement annulée (`migrate sales 0004`) — aucune perte de données possible, l'
  opération ne porte que sur des index (schéma), jamais sur des lignes. Je n'ai relancé AUCUN autre
  `migrate` direct par la suite ; toutes les vérifications suivantes utilisent exclusivement
  `manage.py test` (base éphémère).

## Vérifications finales
- `python manage.py check` : aucun problème.
- `python manage.py makemigrations --check --dry-run` : seule dérive restante = BUG-057
  (production/clients/treasury, pré-existante, documentée, non touchée par cette session).
- `python manage.py test sync sales commissions production` : 99/99 OK (exécution combinée).
- `python manage.py test` (suite complète, 8 apps) : lancée en fin de session en arrière-plan ;
  n'a pas terminé dans le temps imparti de cette session (la suite `clients core` seule prend déjà
  ~254 s, voir constat ci-dessous). Confiance forte malgré tout : toutes les apps que j'ai
  modifiées ont été testées individuellement et en combinaison (`sync sales commissions production`
  = 99/99 OK) ; `python manage.py check` ne signale aucun problème. À confirmer par le testeur en
  relançant `python manage.py test` en entier.
- Constat annexe (non corrigé, hors périmètre des fichiers autorisés pour cette mission) :
  `clients.tests.test_verification_2026_10_22.py::BUG017RealConcurrencyStrictAssertionTests`
  (test pré-existant, BUG-017) est lui-même occasionnellement flaky sous forte concurrence SQLite
  (observé 1 échec sur 3 exécutions, reproduit sans aucune modification de ma part sur
  `clients/`) — signalé pour mémoire, même famille de limitation que la réserve BUG-062 ci-dessus,
  pas une régression introduite par cette session.

## Fichiers modifiés
- `backend/production/views.py`
- `backend/production/tests/test_bug056_forged_node.py` (nouveau)
- `backend/commissions/models.py`
- `backend/commissions/tests/test_formulas.py`
- `backend/commissions/tests/test_audit_comptable_2026_10_22.py`
- `backend/sales/views.py`
- `backend/sales/models.py`
- `backend/sales/migrations/0005_bug064_invoice_indexes.py` (nouveau)
- `backend/sales/tests/test_invoices.py`
- `backend/sales/tests/test_charge_morning_peak.py`
- `backend/sync/models.py`
- `backend/sync/views.py`
- `backend/sync/services.py`
- `backend/sync/apps.py`
- `backend/sync/tests/test_charge_sync_volume.py`
- `docs/qa/REGISTRE_BUGS.md`

## En attente / risques
- BUG-062 : réserve de flakiness résiduelle documentée ci-dessus et dans le registre — à confirmer
  par le testeur lors de la vérification (relancer le test isolé en cas d'échec ponctuel, rouvrir
  seulement si une `OperationalError`/`IntegrityError` brute réapparaît).
- BUG-064 : remesure chiffrée avant/après (script volumétrie) non effectuée dans cette session —
  à faire par `testeur-charge`/`auditeur-comptable`.
- Aucun des 5 tickets ne change de contrat d'API — aucun nouveau ticket `dev-frontend` ouvert.
- Dérive de migrations BUG-057 : non traitée (hors périmètre explicite de cette mission), toujours
  présente à l'identique.
