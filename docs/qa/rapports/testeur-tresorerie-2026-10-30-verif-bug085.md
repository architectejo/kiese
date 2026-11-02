# Vérification indépendante de BUG-085 — testeur-tresorerie, 2026-10-30

Vérification de la correction apportée par `ingenieur-blockchain` (2026-10-30) au ticket BUG-085,
que j'avais ouvert le 2026-10-29 en vérifiant le volet trésorerie de BUG-083 (CLAUDE.md §7 règle 3 :
c'est logiquement moi qui clôture ce ticket).

## Rappel du bug

`treasury.hashing.compute_cashbook_entry_hash` ne couvrait pas `CashbookEntry.is_correction`
(introduit par BUG-083) : une altération directe en base de ce seul champ (ex.
`CashbookEntry.objects.filter(pk=x).update(is_correction=False)`) ne cassait pas la chaîne de hash
et n'était donc pas détectée par `verify_cashbook_chain`/`integrity_check`/`blockchain.run_check` —
alors que `is_correction` est une classification comptable binaire que CLAUDE.md §5.5 veut protéger
contre toute altération silencieuse.

## Relecture du diff

- `backend/treasury/hashing.py` :
  - `HASH_FORMAT_VERSION` passé de `2` à `3`.
  - `compute_cashbook_entry_hash` (formule v3) : payload enrichi de
    `'is_correction': bool(getattr(entry, 'is_correction', False))` — booléen normalisé explicitement,
    évite toute ambiguïté `True`/`'True'`/`1` dans la sérialisation JSON.
  - Nouvelle fonction `compute_v2_hash` : copie figée de l'ancienne formule (sans `is_correction`),
    même rôle que `compute_legacy_v1_hash` créée pour BUG-001/la migration `0007` — reproduire
    fidèlement la formule qui a réellement écrit les `block_hash` existants, pour (a) vérifier
    l'absence de rupture préexistante avant de recalculer, et (b) permettre une migration inverse
    exacte.
  - Aucune duplication de formule constatée : `blockchain/views.py` n'importe que
    `verify_cashbook_chain` de `treasury.hashing` ; `treasury/views.py` importe
    `compute_cashbook_entry_hash`, `verify_cashbook_chain`, `GENESIS_HASH` du même module unique.
    Conforme à CLAUDE.md §5.5 (« Une seule fonction de hash pour l'écriture et la vérification »).
- `backend/treasury/migrations/0014_bug085_recompute_hash_is_correction.py` : migration de données
  en deux passes, même schéma que `0007_recompute_cashbook_hash` (BUG-001) :
  1. Revérifie la chaîne existante sous la formule v2 (celle qui a réellement produit les
     `block_hash` en base jusqu'ici).
  2. Recalcule en v3 uniquement le préfixe validé à l'étape 1 ; s'arrête à la première rupture déjà
     présente sous v2 **sans l'écraser** (hash « v2 legacy » conservé tel quel, détectable ensuite
     par un contrôle d'intégrité plutôt que silencieusement masqué).
  Réversible (`revert_to_v2_hash`, qui redétermine la frontière du préfixe effectivement touché par
  la migration forward avant de restaurer).
- `backend/treasury/tests/test_bug085_hash_is_correction.py` (nouveau, 5 tests) : reproduction exacte
  de la fiche (falsification directe de `is_correction` sur une correction, cas symétrique
  `False -> True`, vérification croisée treasury/blockchain) + 2 tests dédiés au comportement de la
  migration (préfixe sain entièrement recalculé et validé sous v3 ; préfixe avec rupture v2
  préexistante non écrasé).

## Point d'attention principal : l'analyse « impossible à respecter à l'octet près »

Le rapport de correction documente que l'hypothèse initiale du ticket (« le recalcul ne change rien
pour les écritures non-correction ») est en réalité impossible à tenir littéralement : ajouter une
clé à un payload JSON canonique (même valant `False`) change nécessairement le condensé SHA-256,
quelle que soit sa valeur logique — propriété mathématique d'une fonction de hachage cryptographique,
pas une erreur d'implémentation à corriger.

J'ai vérifié cette analyse indépendamment, pas seulement fait confiance au rapport :
- En relisant `compute_v2_hash` vs `compute_cashbook_entry_hash` (v3) : le payload v3 a
  structurellement une clé de plus (`'is_correction'`), donc une chaîne JSON sérialisée différente
  pour toute écriture, y compris celles où `is_correction=False` — c'est un fait vérifiable par
  simple lecture du code, confirmé par les tests (`test_migration_recomputes_all_hashes_but_keeps_logical_chain_valid`
  constate explicitement 5 écritures recalculées, **5 ont changé de `block_hash`**, y compris les 4
  `is_correction=False`).
- Les trois garanties substituées par l'agent sont les bonnes au regard de CLAUDE.md §5.5 et de la
  décision client BUG-083 : (a) la valeur **logique** `is_correction` de chaque écriture reste
  inchangée avant/après (vérifié par relecture en base après migration) ; (b) la chaîne recalculée
  est intégralement valide sous la nouvelle formule v3 (`verify_cashbook_chain` → tous les blocs
  valides) ; (c) chaque nouveau hash correspond exactement à `compute_cashbook_entry_hash` v3 (vérifié
  bloc par bloc dans le test). Ces trois garanties n'exigent à aucun moment une stabilité
  octet-pour-octet du hash — seulement l'intégrité de la chaîne et la détectabilité de toute
  falsification *future*, qui est précisément l'objectif de CLAUDE.md §5.5 et le seul objectif réel
  du ticket BUG-085. **Conclusion : l'analyse de l'agent est correcte et suffisante.**
- `backend/db.sqlite3` avait bien `0` `CashbookEntry` au moment de l'exécution de la migration —
  confirmé indépendamment par une requête SQL directe sur la base réelle
  (`SELECT COUNT(*) FROM treasury_cashbookentry` → `0`). Rien à recalculer en pratique sur
  l'environnement de développement partagé.

## Reproduction indépendante du scénario de la fiche

Falsification directe en base de `is_correction` (`.update(is_correction=False)` sur une écriture
correction) :
- Détectée par `verify_cashbook_chain` (test `test_flipping_is_correction_directly_in_db_is_detected`).
- Détectée également par `blockchain._verify_chain_for_node` via `stats['is_intact'] == False` et
  `stats['tampered_count'] >= 1` (test `test_treasury_and_blockchain_agree_on_is_correction_tampering`)
  — les deux points d'entrée (`GET /api/treasury/cashbook/integrity_check/` et
  `POST /api/blockchain/snapshots/run_check/`) donnent le même verdict, puisqu'ils partagent la même
  fonction `verify_cashbook_chain` unique.

## Exécution des tests

- `python manage.py test treasury blockchain -v2` → **77/77 tests OK**, 0 échec, 0 régression (inclut
  les 5 nouveaux tests `test_bug085_hash_is_correction.py`).
- `python manage.py test` (suite complète) → **377 tests, 1 seul échec** :
  `clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests::test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db`
  (« database table is locked »). Sans rapport avec BUG-085/treasury/blockchain.
  - Relancé seul, en isolation, 3 fois : **OK, puis FAIL, puis FAIL** — résultat non reproductible de
    façon stable, sans qu'aucun autre agent ou processus de test ne tourne en parallèle sur la machine
    pendant ces relances. Confirme une **flakiness réelle** du test lui-même (16 threads réels créant
    des `Client` en concurrence sur SQLite, contention sur `clients_clientcodesequence`/verrou fichier
    mono-écrivain), pas une régression introduite par la correction BUG-085. Ce test et ce motif
    d'échec sont déjà documentés de façon récurrente dans ce registre sous BUG-017 (lignes 543, 653,
    2376, 5653, 5695, 5828, 5892, 7367, 7738, 7927 du registre notamment, sur plusieurs mois de
    vérifications). Conclusion : **flaky confirmé, pas de nouveau ticket ouvert**, conformément à la
    mission.
- `python manage.py makemigrations --check --dry-run` → `No changes detected`.
- `PRAGMA integrity_check` sur `backend/db.sqlite3` (via `./.venv/Scripts/python.exe` explicite, pas
  le `python` du PATH) → `[('ok',)]`.
- `CashbookEntry.objects.count()` sur la base réelle (hors tests) → `0`, confirmé.

## Conclusion

Correction **CONFORME**. Aucune duplication de formule entre `treasury/hashing.py` et
`blockchain/views.py`. Migration `0014` correcte, réversible, et respecte le principe « ne jamais
écraser une rupture déjà présente ». Les tests ajoutés reproduisent fidèlement le scénario de la
fiche et passent. BUG-085 passé à **VÉRIFIÉ** dans `docs/qa/REGISTRE_BUGS.md` (table ligne BUG-085 et
fiche détaillée, sous-section « Vérification »).

Point annexe (clients.tests — flakiness SQLite BUG-017) : confirmé flaky en isolation, pas de ticket
séparé ouvert, simplement noté ici et dans la fiche BUG-085 comme déjà documenté sous BUG-017.

Aucun code applicatif n'a été modifié au cours de cette vérification (CLAUDE.md §7 règle 2).

## Fichiers concernés

- `D:\Projects\kiesse\backend\treasury\hashing.py` (relu, non modifié)
- `D:\Projects\kiesse\backend\treasury\migrations\0014_bug085_recompute_hash_is_correction.py` (relu, non modifié)
- `D:\Projects\kiesse\backend\treasury\tests\test_bug085_hash_is_correction.py` (relu, exécuté, non modifié)
- `D:\Projects\kiesse\backend\clients\tests\test_verification_2026_10_22.py` (relancé en isolation, non modifié)
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (mis à jour : BUG-085 → VÉRIFIÉ)
