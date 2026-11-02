# Rapport — architecte-sync — 2026-11-02 (suite BUG-004 : PK UUID pour la caisse sociale)

## Contexte

Reprise d'une session interrompue (redémarrage de l'environnement). Avant de reprendre le travail,
l'état réel du dépôt a été vérifié fichier par fichier plutôt que supposé :

- `backend/clients/models.py` : `SocialContribution`/`SocialDistribution`/`SocialDistributionLine`
  héritaient déjà de `SyncableModel` (PK UUID) — le code applicatif avait déjà été modifié.
- `backend/clients/migrations/0008_social_syncable_step1.py` et `0009_social_syncable_step2.py`
  existaient déjà, complets en apparence, mais **n'étaient appliqués dans aucune base**
  (`showmigrations clients` → `[ ]` pour les deux).
- `backend/sync/services.py` : commentaire daté du 2026-11-02 affirmant toujours que ces 3 modèles
  « ne sont pas des `SyncableModel` » — **obsolète** par rapport à `models.py`, confirmant un état
  partiel incohérent (modèle déjà migré en Python, migration non vérifiée/jamais appliquée, câblage
  sync non fait).
- `docs/qa/REGISTRE_BUGS.md` fiche BUG-004 : dernière entrée documentait explicitement la
  contradiction signalée au coordinateur et l'absence de décision tranchée seul — cohérent avec le
  fait que la migration de schéma avait été préparée mais pas vérifiée ni appliquée.

Conclusion : le travail n'était ni « à refaire de zéro » ni « terminé » — la migration existait mais
n'avait jamais été exécutée avec succès, et personne n'avait vérifié qu'elle fonctionnait.

## Ce qui a été fait

### 1. Vérification effective de la migration 0008/0009 (jamais seulement relue)

En exécutant réellement `migrate clients 0008` puis `0009` sur une base jetable, **deux bugs réels**
ont été détectés (la migration n'avait jamais tourné avec succès avant cette session) :

1. **Ordre des opérations de bascule PK** (`0009`) : `RenameField(id→legacy_int_id)` puis
   `AlterField(legacy_int_id, BigIntegerField())` retirait `primary_key=True` du seul champ qui le
   portait encore, avant que le nouveau champ `id` (renommé depuis `new_id`) ne devienne lui-même
   `primary_key=True`. Django réinjecte alors implicitement un second champ auto-incrémenté nommé
   `id` dans l'état de migration (absence de tout champ `pk=True` déclaré) → SQLite détecte une
   colonne dupliquée au moment de reconstruire la table (`duplicate column name: id`).
   **Corrigé** en réordonnant les opérations : le nouveau champ devient `pk=True` **avant** que
   l'ancien ne perde ce statut, pour qu'il existe toujours au moins un champ `pk=True` déclaré.

2. **`_populate_uuids` (RunPython) sans `.using(db_alias)`** : les requêtes de la fonction de
   repeuplement utilisaient implicitement l'alias `'default'`, quel que soit l'alias réellement
   migré par `schema_editor`. Sans incidence sur ce dépôt en pratique (une seule base, toujours
   `'default'`), mais révélé en testant la migration sur un alias secondaire dédié (nécessaire pour
   isoler le test de migration de la base de test Django déjà entièrement migrée — voir section
   suivante) : les lignes `new_id` restaient `NULL` (mises à jour exécutées sur le mauvais alias),
   puis la bascule de PK suivante leur attribuait **toutes la même valeur de repli** via
   `COALESCE(id, <littéral unique>)` → violation de contrainte `UNIQUE` lors de la reconstruction de
   table. **Corrigé** par `.using(db_alias)` explicite sur toutes les requêtes de `_populate_uuids`.

Les deux bugs étaient réels et auraient empêché cette migration de s'appliquer dès la première
tentative en production. Ni l'un ni l'autre n'était visible à la seule lecture du code.

### 2. Test de non-régression de migration

`backend/clients/tests/test_migration_social_uuid.py` (nouveau) : la base de test Django habituelle
(alias `default`) est déjà migrée à la tête de chaque app avant le premier test — impossible de la
faire reculer jusqu'à `0007` puisque `0009` est délibérément irréversible
(`_populate_uuids_reverse` lève une erreur explicite plutôt que de fabriquer un faux retour en
arrière, cohérent avec le choix documenté dans l'en-tête de la migration). Le test ouvre donc sa
propre base SQLite jetable sur un alias ajouté dynamiquement, construite par migration forward
*depuis zéro* (jamais par retour en arrière), seed des données via les modèles historiques de l'état
`0007`, puis migration jusqu'à `0009` et vérification :
- aucune perte de ligne (2 cotisations, 1 distribution, 1 ligne) ;
- nouvelles PK = UUID valides, distinctes des anciens entiers ;
- `SocialDistributionLine.distribution_id` pointe vers le **nouvel** UUID de `SocialDistribution`,
  jamais vers l'ancienne PK entière.

Ce test, exécuté avant la correction du bug n°1, échouait avec `duplicate column name: id` ; il passe
après.

### 3. Câblage dans `sync.services` et `sync_now`

Même mécanisme que l'extension précédente de BUG-004 (aucun changement structurel du protocole) :

- `sync/services.py` : `_push_social_contribution`, `_push_social_distribution`,
  `_push_social_distribution_line` ajoutés à `PUSH_HANDLERS`/`PUSH_MODEL_ORDER`
  (`SocialDistribution` avant `SocialDistributionLine`, conforme à `docs/architecture/SYNC.md` §3.5
  point 7 — qui les listait déjà dans la conception initiale ; seule l'implémentation V1 les avait
  oubliés, d'où la contradiction signalée précédemment).
- Enregistrements mono-nœud : toujours créés/modifiés par le gérant d'une seule boulangerie, jamais
  partagés entre deux nœuds comme `Client`/`Invoice` → aucune règle de résolution de conflit
  multi-nœud à définir pour ces 3 modèles.
- `sync/management/commands/sync_now.py::build_outbound_payload` : les 3 modèles remontent
  désormais dans le lot sortant (filtre `is_synced=False`, symétrique des modèles déjà câblés).

### 4. Tests

- `backend/sync/tests/test_sync_social.py` (nouveau, 9 tests) : push accepté et idempotent,
  dépendance manquante rejetée explicitement puis acceptée après coup sans doublon (coupure de lot),
  transitions `is_paid`/`is_closed` idempotentes, mise à jour des champs de ligne (mérite recalculé
  par le gérant avant clôture) sans doublon, contenu du payload sortant (inclusion/exclusion selon
  `is_synced`).
- `backend/sync/tests/test_sync_bug004_extension.py::UnsupportedModelsAreExplicitlyRejectedTests` :
  `clients.SocialContribution` servait d'exemple de modèle non supporté — désormais accepté, donc
  réassigné à `commissions.ClientCommission` (un vrai `SyncableModel`, toujours absent de
  `PUSH_HANDLERS`) pour continuer à couvrir le rejet explicite d'un modèle non câblé.

### 5. Vérifications finales

- `python manage.py makemigrations --check --dry-run` → aucun changement détecté.
- `python manage.py test` (suite complète) → lancé en arrière-plan en fin de session ; à confirmer
  par le coordinateur/testeur avant de passer BUG-004 à `VÉRIFIÉ` (voir note ci-dessous).

## Registre

Fiche `docs/qa/REGISTRE_BUGS.md` BUG-004 mise à jour (nouvelle sous-section « Suite — migration PK
UUID... »). **Statut laissé à `CORRIGÉ`**, pas de passage à `VÉRIFIÉ` par l'auteur de cette suite
(règle CLAUDE.md §7).

## Point d'attention pour le coordinateur / testeur

- Le lancement final de la suite complète (`python manage.py test`) a été démarré en arrière-plan en
  fin de session pour respecter le budget de temps ; son issue (succès/échec) doit être confirmée
  avant de considérer ce travail entièrement clos.
- Les deux bugs de migration détectés (ordre des opérations PK, alias de connexion dans RunPython)
  n'auraient été visibles qu'à l'exécution réelle de la migration, jamais à la seule relecture —
  argument en faveur de systématiser un test de migration exécuté (comme
  `test_migration_social_uuid.py`) pour toute future migration de ce type (bascule de PK entière vers
  UUID avec RunPython), pas seulement pour celle-ci.
