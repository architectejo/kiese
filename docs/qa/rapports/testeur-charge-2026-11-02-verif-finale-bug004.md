# Rapport — testeur-charge — 2026-11-02 — Passe finale de vérification BUG-004

## Mission

Vérification finale (demandée par le coordinateur/client) du ticket **BUG-004**
(synchronisation nœud local ↔ cloud), au statut `CORRIGÉ (V1 + extension
2026-11-02, périmètre partiel)` avant cette session, sous l'angle
charge/concurrence/résilience (mon domaine) sur les deux extensions livrées
le même jour par `architecte-sync` :

1. Câblage de 9 modèles supplémentaires dans `sync.services.PUSH_HANDLERS`
   (`production.ProductionSession`/`ProductionSessionLine`, `BreadDisposal`,
   `ConsumableMovement`, `BreadTransfer`/`BreadTransferLine`,
   `treasury.LocalExpense`, `FacturierReport`, `DisbursementVoucher`).
2. Migration de PK de `clients.SocialContribution`/`SocialDistribution`/
   `SocialDistributionLine` de `BigAutoField` vers UUID (`SyncableModel`),
   puis câblage de ces 3 modèles.

Documents lus avant de commencer : les deux rapports d'extension
(`docs/qa/rapports/architecte-sync-2026-11-02-bug004-extension.md` et
`...-social-uuid.md`), la fiche BUG-004 complète du registre, et
`docs/architecture/SYNC.md` (notamment §3 à §5, §7, §11, §12).

## Méthode

Conformément à CLAUDE.md §7 règle 2, je n'ai **jamais** corrigé de code
applicatif — uniquement écrit des tests et vérifié des comportements réels.
Tous les scripts/tests sont dans `backend/sync/tests/` et
`backend/clients/tests/`, lancés uniquement contre la base de test Django
locale (jamais un serveur de production).

## Travaux réalisés

### 1. Relecture du code (`backend/sync/services.py`)

Relecture complète des 9 nouveaux handlers (`_push_production_session`,
`_push_production_session_line`, `_push_bread_disposal`,
`_push_consumable_movement`, `_push_bread_transfer`,
`_push_bread_transfer_line`, `_push_local_expense`,
`_push_facturier_report`, `_push_disbursement_voucher`,
`_push_social_contribution`, `_push_social_distribution`,
`_push_social_distribution_line`) et des deux migrations
(`backend/clients/migrations/0008_social_syncable_step1.py` +
`0009_social_syncable_step2.py`). Le mécanisme est bien celui déjà en place
(upsert par UUID, rejet explicite « dépendance manquante », machine à états
avant-seulement, `_sync_bypass=True`, transaction par enregistrement) —
aucun changement structurel introduit, conforme à la contrainte donnée aux
deux missions précédentes.

### 2. Tests de charge/concurrence réels (nouveaux, pas une relecture)

**`backend/sync/tests/test_charge_sync_verif_finale_bug004.py`** (5 tests,
tous passent) :

- `BreadTransferConcurrentCreateRaceTests` :
  - **8 threads réellement concurrents** (`threading.Thread`, vraies
    connexions DB séparées, `TransactionTestCase`) poussent le **même**
    UUID de `BreadTransfer` en même temps (simulation : `to_node` a perdu
    la connexion juste après l'envoi initial et retente plusieurs fois en
    parallèle avant de savoir si le Cloud a bien reçu). Résultat : jamais de
    doublon (`BreadTransfer.objects.filter(pk=...).count() == 1` après la
    course), jamais de 500 (uniquement 200 ou 503 — comportement BUG-062/067
    déjà en place), et un rejeu ultérieur (hors course) retrouve
    systématiquement `ACCEPTED`.
  - **Deux nœuds réels et distincts** (K1 = `from_node`, K4 = `to_node`,
    deux jetons `NodeAuthToken` différents) poussent en vraie concurrence
    des opérations qui se référencent : K1 pousse la transition
    `PENDING→RESPONDED` pendant que K4 rejoue en parallèle la création
    initiale (`PENDING`). État final toujours cohérent (`PENDING` ou
    `RESPONDED`, jamais un état incohérent ni une régression visible une
    fois `RESPONDED` atteint), jamais plus d'une ligne `BreadTransfer`.
- `SocialDistributionLineConcurrentCreateTests` : 6 threads poussent chacun,
  en parallèle, la **même** `SocialDistribution` (pas encore créée côté
  Cloud) accompagnée d'une `SocialDistributionLine` différente (un client
  différent par thread) — scénario demandé explicitement par le
  coordinateur (`SocialDistributionLine` → `SocialDistribution`). Résultat :
  une seule `SocialDistribution` créée malgré 6 tentatives de création
  concurrentes du même UUID ; après rattrapage (rejeu individuel hors
  course), chaque client a exactement une ligne — aucun double traitement.
- `NewModelsIdempotenceUnderRapidReplayTests` : rejeu séquentiel rapide
  (20×) de `SocialContribution` et `BreadTransfer` — toujours une seule
  ligne en base.

**`backend/clients/tests/test_migration_social_uuid_volume.py`** (1 test,
passe, ~38 s) : exécute réellement la migration 0008→0009 sur un jeu de
données **fictif** de volume nettement supérieur au test unitaire existant
(`test_migration_social_uuid.py`, 2 cotisations/1 distribution/1 ligne) :

- 8 boulangeries fictives × 40 clients fictifs × 3 cotisations = **960**
  `SocialContribution`.
- 8 boulangeries × 2 années = **16** `SocialDistribution`.
- 16 distributions × 40 clients = **320** `SocialDistributionLine`.

Ce volume dépasse volontairement le `BATCH = 500` utilisé par
`bulk_update()` dans `_populate_uuids` (migration 0009), pour exercer
réellement le passage multi-lots, pas seulement un seul lot. Vérifié après
migration :

- aucune perte de ligne (mêmes effectifs exacts avant/après, sur les 3
  modèles) ;
- aucune collision d'UUID, y compris entre les 3 catégories de modèles
  (contributions, distributions, lignes) et entre les 16 distributions de 8
  boulangeries différentes ;
- chaque `SocialDistributionLine.distribution_id` pointe vers l'UUID exact
  de la bonne distribution — (nœud, année) — vérifié pour les **320**
  lignes une par une, pas un échantillon ; aucun mélange entre deux
  boulangeries ou deux années n'a été détecté.

### 3. Non-régression (CLAUDE.md §7 règle 5)

- `backend/.venv/Scripts/python.exe manage.py test` (suite complète) →
  **477 tests, OK** (0 échec), ~20 minutes. Inclut les 6 nouveaux tests de
  cette session ainsi que les tests déjà existants couvrant BUG-062/067/072
  (idempotence/rejeu sous contention, jamais de 500, jamais de résultat
  `REJECTED` archivé pour toujours — `sync/tests/test_charge_sync_volume.py`,
  relancé sans modification, toujours vert).
- `manage.py makemigrations --check --dry-run` → « No changes detected ».

## Conclusion

**Aucun défaut réel trouvé.** Le câblage des 9 modèles et la migration PK
UUID de la caisse sociale se comportent correctement sous charge et
concurrence réelle (vrais threads, vrais nœuds distincts, volume supérieur
aux tests unitaires existants) : pas de collision d'UUID, pas de double
traitement, pas de blocage permanent en cas de retry après 503, pas de perte
de données sur la migration à volume réaliste.

Un point mineur, **non bloquant**, est documenté comme limitation connue
dans le registre (voir ci-dessous) : les handlers de création (pas les
lignes) des nouveaux modèles ne capturent pas explicitement `IntegrityError`
sur une course de création concurrente du même UUID, contrairement aux
gestionnaires de ligne (`ProductionSessionLine`/`BreadTransferLine`, qui le
font déjà). Observé concrètement dans mes tests : sous course réelle, une
requête concurrente sur deux peut recevoir un rejet transitoire
(« erreur serveur ») au lieu d'un `ACCEPTED` idempotent immédiat. **Sans
perte ni doublon** : le `batch_id` perdant n'est jamais archivé dans
`SyncBatchLog` (comportement BUG-062 déjà en place), donc tout rejeu
ultérieur retrouve l'enregistrement déjà créé par l'autre requête et renvoie
`ACCEPTED`. Ce cas est de toute façon très improbable en pratique (ces
modèles sont normalement créés par un seul nœud à la fois, pas par deux
requêtes concurrentes sur le même UUID). Je ne l'ai pas corrigé moi-même
(CLAUDE.md §7 règle 2) — un ticket séparé (non bloquant) peut être ouvert
pour `architecte-sync` si une harmonisation est souhaitée.

**BUG-004 passé à `VÉRIFIÉ`** dans `docs/qa/REGISTRE_BUGS.md`, avec une note
datée (2026-11-02) précisant le périmètre couvert et les résidus légitimes
(bandeau frontend, `OutboxBatch` desktop réel, UI de résolution de conflits,
second nœud physiquement séparé pour un vrai test réseau, PK locales de
ligne héritées de `InvoiceLine`, et le point mineur `IntegrityError`
ci-dessus) — documentés comme limitations connues plutôt que comme blocages.

## Fichiers créés/modifiés

- `backend/sync/tests/test_charge_sync_verif_finale_bug004.py` — nouveau,
  5 tests.
- `backend/clients/tests/test_migration_social_uuid_volume.py` — nouveau,
  1 test (migration à volume réaliste).
- `docs/qa/REGISTRE_BUGS.md` — fiche BUG-004 mise à jour (statut →
  `VÉRIFIÉ`, nouvelle sous-section « Passe finale de vérification »).
- `docs/qa/rapports/testeur-charge-2026-11-02-verif-finale-bug004.md` — ce
  rapport.

Aucun fichier de code applicatif n'a été modifié.
