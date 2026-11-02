# Rapport dev-backend — correction BUG-062 (réouverture testeur-charge) — 2026-10-23

## Mission

Corriger le résidu confirmé par `testeur-charge` sur BUG-062 (réouvert) : un échec transitoire de
verrou SQLite, après épuisement des 150 retentatives internes de
`backend/sync/services.py::record_debt_movement`, était capturé par
`backend/sync/services.py::process_push_batch` (`except Exception` générique) et archivé **pour
toujours** dans `SyncBatchLog` (`status=PARTIAL`, résultat `REJECTED`). Un rejeu ultérieur du même
`batch_id` (cas d'usage réel : reprise après coupure réseau) retrouvait ce log et renvoyait le même
résultat figé — sans jamais recréer le `DebtMovement` manquant. Décision ADG (M. NDUNGA NSAYI
PIERRE) : un échec transitoire ne doit JAMAIS être archivé comme un résultat terminal.

## Cause racine

- `sync/services.py::process_push_batch` : `except Exception as exc:` traitait indifféremment un
  rejet métier (données invalides) et une `OperationalError` transitoire (verrou SQLite épuisé),
  convertissant les deux en un résultat `_record_result(..., False, reason)` — persisté ensuite par
  `sync/views.py::PushView._post_once` dans un `SyncBatchLog` idempotent et définitif.
- `sync/models.py::NodeAuthToken.authenticate()` : l'épuisement du budget de lecture du jeton
  renvoyait simplement `None`, indistinguable d'un jeton réellement invalide/révoqué → 401 — exactement
  le `401` sporadique signalé par testeur-charge sous charge combinée (confirmé : même log
  `"échec de la lecture du jeton après 150 tentatives"` dans sa trace).

## Correctif

1. `backend/sync/exceptions.py` (nouveau) : `TransientSyncError`, `APIException` DRF, HTTP 503,
   dédiée aux échecs transitoires d'infrastructure.
2. `backend/sync/services.py::process_push_batch` : `except OperationalError: raise` AVANT le
   `except Exception` générique — ne convertit plus jamais un verrou SQLite épuisé en résultat
   `REJECTED` archivable. L'exception traverse `_post_once` jusqu'à la boucle de retentative déjà
   existante de `PushView.post`.
3. `backend/sync/views.py::PushView.post` : si les 150 tentatives sont malgré tout épuisées, lève
   `TransientSyncError` (503) au lieu d'un `raise last_exc` brut (500) — et surtout, **aucun
   `SyncBatchLog` n'est jamais créé** avant ce point : le lot reste intégralement rejouable.
4. `backend/sync/models.py::NodeAuthToken.authenticate()` : épuisement du budget de LECTURE du
   jeton → lève désormais `TransientSyncError` (503) au lieu de renvoyer `None` (401 trompeur).
   L'épuisement du budget d'écriture de `last_used_at` (purement informatif) reste inchangé.

Idempotence préservée par construction : chaque gestionnaire de `PUSH_HANDLERS`
(`_push_client`/`_push_invoice`/`_push_invoice_line`/`_push_debt_movement`/`_push_cash_closure`)
est déjà un no-op sûr sur un enregistrement déjà créé — un rejeu complet du lot après un 503 ne
peut donc jamais double-compter les enregistrements déjà traités avec succès dans une tentative
précédente ; il ne fait que retraiter réellement celui resté en échec.

## Fichiers modifiés

- `backend/sync/exceptions.py` (nouveau)
- `backend/sync/services.py` (`process_push_batch`)
- `backend/sync/views.py` (`PushView.post`)
- `backend/sync/models.py` (`NodeAuthToken.authenticate`)
- `backend/sync/tests/test_charge_sync_volume.py` : nouvelle classe
  `TransientFailureNeverArchivedPermanentlyTests` (2 tests déterministes, reproduisent exactement le
  bug via mock de `DebtMovement.objects.create`) ; adaptation de l'assertion finale de
  `ConcurrentRapidReplayTests::test_replaying_the_same_batch_id_concurrently_many_times_never_duplicates`
  pour tolérer un 503 propre en plus de 200, avec vérification renforcée de l'invariant (aucune perte
  silencieuse, aucun archivage `SyncBatchLog` incohérent).
- `docs/qa/REGISTRE_BUGS.md` : BUG-062 passé à `CORRIGÉ` (fiche détaillée ajoutée) ; nouveau ticket
  `BUG-067` ouvert pour `architecte-sync` (traiter le 503 côté futur client desktop).

## Tests

- `python manage.py test sync sales` : **63/63 OK**.
- Nouveaux tests ciblés (`TransientFailureNeverArchivedPermanentlyTests`) : échouaient avant la
  correction (1ʳᵉ requête 200/REJECTED archivé, 2ᵉ requête `replayed=True` avec le même REJECTED,
  `DebtMovement` jamais créé) — passent après.
- Scénario de charge le plus agressif (`ConcurrentRapidReplayTests::test_replaying_the_same_batch_id_concurrently_many_times_never_duplicates`,
  10 rejeux réellement concurrents du même `batch_id`) : **relancé isolément 30 fois d'affilée →
  30/30 vertes**, contre ≈ 8 % d'échecs mesuré par testeur-charge avant correction (76 exécutions,
  6 échecs). Nature du risque résiduel changée : même en cas d'échec sous cette contention extrême
  (non observé sur ces 30 runs), il se traduirait désormais par un 503 propre sans `SyncBatchLog`
  persisté — jamais par une perte silencieuse et permanente.
- `python manage.py test` (suite complète, 245 tests) : **3 échecs**, tous **pré-existants et sans
  rapport avec cette correction** — confirmés en échouant à l'identique en isolation (sans
  combinaison avec d'autres apps, donc pas un artefact de contention introduit par mes
  changements) :
  - `treasury.tests.test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario`
  - `treasury.tests.test_reports_closures.CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses`
  - `clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests.test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db`
  Ces trois tests ne touchent aucun fichier que j'ai modifié (`treasury`, `clients`, pas `sync`) et
  échouent déjà seuls, hors de toute suite combinée. Hypothèse pour les deux premiers (non
  investiguée, hors mandat) : dates calendaires codées en dur dans les tests
  (`treasury/tests/test_reports_closures.py`, ex. `'2026-10-22'`/`'2026-10-23'`) potentiellement en
  décalage avec une validation de date courante introduite ailleurs. Le troisième ressemble à un
  résidu non corrigé du même type de défaut que BUG-062 mais sur `clients_clientcodesequence`
  (hors périmètre de ce ticket, module différent). **Signalé au coordinateur — pas corrigé ici,
  hors mandat strict de ce ticket (BUG-062/sync uniquement).**
- `python manage.py makemigrations --check --dry-run` : aucune dérive nouvelle ; seule la dérive
  pré-existante documentée sous BUG-057 (`production`/`clients`/`treasury`) subsiste, non touchée
  (aucun changement de schéma dans cette correction — uniquement du code applicatif Python).

## Impact API (contrat changé — ticket lié ouvert)

- `POST /api/sync/push/` peut désormais renvoyer `503 {"detail": "..."}` dans le cas précis d'un
  échec transitoire d'infrastructure (au lieu d'un 200/PARTIAL archivé à tort, ou d'un 500 brut).
  Le nœud appelant doit rejouer le MÊME `batch_id` plus tard.
- L'authentification de nœud (`/api/sync/*`) peut renvoyer `503` au lieu de `401` dans le cas précis
  d'un épuisement de budget de lecture du jeton (transitoire) — un jeton réellement invalide/révoqué
  continue de renvoyer `401` normalement.
- **Ticket `BUG-067` ouvert pour `architecte-sync`** (module client desktop pas encore implémenté
  dans ce dépôt) : traiter explicitement ce 503 comme « réessayer plus tard », distinct d'un rejet
  définitif.

## Statut du ticket

BUG-062 passé à `CORRIGÉ` dans `docs/qa/REGISTRE_BUGS.md` (fiche détaillée sous la section de
réouverture). Je ne le passe pas à `VÉRIFIÉ` (CLAUDE.md §7 règle 3) — c'est `testeur-charge` qui
revérifiera, idéalement en relançant son propre scénario de charge agressif (10 rejeux concurrents,
répété plusieurs dizaines de fois) pour confirmer indépendamment l'absence de perte de données.

## Risques / points d'attention pour la relecture

1. La cause de fond (verrouillage SQLite au niveau fichier, pas ligne) **n'est pas éliminée** — seule
   la migration PostgreSQL déjà recommandée par `testeur-charge` l'élimine par construction. Ce
   correctif élimine uniquement la **conséquence la plus grave** (perte silencieuse et permanente
   d'une dette client) ; un échec résiduel sous contention extrême reste possible en théorie, mais se
   traduit désormais toujours par un 503 propre et un lot rejouable, jamais par une perte de données.
2. BUG-067 (nouveau, lié) attend `architecte-sync` pour que le futur client desktop gère ce 503
   correctement.
3. Les 3 échecs pré-existants (`treasury`/`clients`) signalés ci-dessus méritent un ticket dédié —
   je ne l'ai pas ouvert moi-même pour rester strictement dans le périmètre de cette mission
   (BUG-062/sync), mais je le signale explicitement pour que le coordinateur l'assigne.
