# Rapport — ingenieur-blockchain — 2026-10-22

## Périmètre traité

BUG-001, BUG-002, BUG-003 (`docs/qa/REGISTRE_BUGS.md`), tous passés à **CORRIGÉ** (jamais `VÉRIFIÉ` —
c'est `testeur-tresorerie` qui vérifiera, cf. CLAUDE.md §7). Fiches détaillées complètes dans le
registre. Aucun fichier hors `backend/treasury/` et `backend/blockchain/` n'a été modifié.

## Précision du client prise en compte (message du coordinateur en cours de tâche)

M. NDUNGA NSAYI PIERRE a confirmé que la « Blockchain » du projet est **volontairement** une
simulation de chaîne de hash SHA-256 en base relationnelle (SQLite en dev/desktop, PostgreSQL au
cloud), pas une vraie blockchain distribuée — l'hébergement cible (mutualisé type cPanel) ne peut
pas héberger de nœud blockchain réel. L'implémentation livrée ici est déjà strictement conforme à
cette contrainte, sans qu'aucun changement n'ait été nécessaire :
- Aucune dépendance externe de type blockchain, aucun nœud séparé, aucun smart contract, aucun
  appel réseau à un registre tiers.
- Tout est 100 % interne à l'ORM Django : une fonction de hash SHA-256 partagée
  (`backend/treasury/hashing.py`), un verrou `select_for_update()` + une contrainte d'unicité
  SQLite/PostgreSQL (`previous_hash` unique), et une détection de falsification par recalcul et
  comparaison de hash — rien de plus.

## Ce qui a changé

### BUG-001 — Unification de la fonction de hash
- **Nouveau fichier `backend/treasury/hashing.py`** : module sans aucune dépendance à un modèle
  Django au niveau module (prend un objet `entry` dynamiquement) pour éviter tout risque de cycle
  d'import entre `treasury` et `blockchain`. Expose :
  - `compute_cashbook_entry_hash(entry, previous_hash=None)` — LA fonction de hash, utilisée à
    l'écriture (treasury) et à la vérification (blockchain, qui l'importe directement).
  - `verify_cashbook_chain(entries)` — boucle de vérification elle aussi unifiée (avant, `treasury`
    et `blockchain` avaient chacun leur propre boucle en plus de leur propre formule).
  - `compute_legacy_v1_hash` — uniquement pour la migration de données (BUG-003), ne pas réutiliser
    ailleurs.
  - `GENESIS_HASH = '0'*64`.
- `backend/treasury/views.py` : suppression de `_compute_hash` local ; `integrity_check` utilise
  désormais `verify_cashbook_chain`.
- `backend/blockchain/views.py` : suppression de la boucle de hash locale (concaténation
  f-string) ; `_verify_chain_for_node` utilise `treasury.hashing.verify_cashbook_chain`.

**Problème architectural connexe découvert et corrigé dans le même mouvement** (sinon le ticket
n'était pas réellement résolu) : le Livre de Caisse Direction est **une seule chaîne globale**
(`_get_last_balance()` ne filtre jamais par nœud — toutes les boulangeries et le SIEGE chaînent sur
la même séquence). Mais `_verify_chain_for_node` reconstruisait un chaînage reparti du génésis
**par nœud**. Même avec une formule de hash identique entre les deux modules, cette vérification ne
pouvait jamais correspondre au `block_hash` réellement écrit pour un nœud qui n'est pas le premier
contributeur de la chaîne globale — donc le ticket serait resté « en réalité non résolu » pour
toute boulangerie autre que la première à avoir écrit. Corrigé par `_verify_full_chain()` (calcule
la chaîne complète une seule fois) + `_verify_chain_for_node(node, chain_results=...)` (ventile le
résultat déjà calculé par nœud pour le reporting). `run_check` calcule donc la chaîne globale une
seule fois, pas une fois par boulangerie.

**Correction connexe découverte en testant** : `run_check` appelait
`create_notification(..., notification_type='DANGER', target_roles=['ADMIN','DIRECTION'])` —
deux paramètres qui n'existent pas dans la signature réelle de
`core.utils.create_notification(title, message, severity='INFO', node_origin='CLOUD')`. Résultat :
chaque détection RÉELLE de falsification faisait planter l'endpoint avec un `TypeError` avant de
répondre, empêchant précisément l'alerte ADMIN/DIRECTION voulue par CLAUDE.md §6. Corrigé en
`severity='DANGER', node_origin=node.code`. Je n'ai pas ajouté de ciblage par rôle
(`target_roles` n'existe pas dans `create_notification`, qui notifie aujourd'hui tout le monde,
comme ailleurs dans `treasury`/`sales`) : l'ajouter est une vraie fonctionnalité qui dépasse
BUG-001/002/003 — **signalé au coordinateur plutôt que tranché seul**.

### BUG-002 — Verrou anti-fourche
- `backend/treasury/views.py::append_cashbook_entry(validate_balance=None, **entry_kwargs)` :
  point d'entrée UNIQUE pour ajouter un bloc au Livre de Caisse. Lit `_get_last_balance()` sous
  `select_for_update()` dans un `transaction.atomic()`, calcule le solde/hash, enregistre ; retente
  automatiquement (jusqu'à 25 fois) sur `IntegrityError` (collision `previous_hash`) ou
  `OperationalError` (« database is locked » sous SQLite), en relisant le dernier solde à chaque
  tentative. `push_to_cashbook` (clôture) et `DisbursementVoucherViewSet.perform_create` (bordereau
  de versement) — **les deux seuls points d'écriture au Livre de Caisse** — appellent désormais
  cette fonction unique au lieu de dupliquer chacun la logique lecture/écriture.
- `backend/treasury/models.py` : `CashbookEntry.previous_hash` passe à `unique=True`.

**Choix technique à signaler explicitement** : `select_for_update()` seul ne suffit pas sous
SQLite — Django l'accepte sans erreur mais SQLite ne supporte pas le verrouillage de ligne, donc en
dev/desktop il n'empêche pas deux transactions concurrentes de lire la même « dernière écriture »
avant que l'une des deux n'ait validé. La garantie réelle anti-fourche, portable entre SQLite (dev/
desktop) et PostgreSQL (cloud), est la **contrainte d'unicité en base** sur `previous_hash` : deux
écritures qui chaîneraient sur le même parent ne peuvent physiquement pas coexister, la seconde
insertion échoue et `append_cashbook_entry` la retente avec le nouveau dernier solde. `select_for_update()` reste en
place et devient pleinement actif (verrouillage de ligne réel) une fois le projet déployé sur
PostgreSQL, réduisant alors la fréquence des collisions/retentatives.

### BUG-003 — Hash élargi + migration de données
- `compute_cashbook_entry_hash` couvre désormais : `id`, `node` (id FK), `date`, `piece_number`,
  `imputation`, `label`, `entry_amount`, `exit_amount`, `running_balance`, `source_closure` (id),
  **`source_bordereau`** (id) et `previous_hash`.
  `source_bordereau` n'était pas explicitement listé dans le ticket, mais couvre exactement la même
  catégorie de risque que `source_closure` (une sortie de caisse Direction pourrait sinon être
  réattribuée à un autre bordereau sans casser la chaîne) — ajouté par cohérence ; à ouvrir en
  ticket séparé si le testeur préfère le tracer individuellement.
- **Décision sur les écritures existantes (demandée explicitement, non tranchée silencieusement)** :
  `backend/treasury/migrations/0007_recompute_cashbook_hash.py` (réversible) ne recalcule PAS à
  l'aveugle. Elle :
  1. Revérifie la chaîne existante avec l'**ancienne** formule réellement utilisée à l'écriture
     avant cette correction (`compute_legacy_v1_hash`, qui reproduit l'ancien
     `treasury/views.py::_compute_hash` — **pas** l'ancienne formule de `blockchain`, qui n'a
     jamais servi à écrire un hash, seulement à vérifier, et n'est donc pas la référence
     pertinente pour auditer les données déjà en base).
  2. Recalcule la nouvelle formule uniquement pour le préfixe d'écritures validé à l'étape 1.
  3. Dès la première rupture détectée sous l'ancienne formule, arrête le recalcul : cette écriture
     et toutes les suivantes restent **« hash legacy, non vérifiable rétroactivement »**
     (inchangées), plutôt que d'écraser silencieusement une preuve de falsification réelle déjà
     présente avant la migration. Un `run_check` lancé après la migration les détectera
     explicitement comme falsifiées.
  - Justification du choix (recalculer plutôt que tout documenter comme legacy) : vérifié
    directement en SQL que `backend/db.sqlite3` contenait **0 `CashbookEntry`** au moment de cette
    migration (`select count(*) from treasury_cashbookentry` → 0) — recalculer ne masque donc
    aucune falsification réelle dans cet environnement. Le mécanisme de détection/arrêt est
    néanmoins écrit pour se comporter correctement si une autre base (environnement d'un autre
    agent, ou futur import) contenait déjà des écritures, falsifiées ou non.
  - `revert_to_legacy_hash` (fonction reverse de la migration) ne restaure que le préfixe que la
    migration forward a effectivement modifié (déterminé en revérifiant quelles écritures valident
    sous la NOUVELLE formule depuis le génésis), laissant intact tout ce qui était déjà « legacy ».
- `backend/treasury/migrations/0008_cashbookentry_previous_hash_unique.py` (schéma, après 0007
  pour ne jamais se heurter à un doublon préexistant) : applique `unique=True` sur `previous_hash`
  (BUG-002).

## Fichiers modifiés / ajoutés

- `backend/treasury/hashing.py` (nouveau)
- `backend/treasury/views.py` (hash unifié, `append_cashbook_entry`, `_get_last_balance` verrouillée,
  `push_to_cashbook` et `DisbursementVoucherViewSet.perform_create` réécrits pour utiliser
  `append_cashbook_entry`, `integrity_check` réécrit, `final_report` adapté pour appeler
  `_get_last_balance` dans un `transaction.atomic()` explicite)
- `backend/treasury/models.py` (`CashbookEntry.previous_hash` → `unique=True`, commentaire)
- `backend/treasury/migrations/0007_recompute_cashbook_hash.py` (nouveau, données, réversible)
- `backend/treasury/migrations/0008_cashbookentry_previous_hash_unique.py` (nouveau, schéma)
- `backend/blockchain/views.py` (hash/boucle unifiés, chaîne globale vérifiée une fois puis
  ventilée par nœud, correction de l'appel `create_notification`)
- `backend/treasury/tests/__init__.py`, `backend/treasury/tests/test_ledger.py` (nouveau — et
  suppression de l'ancien `backend/treasury/tests.py` vide, devenu un conflit avec le package
  `tests/`)
- `backend/blockchain/tests/__init__.py`, `backend/blockchain/tests/test_integrity.py` (nouveau,
  idem suppression de l'ancien `backend/blockchain/tests.py` vide)
- `docs/qa/REGISTRE_BUGS.md` (BUG-001/002/003 → `CORRIGÉ`, fiches détaillées)

## Tests ajoutés (tous échouaient avant correction, passent après)

`backend/treasury/tests/test_ledger.py` :
- `CashbookChainTests::test_chain_of_50_entries_is_valid` — chaîne de 50 écritures, intacte.
- `CashbookChainTests::test_tampering_an_amount_is_detected_at_the_right_entry` — `.update()`
  direct en base sur un montant → détecté exactement à partir de cette écriture.
- `CashbookChainTests::test_imputation_node_and_source_closure_are_covered_by_la_hash` — BUG-003 :
  falsification de `imputation` puis `node` directement en base → détectée.
- `CashbookChainTests::test_deleting_an_entry_breaks_the_chain` — suppression d'une écriture →
  détectée (les écritures avant restent valides, celle qui chaînait sur le hash supprimé et toutes
  les suivantes sont signalées).
- `CashbookChainTests::test_treasury_and_blockchain_agree_on_a_healthy_chain` — l'objectif même du
  ticket : une chaîne écrite via `treasury.views.append_cashbook_entry` est validée par
  `blockchain.views._verify_chain_for_node` sans fausse alerte.
- `CashbookHashFunctionTests::test_compute_cashbook_entry_hash_is_deterministic`
- `CashbookHashFunctionTests::test_treasury_write_hash_matches_blockchain_verification_hash` — le
  hash écrit côté treasury est identique au hash recalculé côté vérification (même fonction).
- `ConcurrentAppendTests::test_concurrent_appends_do_not_fork_the_chain` (`TransactionTestCase`,
  8 threads, chacun avec sa propre connexion DB fermée en fin de thread) — aucune erreur, aucun
  `previous_hash` dupliqué, chaîne entièrement valide, solde final exact.

`backend/blockchain/tests/test_integrity.py` :
- `RunCheckIntegrationTests::test_healthy_chain_across_two_nodes_is_not_flagged_as_tampered` —
  appel réel à `POST /api/blockchain/snapshots/run_check/` sur une chaîne saine répartie sur 2
  nœuds → `all_intact=True`, 0 `TamperAlert`, 0 `CashbookEntry.is_tampered`.
- `RunCheckIntegrationTests::test_tampered_entry_is_flagged_and_raises_an_alert` — falsification
  directe en base → `TamperAlert` créée, écritures affectées marquées `is_tampered`, écritures
  antérieures non affectées, **sans lever d'exception** (ce test est celui qui a révélé le bug
  `create_notification` ci-dessus).

Résultat : `python manage.py test` → **10/10 OK** (ce sont actuellement les seuls tests
automatisés du projet — BUG-008 reste ouvert pour le reste, hors de mon périmètre).

## Vérifications finales

- `python manage.py check` → 0 problème.
- `python manage.py test` → 10 tests, OK.
- `python manage.py makemigrations --check --dry-run` → affiche uniquement le drift
  pré-existant déjà signalé par `nettoyeur-securite` sur `production`/`clients`/`treasury`
  (`dailysavings`/`journalentry`, sans rapport avec `CashbookEntry`) — **aucune nouvelle dérive**
  introduite par ce travail.
- `npm run build` : non applicable, aucun fichier frontend touché (périmètre strictement backend
  trésorerie/blockchain, conformément aux consignes).

## Démonstration manuelle dans `backend/db.sqlite3` (règle §0.1 du plan)

Pour que le client puisse constater le résultat via `/admin/` (modèle `CashbookEntry` déjà
enregistré dans `backend/treasury/admin.py`) :
1. `python manage.py migrate` exécuté sur la vraie base (`backend/db.sqlite3`) — a appliqué
   0007/0008 sans effet car la base contenait 0 `CashbookEntry` au préalable (vérifié par SQL
   direct avant toute action).
2. Créé 3 écritures **réelles et laissées en base**, nœud `K1 (TABORA)`, préfixe
   `DEMO-INGBLOCKCHAIN-00/01/02`, libellé « DEMO ingenieur-blockchain — démonstration chaîne
   saine #n », 1000 FC chacune, via `append_cashbook_entry` (pas de `transaction.atomic()` suivi
   d'un rollback — écriture réelle et persistante).
3. Vérifié avec `blockchain.views._verify_chain_for_node(node_K1)` sur la vraie base :
   `{'total_entries': 3, 'tampered_count': 0, 'is_intact': True}` — confirme en conditions réelles
   que le but du ticket est atteint.
4. **Laissé en base** à la discrétion du coordinateur pour revue (préfixe `DEMO-INGBLOCKCHAIN`
   clairement identifiable comme fictif, nœud K1 réel mais montants/libellés inventés) — à
   nettoyer ou conserver selon ce que le coordinateur juge utile pour la suite de la recette.

## Points nécessitant validation humaine / signalés au coordinateur

1. **Ciblage par rôle des notifications** (`target_roles` dans l'appel cassé de `run_check`) :
   `create_notification` ne sait pas aujourd'hui cibler ADMIN/DIRECTION spécifiquement (notifie
   tout le monde, comme partout ailleurs dans le code). Corriger juste l'appel pour qu'il ne
   plante plus était nécessaire à ce ticket ; ajouter un vrai ciblage par rôle est une
   fonctionnalité à part, non traitée ici.
2. **Champ `source_bordereau` ajouté au hash** en plus des trois champs explicitement listés dans
   BUG-003 (`node`, `imputation`, `source_closure`) — décision assumée et justifiée ci-dessus, mais
   signalée pour que le coordinateur/testeur sache que le périmètre a été légèrement élargi par
   cohérence et pas par erreur.
3. **Confirmation du modèle "simulation de blockchain via hash chaîné en base"** reçue en cours de
   tâche et déjà respectée sans aucune modification nécessaire (voir section dédiée ci-dessus) —
   documentée ici pour traçabilité.
4. **Architecture de la chaîne "globale" vs "par nœud"** : j'ai choisi de conserver le modèle
   existant d'une chaîne UNIQUE globale (tel qu'il ressort de `_get_last_balance()`/
   `append_cashbook_entry`, qui n'ont jamais filtré par nœud) et d'adapter la vérification pour s'y
   conformer, plutôt que l'inverse (créer une chaîne séparée par nœud, ce qui aurait été un
   changement de schéma plus lourd et hors du périmètre strict BUG-001/002/003). À confirmer avec
   le client/coordinateur si le modèle attendu était en réalité "une chaîne par boulangerie" —
   aucune indication contraire trouvée dans CLAUDE.md §5.5 ou cahierDesCharges.md, qui décrivent un
   livre de caisse Direction unique.

## Hors périmètre, non traité (rappel)

- Drapeau `Node.is_locked` / blocage des écritures d'un nœud compromis (évoqué dans une version
  plus large de la mission initiale, mais absent du périmètre BUG-001/002/003 confirmé par le plan
  du coordinateur) — non implémenté, à discuter si souhaité pour une itération ultérieure.
- Ancrage externe quotidien (empreinte de tête de chaîne exportée/imprimée) — idem, hors périmètre
  confirmé, et de toute façon à concevoir en cohérence avec la contrainte d'hébergement mutualisé
  rappelée par le client.
- BUG-004 (sync), BUG-005/006/007/009/010 (déjà `CORRIGÉ` par `nettoyeur-securite`), BUG-008 (pas
  de tests pour le reste du projet), BUG-012..016 (audits `remarque.md`) : non touchés.
