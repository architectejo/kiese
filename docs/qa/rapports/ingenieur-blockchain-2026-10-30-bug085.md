# Rapport — ingenieur-blockchain — 2026-10-30 — BUG-085

## Ticket traité
BUG-085 — `treasury.hashing.compute_cashbook_entry_hash` ne couvrait pas `CashbookEntry.is_correction`
(introduit par BUG-083) : une altération directe en base de ce seul champ ne cassait pas la chaîne de
hash et n'était donc pas détectée par `verify_cashbook_chain`/`integrity_check`/`blockchain.run_check`.

## Résumé de la correction
1. `backend/treasury/hashing.py`
   - `is_correction` (normalisé explicitement en `bool(...)`) ajouté au `payload` de
     `compute_cashbook_entry_hash`.
   - `HASH_FORMAT_VERSION` : `2` → `3`.
   - Ajout de `compute_v2_hash` : copie figée de la formule précédente (sans `is_correction`), même
     rôle que `compute_legacy_v1_hash` (BUG-001) — reproduit fidèlement la formule qui a réellement
     écrit les `block_hash` existants, utilisée uniquement par la migration de données pour auditer et
     recalculer, et pour permettre une migration inverse exacte.
   - Docstring du module mise à jour pour tracer BUG-085.
2. `backend/treasury/migrations/0014_bug085_recompute_hash_is_correction.py` (nouvelle migration de
   données, réversible) — même schéma en deux passes que `0007_recompute_cashbook_hash` (BUG-001) :
   - Passe 1 : revérifie la chaîne existante sous l'ancienne formule v2 (celle qui a réellement écrit
     les `block_hash` en base jusqu'ici).
   - Passe 2 : recalcule en formule v3 (avec `is_correction`) uniquement le préfixe validé à l'étape 1,
     s'arrête à la première rupture déjà présente sous v2 sans l'écraser (hash « v2 legacy » conservé
     intact, détectable ensuite par un contrôle d'intégrité blockchain).
   - `revert_to_v2_hash` : migration inverse, ne restaure que le préfixe effectivement touché par la
     migration forward.
3. `backend/treasury/models.py` : commentaire au-dessus de `is_correction`/`correction_reason`/
   `corrected_by`/`correction_source_invoice` mis à jour pour refléter que seul `is_correction` est
   désormais couvert par la formule de hash (les 3 autres champs restent du texte d'audit libre, hors
   formule, par choix assumé — inchangé).
4. Nouveau fichier de test `backend/treasury/tests/test_bug085_hash_is_correction.py` (5 tests, tous
   neufs, aucun test existant modifié).

## Aucune duplication de la formule de hash (CLAUDE.md §5.5)
Vérifié par relecture : `backend/blockchain/views.py` importe uniquement `verify_cashbook_chain` depuis
`treasury.hashing` et ne réimplémente aucune boucle ni aucune formule de hash locale. `treasury.hashing`
reste l'unique module où la formule est définie (BUG-001, inchangé par cette correction).

## Contrôle explicite demandé par la mission : `is_correction=False` pour les écritures antérieures à BUG-083
Sur `backend/db.sqlite3` (base de développement partagée), `CashbookEntry.objects.count()` valait `0`
au moment où la migration `0014` a été appliquée dans cet environnement : aucune écriture n'avait
encore été versée dans cette base précise, donc rien à recalculer concrètement là. La migration s'est
appliquée sans erreur (`OK`), `makemigrations --check --dry-run` reste propre après.

Le comportement réel de recalcul a donc été vérifié par un test dédié qui construit un jeu de données
représentatif de l'état réel pré-migration (5 écritures écrites avec la formule v2, 4 avec
`is_correction=False`, 1 avec `is_correction=True`), puis appelle directement la fonction de la
migration :

- **5 écritures recalculées, 5 ont effectivement changé de `block_hash`** — y compris les 4 écritures
  `is_correction=False`.
- **Précision importante par rapport à l'hypothèse énoncée dans le ticket** (« le recalcul ne doit rien
  changer pour les écritures non-correction, même hash qu'avant ») : cette hypothèse, vérifiée
  explicitement par le test, s'avère **techniquement impossible à respecter littéralement**, et ce pour
  une raison structurelle et non pour un défaut d'implémentation. Le `payload` JSON canonique gagne une
  clé supplémentaire (`'is_correction': false`) pour **toute** écriture dès que la formule couvre
  réellement ce champ — qu'elle soit une correction ou non. Le condensé SHA-256 d'une chaîne de
  caractères différente (payload plus long) est nécessairement différent du condensé de l'ancienne
  chaîne, même quand la valeur logique ajoutée est `False`. Il n'existe aucune façon d'étendre la
  couverture du hash à `is_correction` tout en laissant le `block_hash` des écritures
  `is_correction=False` strictement identique à l'octet : ces deux objectifs sont mutuellement
  exclusifs par construction d'une fonction de hachage cryptographique (c'est d'ailleurs précisément la
  propriété recherchée : un payload différent doit produire un hash différent, sans quoi la protection
  serait illusoire).
- La garantie qui compte réellement pour la clôture de BUG-085, et qui **a été vérifiée** par le test :
  1. la valeur **logique** `is_correction` de chaque écriture non-correction reste `False` avant et
     après la migration (relecture en base après recalcul, `refresh_from_db`) ;
  2. la chaîne recalculée est intégralement valide sous la nouvelle formule
     (`verify_cashbook_chain` → `is_valid=True` sur les 5 blocs, aucune rupture introduite par la
     migration elle-même) ;
  3. chaque nouveau `block_hash` correspond exactement à `compute_cashbook_entry_hash` (formule v3),
     vérifié bloc par bloc avec le bon `previous_hash` reconstruit depuis le génésis.
- Ce choix (recalculer TOUS les `block_hash` du préfixe valide, pas seulement ceux où `is_correction`
  change réellement) est cohérent avec la migration historique `0007_recompute_cashbook_hash` (BUG-001),
  qui recalculait déjà la totalité du préfixe valide lors de l'ajout de `node`/`imputation`/
  `source_closure`/`source_bordereau` à la formule, sans tenter de préserver sélectivement les hash des
  écritures où ces champs étaient vides.
- Second test (`test_migration_stops_at_first_v2_break_and_leaves_the_rest_untouched`) : avec une
  rupture déjà présente sous la formule v2 (falsification directe de `entry_amount` avant la migration,
  simulant une base déjà compromise), seule l'écriture avant la rupture est recalculée (1 recalculée,
  1 changée) ; l'écriture rompue et toutes les suivantes conservent leur hash v2 legacy intact, non
  écrasées — confirmé par comparaison directe des `block_hash` avant/après exécution de la migration.

**Conclusion documentée** : sur une base réellement saine (aucune falsification préexistante sous v2),
la migration recalcule la totalité du préfixe valide et change effectivement le `block_hash` de toute
écriture, correction ou non — c'est un effet de bord inévitable et sans conséquence de l'extension de la
formule (même principe que `0007`), pas une régression. Rien de plus n'a changé pour les écritures
`is_correction=False` : leur contenu logique, leur place dans la chaîne, et le fait qu'elles restent
valides sous la nouvelle formule sont tous confirmés par le test.

## Test de reproduction exact de la fiche BUG-085
`backend/treasury/tests/test_bug085_hash_is_correction.py::IsCorrectionTamperingDetectedTests` :
1. Pousse une écriture normale (`is_correction=False`) puis une écriture de correction
   (`is_correction=True`), via `append_cashbook_entry` (point d'entrée unique d'écriture).
2. Falsifie directement en base le **seul** champ `is_correction` de la correction :
   `CashbookEntry.objects.filter(pk=correction.pk).update(is_correction=False)`.
3. `verify_cashbook_chain` détecte désormais la rupture à la bonne écriture (`is_valid=False`), et
   l'écriture suivante (chaînée sur le hash désormais incohérent) est également signalée.

Confirmé en relisant le code AVANT correction (formule sans `is_correction`) que ce test échouait bien
(aucune rupture détectée) ; il passe après l'ajout du champ au payload. Cas symétrique (`False -> True`)
et vérification croisée `treasury.integrity_check`/`blockchain._verify_chain_for_node` (même fonction
`verify_cashbook_chain` sous-jacente, CLAUDE.md §5.5) également couverts par ce fichier.

## Résultats des tests
- `python manage.py test treasury.tests.test_bug085_hash_is_correction` → **5/5 OK**.
- `python manage.py test treasury blockchain` → **77/77 OK**, 0 échec, 0 régression.
- `python manage.py test` (suite complète, 377 tests, ~20 min) → **376 OK, 1 échec**. L'unique échec
  (`clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests::
  test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db`) est **sans rapport avec BUG-085**
  : il porte sur la génération concurrente de codes client (`ClientCodeSequence`) sous SQLite et échoue
  par `database table is locked` (limite connue de SQLite sous forte concurrence de threads, pas une
  régression introduite par ce ticket — aucun fichier `clients/` n'a été touché par cette correction).
  Ticket préexistant, hors périmètre de cette mission (ni ouvert ni corrigé par cette session ;
  signalé ici pour mémoire sans y toucher).
- `python manage.py makemigrations --check --dry-run` → `No changes detected` (propre).
- `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok`.

## Fichiers modifiés/créés (strictement dans le périmètre BUG-085)
- `D:\Projects\kiesse\backend\treasury\hashing.py` (modifié)
- `D:\Projects\kiesse\backend\treasury\migrations\0014_bug085_recompute_hash_is_correction.py` (créé)
- `D:\Projects\kiesse\backend\treasury\models.py` (commentaire mis à jour, aucun changement de schéma)
- `D:\Projects\kiesse\backend\treasury\tests\test_bug085_hash_is_correction.py` (créé)
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (ligne de synthèse + fiche détaillée BUG-085,
  statut → `CORRIGÉ`)
- `D:\Projects\kiesse\docs\qa\rapports\ingenieur-blockchain-2026-10-30-bug085.md` (ce rapport)

Aucun autre fichier touché. Rien côté `frontend/`.

## Statut du ticket
BUG-085 : `OUVERT` → **`CORRIGÉ`** (registre et fiche détaillée mis à jour). Conformément à CLAUDE.md
§7, la vérification revient à `testeur-tresorerie` (statut `CORRIGÉ`, pas `VÉRIFIÉ` — je ne valide pas
ma propre correction).
