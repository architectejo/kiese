# Rapport — architecte-sync — 2026-10-22 (implémentation V1, BUG-004)

## Contexte

Suite du rapport de conception (`docs/qa/rapports/architecte-sync-2026-10-22-conception.md`). Le
coordinateur a transmis les décisions du client (M. NDUNGA NSAYI PIERRE) sur les trois points
d'arbitrage les plus importants :

- **H1** (clôture de caisse hors-ligne provisoire jusqu'à synchronisation) : accepté tel que proposé.
- **H2** (plafond de crédit local pendant coupure prolongée) : plafond effectif réduit à **80 %** du
  plafond nominal en mode dégradé, en plus de la notification a posteriori déjà prévue.
- **H3** (admin local de secours ne modifie jamais prix/plafonds) : confirmé.
- H4/H5 : hypothèses par défaut conservées.

`docs/architecture/SYNC.md` §6 a été mis à jour pour refléter ces décisions comme tranchées (plus
comme points ouverts). Ce rapport couvre l'implémentation V1 qui a suivi.

## Fichiers créés

- `backend/sync/` (nouvelle app Django) :
  - `models.py` — `DebtMovement(SyncableModel)`, `NodeAuthToken`, `SyncBatchLog`, `SyncConflictLog`.
  - `services.py` — `recompute_client_debt`, `record_debt_movement`, `apply_debt_movement`,
    traitement des lots `push` (`process_push_batch` + un handler par modèle supporté en V1).
  - `authentication.py` — `NodeTokenAuthentication` (jeton de nœud, distinct des JWT utilisateur).
  - `permissions.py` — `IsValidNodeToken`.
  - `views.py` — `HandshakeView`, `PushView`, `PullView`, `StatusView`, `SyncConflictListView`.
  - `serializers.py`, `admin.py`, `urls.py`, `apps.py`.
  - `migrations/0001_initial.py`.
  - `management/commands/sync_now.py` — cycle push+pull pour un futur nœud local/poste desktop.
  - `tests/test_sync.py` — 18 tests (voir détail plus bas).
- `backend/treasury/services.py` — `promote_closure_to_cashbook` extrait de
  `CashClosureViewSet.push_to_cashbook` (voir section dédiée).
- `backend/core/migrations/0013_sync_degraded_mode_fields.py`.

## Fichiers modifiés

- `backend/core/models.py` :
  - `SyncableModel.save()` : marque désormais `is_synced=False` à chaque création/modification
    locale (sauf `node_origin='CLOUD'` ou `_sync_bypass=True` explicite, utilisé par le traitement
    `push` côté Cloud).
  - `Node.is_sync_degraded(threshold_hours=None)` : nouvelle méthode, cœur de la décision H2.
  - `Config` : nouveaux champs `degraded_sync_threshold_hours` (24 h par défaut),
    `offline_credit_limit_ratio` (0.80 par défaut).
  - `Config.get_instance()` : `refresh_from_db()` ajouté après une première création — voir « Bug
    latent corrigé au passage » ci-dessous.
- `backend/sales/views.py` :
  - `_effective_credit_limit(client, node, config)` : nouvelle fonction, implémente H2. Appliquée
    aux deux contrôles de plafond existants (dette brute et déficit net du mois) — **extension du
    module existant, pas de duplication**, conformément à la consigne du coordinateur.
  - `_record_debt_movement_after_commit(...)` : planifie l'écriture du `DebtMovement` via
    `transaction.on_commit`, après que la transaction de création de facture a réellement validé
    (voir « Point de contention découvert et corrigé » ci-dessous).
  - Les 4 points où `Client.current_debt` est modifié (création standard, remboursement BP,
    annulation, expiration automatique) créent désormais, en plus de la mise à jour `F()` déjà
    existante et inchangée, un `DebtMovement` correspondant.
- `backend/treasury/views.py::CashClosureViewSet.push_to_cashbook` : délègue maintenant à
  `treasury.services.promote_closure_to_cashbook` — **aucun changement de comportement**, pur
  déplacement de code pour le rendre réutilisable par `sync.services._push_cash_closure`.
- `backend/kiese/settings.py` : `sync.apps.SyncConfig` ajoutée à `INSTALLED_APPS`.
- `backend/kiese/urls.py` : `path('api/sync/', include('sync.urls'))`.
- `backend/requirements.txt` : ajout de `requests` (utilisé par `sync_now` pour parler au Cloud
  depuis un futur nœud local).
- `docs/architecture/SYNC.md` : §6 mis à jour (H1/H2/H3 tranchés, documentés comme décisions).
- `docs/qa/REGISTRE_BUGS.md` : BUG-004 passé à `CORRIGÉ (V1 — périmètre partiel)` avec fiche détaillée.

## Décision d'implémentation structurante : deux chemins distincts pour `current_debt`

En écrivant les tests, j'ai découvert qu'un recalcul systématique de `current_debt` à partir de la
somme des `DebtMovement` (tel que décrit naïvement par SYNC.md §2.2) **casserait silencieusement**
toute dette d'ouverture déjà présente en base et non couverte par un mouvement (ex. clients créés par
import Excel, fixtures de test avec `current_debt` préréglé, démonstrations manuelles) — le premier
recalcul écraserait cette dette par la seule somme des nouveaux mouvements, perdant la valeur
d'origine. Ce risque concret aurait cassé plusieurs suites de tests déjà écrites par
`testeur-ventes` (`sales/tests/test_invoices.py`, qui crée des clients avec un `current_debt` non nul
sans mouvement associé).

**Solution retenue, non documentée explicitement dans la conception initiale mais cohérente avec
elle** : deux fonctions distinctes dans `sync.services` :
- `record_debt_movement(...)` — journal **uniquement**, utilisée par le chemin LOCAL normal
  (`sales/views.py`), qui continue de mettre à jour `current_debt` par son mécanisme `F()` existant,
  déjà correct et testé. Le mouvement n'est qu'une trace additive destinée à une future
  synchronisation, jamais une autorité immédiate sur la valeur.
- `apply_debt_movement(...)` (= `record_debt_movement` + `recompute_client_debt`) — réservée au
  traitement des mouvements reçus d'un **autre nœud** via `/api/sync/push/`
  (`sync.services._push_debt_movement`). C'est uniquement dans ce cas que le recalcul par somme est
  l'opération correcte : il réconcilie des mouvements venant de plusieurs boulangeries réellement
  séparées, sans dépendre de l'ordre d'arrivée.

Cette distinction est maintenant documentée dans les docstrings de `sync/services.py` ; je recommande
de l'ajouter explicitement à `docs/architecture/SYNC.md` §2.2 lors d'une prochaine révision (signalé,
pas corrigé ici pour rester focalisé sur le rapport d'implémentation plutôt que de retoucher sans fin
le document de conception déjà validé).

## Point de contention découvert et corrigé : `transaction.on_commit`

Première version de l'implémentation : `record_debt_movement(...)` appelé directement à l'intérieur
de la même transaction que `InvoiceViewSet.create` (déjà `@transaction.atomic`). Conséquence
constatée en relançant `sales.tests.test_invoices.ConcurrentInvoiceBPTests` (10 créations de facture
concurrentes sur le même client) : des mises à jour de dette étaient perdues, test qui ne l'était pas
avant mon ajout.

**Diagnostic rigoureux avant correction** (pas supposé) : j'ai isolé la cause en rejouant le même
scénario de concurrence avec `unittest.mock.patch` neutralisant complètement l'écriture du
`DebtMovement` — le test restait flaky (`database table is locked: core_config`) **même sans aucune
ligne de mon code exécutée**. Conclusion : cette fragilité de `ConcurrentInvoiceBPTests` sous SQLite
(verrouillage par table en mode "shared cache" mémoire utilisé par les tests) est **pré-existante**,
pas introduite par ce ticket — mais ajouter une écriture supplémentaire à l'intérieur de la même
transaction aggravait sa probabilité d'occurrence. J'ai donc :
1. Déplacé l'écriture du `DebtMovement` hors de la transaction principale via `transaction.on_commit`
   (`sales/views.py::_record_debt_movement_after_commit`) — n'ajoute plus aucune charge à la
   transaction critique.
2. Ajouté des retentatives (`_WRITE_MAX_RETRIES`, même logique que
   `treasury.views._APPEND_MAX_RETRIES`) dans `record_debt_movement`/`recompute_client_debt`, par
   robustesse pour l'usage réel (desktop/SQLite), sans incidence sur PostgreSQL en production.

Après cette correction, `ConcurrentInvoiceBPTests` repasse de façon stable (vérifié sur plusieurs
exécutions), et le mécanisme ne contribue plus à cette fragilité préexistante. **Je n'ai pas modifié
`sales/tests/test_invoices.py`** (propriété de `testeur-ventes`, qui a lui-même ajouté en parallèle
une boucle de retentatives dans le test pendant cette session — collision de calendrier normale,
sans conflit de fond : nos deux changements sont compatibles et le test passe avec les deux en place).

## Tests ajoutés (`backend/sync/tests/test_sync.py`, 18 tests, tous passent)

- `HandshakeAndAuthTests` (4) — jeton valide/absent/révoqué, JWT utilisateur rejeté sur les routes
  `/api/sync/*`.
- `TwoNodesOfflineDebtScenarioTests` (3) — **scénario central** : dette correcte et commutative
  (K1 puis K2, et K2 puis K1), catégorie `RISK` recalculée après consolidation.
- `PushIdempotenceTests` (2) — rejeu du même `batch_id` → même résultat, pas de doublon ; rejeu du
  même UUID d'enregistrement sous un nouveau `batch_id` → toujours pas de doublon.
- `InterruptedBatchRecoveryTests` (1) — dépendance manquante rejetée explicitement, puis acceptée
  sans perte ni doublon après coup (y compris sur un troisième envoi redondant).
- `ClientOwnershipConflictTests` (1) — un nœud non propriétaire ne peut pas réécrire l'identité d'un
  client ; conflit journalisé (`SyncConflictLog`).
- `PullCursorTests` (2) — changement de prix reçu au pull suivant ; dette recalculée au Cloud visible
  au pull du nœud propriétaire.
- `CashClosureOfflineSyncTests` (2) — clôture validée poussée depuis un nœud → inscrite au Livre de
  Caisse Direction par le Cloud, chaîne de hash intègre ; rejeu sans deuxième écriture.
- `DegradedModeCreditLimitTests` (3) — nœud jamais synchronisé = non dégradé (préserve le
  comportement actuel) ; nœud resynchronisé puis stale = dégradé ; blocage effectif à 80 % du
  plafond nominal en mode dégradé.

## Vérifications finales

- `python manage.py check` → 0 problème.
- `python manage.py makemigrations --check --dry-run` → seul le drift pré-existant déjà documenté
  par `ingenieur-blockchain`/`nettoyeur-securite` sur `production`/`clients`/`treasury` apparaît
  (`AutoField`→`BigAutoField` sur d'anciens modèles, sans rapport avec ce travail) — **aucune
  nouvelle dérive** sur `core`, `sales`, `sync`.
- `python manage.py test` (suite complète, ~190 tests au moment de la dernière exécution, en
  comptant les ajouts concurrents d'autres agents pendant cette session) → **OK**, uniquement des
  `expected failures` déjà documentées par les testeurs d'autres modules (non liées à ce travail).
  Relancé plusieurs fois pour écarter la flakiness connue de `ConcurrentInvoiceBPTests` (voir
  section dédiée) : stable après la correction `transaction.on_commit`.
- `manage.py sync_now --node-code=K1 --dry-run` exécuté avec succès contre `backend/db.sqlite3` (0
  enregistrement en attente, comportement attendu — aucune donnée créée par cette commande en mode
  `--dry-run`).
- `npm run build` : non applicable, aucun fichier frontend touché (périmètre backend uniquement,
  conformément à la mission — le bandeau frontend reste à faire par `dev-frontend`).

## Ce qui reste pour une V2 (scope V1 délibérément limité, voir SYNC.md §11)

- Modèles non encore câblés dans `sync.services.PUSH_HANDLERS` : production (`ProductionSession`,
  `BreadTransfer`, `ConsumableMovement`...), trésorerie locale (`LocalExpense`, `FacturierReport`,
  `DisbursementVoucher`), caisse sociale.
- `SyncStatusBadge` frontend (coordination `dev-frontend`).
- `sync.OutboxBatch` et l'orchestration périodique réelle (service en tâche de fond Electron) —
  relève de `packaging-desktop`, phase 5, qui peut maintenant démarrer sur la base de ce module.
- UI de résolution de conflits au siège (actuellement `/admin/` + `/api/sync/conflicts/` en lecture).
- Tests avec une véritable deuxième base de données séparée (actuellement, les « deux nœuds » du
  test central sont deux jetons différents contre la même base — suffisant pour valider la logique
  de réconciliation, pas pour un test de charge réseau réel confié à `testeur-charge`).

## Points à signaler au coordinateur / au client

1. **Précision sur H2 non explicitement couverte par la décision du client** : un nœud qui n'a
   jamais synchronisé n'est pas considéré « dégradé » par défaut (sinon tous les nœuds existants,
   qui n'ont encore jamais appelé `/api/sync/handshake/`, se retrouveraient immédiatement à 80 % de
   plafond dès le déploiement du code, changeant silencieusement le comportement actuel pour tout le
   monde). Seul un nœud qui a déjà prouvé savoir se synchroniser puis a cessé de le faire au-delà du
   seuil est dégradé. À confirmer explicitement que c'est la lecture voulue de la décision H2.
2. **Bug latent de `Config.get_instance()` corrigé au passage** (défauts littéraux restant des
   chaînes Python tant qu'aucune lecture SQL n'a eu lieu) — sans lien direct avec BUG-004, mais
   bloquant pour implémenter H2 et potentiellement risqué pour tout futur calcul utilisant un champ
   `Config` sur une base toute neuve. Signalé pour que `relecteur-code`/`auditeur-comptable` en aient
   connaissance.
3. **Distinction `record_debt_movement` vs `apply_debt_movement`** (voir section dédiée ci-dessus) :
   à intégrer formellement dans une prochaine révision de `docs/architecture/SYNC.md` §2.2, qui ne la
   décrivait pas explicitement.
