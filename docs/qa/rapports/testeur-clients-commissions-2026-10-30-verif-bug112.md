# Rapport — Vérification indépendante de BUG-112 (testeur-clients-commissions, 2026-10-30)

## Contexte

Le coordinateur demande une vérification indépendante de BUG-112
(`database table is locked` sous forte concurrence réelle de création de clients, SQLite),
corrigé par dev-backend le 2026-10-30. Je suis l'ouvreur historique du test de concurrence
sous-jacent (BUG-017,
`clients/tests/test_verification_2026_10_22.py::BUG017RealConcurrencyStrictAssertionTests`),
d'où cette vérification confiée à mon rôle plutôt qu'à un autre agent.

Rappel de la règle (CLAUDE.md §7) : je n'ai modifié aucun code applicatif. Seules des lectures,
des exécutions de tests existants, et la mise à jour du registre (table + fiche détaillée) ont
été faites.

## 1. Relecture complète du diff

### `backend/kiese/settings.py` (~l.112-168)

- `_DB_ENGINE = os.environ.get('DB_ENGINE') or 'django.db.backends.sqlite3'` lu une seule fois.
- `DATABASES['default']['OPTIONS'] = {'timeout': 30}` et le branchement du signal
  `connection_created` (PRAGMA `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=30000`) sont
  strictement à l'intérieur de `if _DB_ENGINE == 'django.db.backends.sqlite3':`. Confirmé par
  lecture directe : une configuration PostgreSQL (`DB_ENGINE=django.db.backends.postgresql`) ne
  reçoit ni `OPTIONS`, ni le signal — condition exacte, pas d'effet de bord sur le moteur de
  production Linux.
- Le récepteur vérifie lui-même `connection.vendor != 'sqlite'` avant d'exécuter les `PRAGMA`
  (double garde).

### `backend/clients/models.py::Client.save()`

- Boucle de retry toujours bornée à `_CODE_GENERATION_MAX_RETRIES = 10` (inchangé).
- Capture désormais `IntegrityError` (déjà existant, BUG-017) **et** `OperationalError`, mais pour
  cette dernière uniquement si `'locked' in str(exc).lower()` — sinon `raise` immédiat. Vérifié :
  aucune autre `OperationalError` (ex. erreur de schéma, colonne manquante) n'est avalée
  silencieusement.
- Avant de retenter : `self.code = ''` (comme pour `IntegrityError`) puis
  `time.sleep(random.uniform(0.01, 0.05))` (petit backoff aléatoire, même style que
  `treasury/views.py::append_cashbook_entry`, confirmé par lecture croisée des deux fichiers).
- **Unicité stricte inchangée** : `_generate_client_code` réserve toujours le numéro sous
  `select_for_update()` + `transaction.atomic()`, avec la boucle
  `while Client.objects.filter(code=code).exists(): ...` intacte. Le retry ne fait que relancer
  tout le bloc (génération + sauvegarde) depuis zéro après un échec transitoire de verrou — aucune
  fenêtre ne permet à deux threads d'obtenir le même code.

## 2. Test de concurrence relancé isolément 8 fois

`backend/.venv/Scripts/python.exe manage.py test clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests.test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db`

Aucun autre processus Python actif en parallèle (vérifié par `ps aux` avant le premier run).

| Run | Résultat |
|---|---|
| 1 | OK |
| 2 | OK |
| 3 | OK |
| 4 | OK |
| 5 | OK |
| 6 | OK |
| 7 | OK |
| 8 | OK |

**8/8 (100 %)**. Les trois assertions du test (majorité de créations réussies sur 16 threads,
unicité des codes en mémoire, unicité relue en base) passent systématiquement.

## 3. Logique d'unicité re-vérifiée

Confirmé (voir §1) : le verrou `select_for_update()` sur `ClientCodeSequence` reste la seule
source de vérité pour la réservation du numéro ; le nouveau retry/backoff ne touche qu'à la
gestion de l'erreur transitoire SQLite, jamais à la logique d'unicité elle-même. Aucune collision
de code n'est possible, avec ou sans le nouveau backoff.

## 4. Suite complète en isolation stricte

`backend/.venv/Scripts/python.exe manage.py test` (aucun autre agent/processus actif avant et
pendant, vérifié par `ps aux`) :

```
Ran 377 tests in 914.564s
OK
```

0 échec, 0 erreur. Aucune `OperationalError` / « database is locked » dans la sortie complète.

## 5. Impact du mode WAL sur `backend/kiese/settings_desktop.py`

Lu intégralement, non modifié par dev-backend. `settings_desktop.py` fait
`from .settings import *`, ce qui exécute déjà le bloc sqlite de `settings.py` et connecte son
récepteur (`busy_timeout=30000`) au signal `connection_created`. `settings_desktop.py` définit
ensuite **sa propre** fonction `_set_sqlite_pragmas` (même nom, portée différente) et la connecte
**une seconde fois** au même signal, avec `busy_timeout=5000` et son propre `OPTIONS['timeout']: 20`
(inchangés, pré-existants).

Point précis que je corrige par rapport à la formulation « sans effet nuisible » du rapport
dev-backend : les deux récepteurs sont bien **deux objets distincts** connectés au signal (Django
ne les déduplique pas, il n'écrase rien) — ils s'exécutent donc **tous les deux**, dans l'ordre de
connexion (celui de `settings.py` d'abord, puis celui de `settings_desktop.py`). Le `PRAGMA
busy_timeout` de `settings_desktop.py` (5000) est donc le **dernier appliqué** et c'est lui qui
reste actif pour chaque connexion desktop — pas 30000. Il n'y a cependant pas de régression : ce
comportement (`busy_timeout=5000`, `OPTIONS['timeout']=20`) est **exactement celui d'avant ce
ticket** pour le poste desktop, qui n'était pas dans le périmètre du correctif BUG-112. La seule
conséquence est que le relèvement à 30 s fait pour le mode cloud/dev ne bénéficie pas (encore) au
poste desktop — ni amélioration, ni dégradation involontaire. Signalé ici pour information au
coordinateur / `architecte-sync` (harmonisation éventuelle hors du périmètre d'un testeur, qui ne
modifie jamais le code applicatif).

## 6. Point annexe `sync/authentication.py` (BUG-062, informatif)

Non reproduit dans mes propres runs : aucun log d'épuisement de
`_AUTH_WRITE_MAX_RETRIES = 150` (`sync/models.py::NodeAuthToken`), aucun test `sync` en échec dans
la suite complète (377/377 OK). Le mécanisme concerné est indépendant de la correction BUG-112
(retry propre à la mise à jour de `last_used_at` sur l'authentification de nœud, pas à
`Client.save()`). Aucun nouveau ticket ouvert — purement informatif, conforme à la consigne.

## 7. Vérifications complémentaires

- `makemigrations --check --dry-run` → `No changes detected`.
- `PRAGMA integrity_check` sur `backend/db.sqlite3` → `[('ok',)]`.

## Conclusion

BUG-112 est conforme à la description de la correction, reproductible comme corrigé (8/8 sur le
test ciblé, 377/377 sur la suite complète), sans aucune faiblesse d'unicité introduite et sans
impact sur le moteur PostgreSQL de production. Ticket passé de `CORRIGÉ` à `VÉRIFIÉ` dans
`docs/qa/REGISTRE_BUGS.md` (table ligne BUG-112 + fiche détaillée, section « Vérification »
ajoutée).

Seul point à signaler au coordinateur (non bloquant, non régressif) : le mode WAL/`busy_timeout`
relevé à 30 s dans `settings.py` est en pratique neutralisé pour le poste desktop par la
redéfinition/reconnexion du même signal dans `settings_desktop.py` (`busy_timeout` y reste à
5000 ms, comportement inchangé depuis avant ce ticket) — à considérer pour une harmonisation
future si le poste desktop rencontre un jour le même type de contention sous charge réelle.
