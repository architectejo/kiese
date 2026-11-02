# Rapport — testeur-charge — 2026-10-22/23

Mission : charge et résilience, focalisée sur BUG-004 (sync V1, périmètre
partiel) — concurrence réaliste, scénario de synchronisation multi-nœuds,
coupures/reprise, volumétrie. Référence : `docs/qa/PLAN_2026-10-22.md`,
`docs/architecture/SYNC.md`, CLAUDE.md §5.

## 0. Incident en cours de mission — db.sqlite3 touché puis restauré

En débogant manuellement une anomalie du serializer de factures (voir
BUG-063), une commande `python manage.py shell -c "..."` a été lancée
**sans isolation**, directement contre les vrais settings (pas de base
temporaire) — ce qui a écrit dans `backend/db.sqlite3` réel : un nœud
`ZZZ`, un utilisateur `test_facturier_X`, un client fictif « Testeur
Client1 ». Repéré immédiatement (l'erreur obtenue, `IntegrityError`
inattendue, a déclenché une vérification). Actions prises :
1. Vérifié l'étendue exacte de l'écriture (`Node.objects.filter(code='ZZZ')`
   → 1 nœud, 1 client, 1 utilisateur rattachés, 0 facture).
2. Supprimé précisément ces trois objets (dans l'ordre : factures [aucune],
   client, utilisateur, nœud).
3. **Confirmé la restauration** : comparaison avant/après de la liste des
   16 nœuds (identique), de la liste des `BreadPrice` (identique — le seul
   `get_or_create` fait par le débogage a réutilisé une ligne déjà
   existante, rien créé), et recherche explicite de toute trace résiduelle
   de mes propres artefacts (`Node.objects.filter(code__startswith='ZZZ')`,
   `User.objects.filter(username__icontains='charge')`,
   `Client.objects.filter(first_name__icontains='ClientCharge')`) — tous à
   zéro. Les 2 clients « Testeur » encore présents en base (nœuds
   `YY4517`/`ZZ4517`, datés du 2026-10-22 12:04) sont antérieurs à mon
   intervention (ma propre session n'a commencé qu'en fin de journée, mon
   premier incident est daté 22:55) : ils appartiennent à un autre agent,
   pas à moi.
4. Le nombre total de clients a varié entre mes deux relevés (684 puis
   688) : c'est attendu dans cet environnement **partagé en continu par
   plusieurs agents actifs en parallèle** (confirmé par l'apparition de
   tickets BUG-058/059/060/061 d'autres agents pendant ma propre session) —
   pas un signe de pollution de ma part, déjà exclu par le point 3.
5. **Correctif appliqué immédiatement après l'incident** : toute
   exploration manuelle suivante s'est faite exclusivement via
   `manage.py test` avec des fichiers de test temporaires (créés puis
   supprimés), jamais plus `manage.py shell` nu. Le script de volumétrie
   final (`scripts/charge/volumetrie.py`) inclut un garde-fou explicite qui
   arrête le script si la connexion par défaut ne pointe pas vers sa base
   temporaire (voir `scripts/charge/README.md` pour le détail technique —
   la cause était `load_dotenv(..., override=True)` dans `settings.py` qui
   écrasait silencieusement la variable d'environnement positionnée avant
   `django.setup()`).

**Confirmation explicite demandée par le coordinateur** : oui, `backend/db.sqlite3`
est bien restauré à l'identique pour tout ce qui concerne mon intervention —
aucune trace résiduelle de mes propres écritures accidentelles. Toute la
suite de la mission (ci-dessous) s'est déroulée en isolation stricte,
jamais contre la vraie base.

## 1. Règle transversale db.sqlite3 (plan §0.1) — application à ce testeur

Mes scripts de charge créent des volumes de données par nature non
« démonstratifs » (24 000 factures fictives, etc.) — hors du cas d'usage
§0.1 (vérifications ponctuelles visibles par le client). J'ai donc choisi :
- `scripts/charge/volumetrie.py` : base SQLite **temporaire dédiée**,
  distincte de `db.sqlite3`, créée et détruite à chaque exécution, avec
  garde-fou d'arrêt si l'isolation n'est pas confirmée.
- Scénarios de concurrence/synchronisation : suites `manage.py test`
  standard (`backend/sales/tests/test_charge_morning_peak.py`,
  `backend/sync/tests/test_charge_sync_volume.py`), qui bénéficient déjà de
  l'isolation automatique de Django (base de test éphémère détruite en fin
  de run) — jamais de route vers `db.sqlite3`.

## 2. Concurrence réaliste — résultats

### 2.1 Code client (BUG-017) — déjà VÉRIFIÉ, non retesté en profondeur
`testeur-clients-commissions` a déjà vérifié ce point avec 16 threads réels
et une assertion stricte d'unicité (voir `docs/qa/REGISTRE_BUGS.md`,
BUG-017, statut VÉRIFIÉ). Je n'ai pas dupliqué ce travail.

### 2.2 Numéro de reçu (signalé comme risque théorique par SYNC.md §10) — **confirmé réel, mais masqué par un problème plus grave**
En essayant de reproduire la collision de `receipt_number` sous charge
réelle (`backend/sales/tests/test_charge_morning_peak.py`), j'ai découvert
que la collision elle-même n'est presque jamais le premier symptôme
observable : **dès 2 facturiers strictement simultanés, les deux requêtes
échouent systématiquement avec `OperationalError: database table is
locked`**, avant même d'atteindre le point où deux numéros identiques
pourraient être committés avec succès. J'ai ouvert **BUG-062** pour ce
problème plus sévère (aucune retentative sur `OperationalError`, alors que
`append_cashbook_entry`/BUG-002 et `_generate_client_code`/BUG-017 en ont
une) — le risque théorique de numéro de reçu dupliqué (SYNC.md §10) reste
documenté dans ce même ticket comme second effet, à retester une fois
BUG-062 corrigé (avec une vraie retentative, deux écritures concurrentes
auront enfin l'occasion de toutes les deux réussir, et c'est à ce
moment-là que la collision de `_make_receipt_number` — lecture non
verrouillée de `count()+1` — redeviendra observable et vérifiable).

### 2.3 Chaîne de hash du Livre de Caisse (BUG-002) — déjà VÉRIFIÉ par ingenieur-blockchain
Non retesté (hors périmètre : la V1 de sync ne pousse jamais de
`CashbookEntry` depuis un nœud local, SYNC.md §0 — le seul écrivain reste
le Cloud lui-même, déjà couvert).

### 2.4 Découverte incidente : type mismatch sur `bread_price` (BUG-063)
En diagnostiquant pourquoi mon scénario de pic du matin échouait avec
« BreadPrice introuvable » alors que le `BreadPrice` existait bel et bien,
j'ai isolé un bug de comparaison de types indépendant de toute
concurrence : `InvoiceViewSet.create` compare des identifiants bruts non
typés (`bp_ids`, potentiellement des chaînes JSON) à des clés `int`
(`bp.pk`) sans normalisation — `'1' not in {1: ...}` est vrai en Python.
Documenté sous **BUG-063** (Mineur — probablement dormant si le frontend
actuel envoie déjà des nombres, mais bloquant pour tout futur client HTTP
qui sérialiserait les identifiants en chaîne).

## 3. Scénario de synchronisation réaliste — allé plus loin que `sync/tests/test_sync.py`

`backend/sync/tests/test_charge_sync_volume.py` :
- **`ManyNodesOutOfOrderVolumeTests`** : 4 nœuds (pas 2), 5 mouvements de
  dette chacun (pas 1), ordre d'arrivée **vraiment aléatoire** (`random.shuffle`,
  rejoué sur deux tirages indépendants) — la dette consolidée au Cloud est
  la somme exacte (confirmé), et le nombre de `DebtMovement` en base est
  exactement `N_NODES × MOVEMENTS_PER_NODE` (aucun perdu, aucun dupliqué).
  **PASSE** — la logique de recalcul par somme (SYNC.md §2.2) tient à cette
  échelle élargie.
- **`ConcurrentRapidReplayTests.test_rapid_sequential_replay_hundred_times_stays_idempotent`** :
  100 rejeux séquentiels rapides du même `batch_id` → toujours un seul
  `DebtMovement`, dette correcte. **PASSE**.
- **`ConcurrentRapidReplayTests.test_replaying_the_same_batch_id_concurrently_many_times_never_duplicates`** :
  10 rejeux **vraiment concurrents** (vrais threads) du même `batch_id` →
  échec systématique, mais pas où on l'attendrait : l'échec survient dans
  `NodeAuthToken.authenticate()` (mise à jour non protégée de
  `last_used_at`), **avant** d'atteindre la logique métier déjà protégée
  (`sync.services.apply_debt_movement`, qui a sa propre retentative
  `_WRITE_MAX_RETRIES=25`). Même cause racine que BUG-062, documentée dans
  le même ticket. Marqué `@expectedFailure` en attendant correction.

## 4. Coupures et reprise

Le scénario de coupure au milieu d'un lot est déjà testé par
`architecte-sync` (`sync/tests/test_sync.py`) et prouvé idempotent pour un
rejeu isolé. Mon apport : le rejeu **répété et rapide** (100× séquentiel,
10× concurrent) ci-dessus, demandé explicitement par la mission — confirme
l'idempotence applicative pour la partie métier, mais révèle que
l'authentification de nœud elle-même (couche transverse à toute requête
`/api/sync/*`) n'a pas la même robustesse (BUG-062).

Je n'ai pas pu tester une coupure réseau réelle entre backend desktop et
Cloud (SYNC.md §9) : aucun poste desktop n'existe encore (`packaging-desktop`
n'a pas démarré) — confirmé hors périmètre actuel, pas un oubli. Les
scénarios « deux nœuds » restent, comme documenté dans BUG-004, prouvés via
l'API `/api/sync/push/` avec des jetons de nœud différents contre la même
base, pas via un vrai réseau séparé.

## 5. SQLite vs PostgreSQL

Les deux anomalies ci-dessus (BUG-062 particulièrement) sont une
démonstration directe et chiffrée de pourquoi ce choix de moteur compte :
**2 écritures strictement simultanées suffisent à faire échouer les deux**
sous SQLite, sans aucune erreur applicative propre (juste une exception
non rattrapée). Recommandation, cohérente avec CLAUDE.md §8 :
- **Cloud (serveur de production, Gunicorn+Nginx)** : PostgreSQL. Élimine
  structurellement ce mode de défaillance (verrouillage au niveau ligne,
  pas de verrou fichier mono-écrivain). Le volume réel visé (~876 000
  factures/an, 8 boulangeries) ne pose aucune difficulté à PostgreSQL.
- **Nœud local desktop (Electron + Waitress)** : SQLite en mode WAL reste
  le bon choix (CLAUDE.md §8 — un seul poste par boulangerie, 1-2
  facturiers), **mais** le risque résiduel de 2 écritures simultanées sur
  le même poste reste réel et justifie quand même d'ajouter une
  retentative applicative (BUG-062) indépendamment du moteur cible — le
  mode WAL réduit la contention en lecture/écriture mais ne supprime pas
  le besoin d'une retentative applicative sur écriture concurrente.
- Je n'ai pas eu accès à une instance PostgreSQL dans cet environnement
  pour mesurer un contraste chiffré direct (aucune installation disponible,
  hors périmètre de provisionner une base — à refaire par `dev-backend`/
  `packaging-desktop` lors du choix définitif d'infrastructure cloud).

## 6. Poste modeste (profil réseau/CPU ralenti)

**Non traité** dans cette itération — aucune page POS front-end stabilisée
spécifiquement pour ce test au moment de la mission (le scénario Playwright
3G/CPU ralenti suppose un périmètre e2e déjà vert, relevant plutôt de
`testeur-e2e`/`testeur-materiel`, qui ont des tickets frontend encore
`OUVERT` en cours — BUG-059/060/061 par exemple). Signalé au coordinateur
plutôt que improvisé hors mandat.

## 7. Volumétrie

Voir `backend/scripts/charge/volumetrie.py` et son `README.md` pour la
méthode complète. Résumé des mesures (médiane sur 5 appels à chaud,
volume : 8 nœuds, 696 clients, 24 000 factures/47 901 lignes sur 10 jours
simulés à 300 factures/jour/nœud — représentatif d'environ **1 mois**
d'exercice réel, pas l'année complète pour des raisons de temps
d'exécution, voir justification dans le script) :

| Endpoint | Médiane | Requêtes SQL | Verdict (<500ms) |
|---|---|---|---|
| Recherche client (nom partiel) | 56,8 ms | 3 | OK |
| Liste factures filtrée nœud+jour | 90,7 ms | 6 | OK |
| Liste factures NON filtrée (page 1) | 435,1 ms | 5 | OK (proche de la limite) |
| Commissions `summary()` | 9,1 ms | 2 | OK |
| **Finance `comparative()` (N/N-1)** | **1 206,2 ms** | **32** | **DÉPASSE** |
| Production `reconciliation()` | 22,8 ms | 7 | OK |
| Livre de Caisse (liste) | 27,8 ms | 3 | OK |

Aucun N+1 classique détecté (nombre de requêtes constant, indépendant du
volume de données retournées — le code lu utilise déjà largement
`select_related`/`prefetch_related`, y compris dans `finance/views.py::doc1_report`,
`clients/views.py`, `treasury/views.py`, `production/views.py`). Le
problème identifié est différent : des agrégats corrects mais **sans
index** sur les colonnes de date/statut filtrées, dont le coût croît avec
le volume TOTAL en base plutôt qu'avec la page affichée. Documenté sous
**BUG-064** (Majeur), avec recommandation d'index composites.

Anomalie isolée non retenue comme preuve : un des 10 jours simulés a pris
~16 minutes contre ~20 secondes pour les 9 autres pendant le seed (détail
dans le script/README) — non réinvestiguée (coût de reproduction trop
élevé pour ce budget de mission), probablement un facteur externe
(antivirus/indexation sur le fichier temporaire) plutôt qu'un comportement
applicatif.

## 8. Tickets ouverts

- **BUG-062** (Majeur) — Aucune retentative sur `OperationalError` pour
  `InvoiceViewSet.create` (sales) ni `NodeAuthToken.authenticate()` (sync) —
  échec systématique dès 2 écritures concurrentes sous SQLite.
- **BUG-063** (Mineur) — Type mismatch `str`/`int` sur les PK de
  `BreadPrice` dans `InvoiceViewSet.create`, découvert incidemment.
- **BUG-064** (Majeur) — Absence d'index sur `Invoice`/équivalents : liste
  non filtrée et états financiers dépassent déjà l'objectif de 500 ms à un
  volume représentatif modeste (~1 mois d'exercice réel).

Numérotation vérifiée au moment de l'écriture (le registre contenait déjà
BUG-001 à BUG-061, avec quelques doublons 056-058 entre deux agents ayant
travaillé en parallèle — mes tickets ont été numérotés 062-064 pour éviter
tout nouveau conflit).

## 9. Ce qui n'a pas pu être testé (périmètre hors de portée, documenté comme tel et non comme bug)

- Production/dépenses/caisse sociale non câblées dans `sync.services.PUSH_HANDLERS`
  (confirmé dans BUG-004 comme périmètre V1 volontairement limité) — pas
  testées en synchronisation, seulement en volumétrie côté lecture.
- Pas de vrai second poste/réseau séparé (desktop) — scénarios « deux
  nœuds » strictement logiciels (même base, jetons différents), comme déjà
  documenté par `architecte-sync`.
- Pas d'instance PostgreSQL disponible pour une mesure comparative directe.
- Scénario « poste modeste » (3G/CPU ralenti, Playwright) non traité —
  signalé au coordinateur, relève plutôt de `testeur-e2e`/`testeur-materiel`.

## 10. Fichiers livrés

- `backend/scripts/charge/volumetrie.py` — script de mesure de volumétrie,
  base temporaire isolée, garde-fou anti-pollution de `db.sqlite3`.
- `backend/scripts/charge/README.md` — mode d'emploi + leçons tirées de
  l'incident §0.
- `backend/sales/tests/test_charge_morning_peak.py` — pic du matin
  multi-boulangeries (2 tests, 1 `@expectedFailure` → BUG-062).
- `backend/sync/tests/test_charge_sync_volume.py` — synchronisation
  multi-nœuds à plus grande échelle (4 tests, 1 `@expectedFailure` →
  BUG-062).
- `docs/qa/REGISTRE_BUGS.md` — BUG-062, BUG-063, BUG-064 ajoutés (tableau +
  fiches détaillées).

## 11. État de la suite de tests

`python manage.py test sales.tests.test_charge_morning_peak
sync.tests.test_charge_sync_volume` : **5/5 verts** (2 `@expectedFailure`
documentées).

`python manage.py test` (suite complète, 229 tests) : **3 échecs non liés à
mon travail**, confirmés pré-existants en reproduisant les mêmes tests avec
mes fichiers intégralement retirés du répertoire (voir reproduction
détaillée ci-dessous) :
- `clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests`
  — déjà documenté comme parfois flaky sous SQLite dans ce même
  environnement (voir note de `testeur-clients-commissions` dans le
  registre, BUG-017).
- `treasury.tests.test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario`
  et `treasury.tests.test_reports_closures.CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses`
  — échouent à l'identique SANS mes fichiers (`test_charge_morning_peak.py`/
  `test_charge_sync_volume.py` déplacés hors du répertoire puis les deux
  tests relancés seuls) ; piste la plus probable : changement de date
  système en cours de session (passage au 2026-10-23) affectant une
  logique dépendant de `date.today()` dans ces tests ou le code testé — à
  confirmer par `testeur-tresorerie`, hors de mon périmètre de correction.

Je n'ai pas touché `backend/treasury/` ni `backend/clients/tests/test_verification_2026_10_22.py` : signalé ici pour information du coordinateur, pas pris en charge (ce n'est pas mon module et je ne corrige pas le code applicatif).
