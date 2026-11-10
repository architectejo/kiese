# Rapport dev-backend — 2026-11-10 — BUG-144 (stock de pains par jour)

## Contexte

Demande client (remarque.md, ligne ajoutée après l.396) : pouvoir sélectionner
un jour dans « Production & Stocks » pour les sections « Stock Pains Actuel »
(à renommer « Stock Pains du Jour ») et « Historique des Fournées ».

Cette tâche couvre **uniquement le volet backend** (BUG-144). Le sélecteur de
date et le renommage côté UI font l'objet d'un ticket séparé **BUG-145**
(`dev-frontend`), qui pourra implémenter son côté sans deviner grâce au
contrat ci-dessous.

## Analyse

- `BreadStock` (`backend/production/models.py`) est un solde **courant**
  cumulatif par `(node, bread_price)` — une seule ligne, pas d'historique par
  jour. C'est ce que `GET /api/production/bread-stocks/` (`BreadStockViewSet`)
  renvoie aujourd'hui.
- `DailyBreadStockSnapshot` (déjà en place, BUG-118, déjà vérifié) capture
  **par équipe** (A/B) le solde déclaré à la clôture d'une session, pour
  `(node, bread_price, date, team)`. C'est la seule source d'historique par
  jour déjà disponible — pas de nouveau modèle nécessaire.
- « Historique des Fournées » (liste des `ProductionSession`) n'a nécessité
  **aucun changement backend** : `ProductionSessionViewSet.filterset_fields`
  inclut déjà `'date'` — le frontend (BUG-145) pourra directement appeler
  `GET /api/production/sessions/?date=AAAA-MM-JJ&node=...` (filtre déjà
  existant, isolation par nœud déjà en place dans `get_queryset()`).

## Décision d'architecture

Un **nouvel endpoint dédié**, en lecture seule, plutôt qu'une extension de
`BreadStockViewSet` — pour garantir une non-régression TOTALE et sans risque
du comportement existant (le ticket l'exige explicitement) : `BreadStockViewSet`
n'est pas touché d'un seul caractère. Le nouvel endpoint réutilise le même
`BreadStockSerializer`-like shape (mais en vue fonctionnelle `APIView`, pas un
`ViewSet`, car la source des données change radicalement selon la date
demandée — `BreadStock` vs agrégation de `DailyBreadStockSnapshot`).

## Contrat API (pour `dev-frontend`, BUG-145)

```
GET /api/production/bread-stocks/by-date/?node=<code ou pk>&date=<AAAA-MM-JJ>
```

- `date` est **optionnel** (défaut : aujourd'hui).
- `node` :
  - Non-HQ (GERANT/FACTURIER/etc., `not user.can_access_all_nodes`) : ignoré
    si fourni, remplacé par `user.node` — jamais d'accès à un autre nœud, même
    forgé dans la requête (même garde-fou que `DailyClosureReportView`,
    BUG-022/025/056/120).
  - HQ (ADMIN/DIRECTION/COMPTABLE/superuser) : **requis explicitement**, sinon
    `400 {"detail": "Le paramètre \`node\` (code ou identifiant) est requis."}`.
    Accepte le code boulangerie (`K1`, `B2`, insensible à la casse) ou la PK
    numérique.
- Permission : `IsAuthenticated` — identique à `BreadStockViewSet` (tous les
  rôles authentifiés peuvent lire, pas de restriction de rôle supplémentaire).

### Réponse — cas `date` omise ou égale à aujourd'hui (`source: "live"`)

Comportement **rigoureusement identique** à ce que renvoie aujourd'hui
`GET /api/production/bread-stocks/?node=<pk>` pour ce nœud (non-régression
vérifiée par test, voir plus bas) :

```json
{
  "node": 3,
  "node_display": "K1 — Boulangerie Tabora",
  "date": "2026-11-10",
  "source": "live",
  "categories": [
    {"bread_price": 7, "bread_price_display": "Pain 500 FC", "unit_price": 500, "qty_available": 120},
    {"bread_price": 8, "bread_price_display": "Pain 1000 FC", "unit_price": 1000, "qty_available": 40}
  ]
}
```

`qty_available` = `BreadStock.qty_available` courant (produit + reçu − envoyé
− disposé + ajusté). Seules les catégories ayant déjà une ligne `BreadStock`
pour ce nœud apparaissent (même liste que l'ancien endpoint).

### Réponse — cas `date` strictement dans le passé (`source: "snapshot"`)

```json
{
  "node": 3,
  "node_display": "K1 — Boulangerie Tabora",
  "date": "2026-11-05",
  "source": "snapshot",
  "categories": [
    {"bread_price": 7, "bread_price_display": "Pain 500 FC", "unit_price": 500, "qty_available": 55}
  ]
}
```

`qty_available` = somme de `DailyBreadStockSnapshot.qty_at_close` sur les
équipes A et B pour `(node, bread_price, date)`. Une équipe qui n'a pas de
ligne ce jour-là compte pour **0** (pas une absence de valeur — même
convention que le docstring de `DailyBreadStockSnapshot`, BUG-118/120/135).
Une catégorie sans AUCUNE ligne ce jour-là (ni A ni B n'ont clôturé)
**n'apparaît pas** dans `categories` (même convention que le cas « live », qui
ne liste que les catégories suivies). Le frontend (BUG-145) peut donc afficher
un badge « Historique » quand `source === "snapshot"`.

**Point d'attention signalé pour `dev-frontend`/le coordinateur (non bloquant,
CLAUDE.md §7 règle 6)** : si un jour donné n'a de ligne `DailyBreadStockSnapshot`
que pour UNE des deux équipes (l'autre n'ayant pas travaillé/clôturé ce
jour-là), l'endpoint renvoie quand même une valeur "complète" en apparence
(somme avec 0 pour l'équipe absente) — ce qui est la bonne valeur par défaut
déjà établie ailleurs dans le code, mais peut donner l'illusion d'un stock
« du jour entier » alors qu'une seule équipe a réellement clôturé. Le contrat
actuel ne distingue pas ce cas (pas de champ `teams_reporting` ou similaire) —
à envisager seulement si l'UI en a réellement besoin ; non implémenté ici pour
ne pas sur-ingénierer un contrat que personne n'a encore demandé.

### Cas `date` dans le futur

`400 {"detail": "La date demandée (2099-01-01) ne peut pas être dans le futur (aujourd'hui : 2026-11-10)."}`

Volontairement **sans** passer par `core.utils.validate_requested_date` : cet
utilitaire conditionne aussi le refus d'une date **passée** à
`Config.allow_backdated_sales`, une règle d'**écriture** (BUG-083) sans
rapport avec la simple **lecture** d'un historique déjà enregistré — un
gérant doit pouvoir consulter n'importe quel jour passé, que la saisie de
ventes passées soit activée ou non sur ce réglage. Seul le refus universel du
futur est repris (même esprit que BUG-128/`CalendarPicker.tsx`).

### Cas `date` invalide (mauvais format)

`400 {"detail": "Date invalide — format attendu AAAA-MM-JJ."}`

## « Historique des Fournées »

Aucun changement backend nécessaire : `GET /api/production/sessions/?date=AAAA-MM-JJ&node=<pk>`
fonctionne déjà (filtre `date` déjà dans `filterset_fields`, isolation par
nœud déjà dans `get_queryset()`). `dev-frontend` (BUG-145) peut l'utiliser
directement.

## Fichiers modifiés

- `backend/production/views.py` : ajout de `BreadStockByDateView` (nouvelle
  classe, juste avant `BreadDisposalViewSet`). `BreadStockViewSet` **non
  modifié**.
- `backend/production/urls.py` : ajout de la route littérale
  `bread-stocks/by-date/` (déclarée **avant** `include(router.urls)` pour ne
  jamais être capturée par la route détail `bread-stocks/<pk>/` du routeur
  DRF).
- `backend/production/tests/test_bug144_bread_stock_by_date.py` (nouveau
  fichier, 12 tests, écrits directement sans `@expectedFailure` puisque la
  correction était déjà en place au moment de l'écriture — vérifiés localement
  en commentant temporairement le bloc `source = 'snapshot'`/le filtre de date
  futur pour confirmer qu'ils échouaient bien avant, conformément à CLAUDE.md
  §7 règle 4) :
  - `BreadStockByDateLiveTests` : date omise, et date = aujourd'hui comparée
    ligne à ligne à l'ancien endpoint `GET /api/production/bread-stocks/`
    (non-régression explicite).
  - `BreadStockByDateSnapshotTests` : date passée avec une seule équipe
    (A seule → résultat = cette équipe, différent du solde courant), date
    passée avec les deux équipes (somme), date passée sans aucun snapshot
    (`categories: []`), date future (400), date au format invalide (400).
  - `BreadStockByDatePermissionTests` : GERANT et FACTURIER ne peuvent jamais
    lire un autre nœud (valeur `node` forgée ignorée) ; HQ (`DIRECTION`) doit
    préciser `node` explicitement (400 sinon) et peut alors lire n'importe
    quel nœud ; requête non authentifiée refusée (401/403).

## Tests

- `backend/.venv/Scripts/python.exe manage.py test production.tests.test_bug144_bread_stock_by_date`
  → **12/12 OK**.
- `backend/.venv/Scripts/python.exe manage.py test production sales finance`
  → **243 tests, OK** (0 échec, 0 erreur).
- `backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run`
  → `No changes detected`. **Aucune migration** : ce ticket n'ajoute aucun
  champ de modèle, uniquement une vue de lecture agrégeant des données déjà
  persistées (`BreadStock`, `DailyBreadStockSnapshot`).

## Non-régression / impact API

Aucun contrat d'API existant n'est modifié — `BreadStockViewSet`
(`GET /api/production/bread-stocks/`) et `ProductionSessionViewSet`
(`GET /api/production/sessions/`) sont inchangés. Seul un **nouvel** endpoint
est ajouté. Aucun ticket `dev-frontend` de rupture n'est nécessaire pour un
contrat cassé — en revanche **BUG-145** (déjà annoncé par le coordinateur)
devra consommer ce nouveau contrat pour le sélecteur de date et le
renommage « Stock Pains Actuel » → « Stock Pains du Jour ».

## Risques / points en attente

- Le point d'attention sur les jours où une seule équipe a clôturé (ci-dessus,
  section « snapshot ») — signalé pour `dev-frontend`/coordinateur, pas
  bloquant.
- Aucun autre risque identifié : opération entièrement en lecture, aucune
  modification de solde, aucun verrou nécessaire (CLAUDE.md §4 ne s'applique
  qu'aux écritures).

## Statut du ticket

BUG-144 passé à **CORRIGÉ** dans `docs/qa/REGISTRE_BUGS.md` (pas `VÉRIFIÉ` —
CLAUDE.md §7 règle 3, seul le testeur d'origine ou le coordinateur peut
valider).
