# Rapport dev-backend — 2026-10-31 — BUG-117

## Ticket traité

**BUG-117** — `FinancialYearViewSet.summary()` (`backend/finance/views.py`) : `int(request.
query_params.get('year', datetime.date.today().year))` appelé sans aucune protection — un paramètre
`year` non numérique (ex. `year=abc`) déclenche une `ValueError` non rattrapée → `500 Internal Server
Error` au lieu d'un `400` propre. Même famille de défaut que BUG-114/115 (déjà VÉRIFIÉ), mais ici sur
un `int()` direct, pas un lookup Django `__year=`/`__month=`.

- Gravité : Mineur
- Composant : backend
- Statut avant : OUVERT
- Statut après : **CORRIGÉ** (pas VÉRIFIÉ — conforme à CLAUDE.md §7 et à la consigne explicite du
  ticket : c'est le coordinateur qui vérifiera ce ticket, vu sa simplicité).

## Cause

`summary()` lisait `year` depuis `request.query_params` et le convertissait directement avec
`int(...)`, sans `try/except` ni borne de plage. Une valeur non convertible en entier lève une
`ValueError` non interceptée par DRF, remontée en `500`.

## Correctif

Fichier modifié : `backend/finance/views.py::FinancialYearViewSet.summary()`.

Réutilisation de `_validate_month_year(month, year)` (déjà définie dans `backend/treasury/views.py`
par BUG-114, déjà importée dans `backend/finance/views.py` pour BUG-115) — **aucune nouvelle
fonction créée, aucune duplication de logique**. Cette fonction accepte déjà `month=None` (« aucun
filtre mois demandé », ne valide alors que `year`), ce qui correspond exactement au besoin de
`summary()` qui ne reçoit qu'un paramètre `year` (pas de `month`).

```python
year_param = request.query_params.get('year')
error = _validate_month_year(None, year_param)
if error:
    return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
year = int(year_param) if year_param is not None else datetime.date.today().year
```

- Comportement inchangé pour une entrée valide (même valeur par défaut : année courante si `year`
  absent).
- Bornes appliquées : 2000-2100 (`_JOURNAL_YEAR_MIN`/`_JOURNAL_YEAR_MAX`, mêmes constantes que
  BUG-114/115 — aucune nouvelle borne inventée).
- `500` → `400` pour toute entrée invalide (`year='abc'` ou hors bornes), message en français,
  `{"detail": "..."}` conforme CLAUDE.md §4.

### Point 3 du ticket (recherche d'autres `int(request.query_params.get(...))` non protégés)

Recherche effectuée dans `backend/finance/views.py` : `summary()` était la **seule** occurrence de
ce motif. `doc1_report()`/`doc1_export()` lisent `month`/`year` comme chaînes et les passent déjà à
`_validate_month_year()` (corrigé par BUG-115) — aucune conversion `int()` directe non protégée
ailleurs dans ce fichier.

## Impact API

Aucun changement de contrat pour une entrée valide. Pour une entrée invalide : `500` → `400`
(durcissement pur, aucun appelant légitime ne peut dépendre d'un `500`). Aucun ticket `dev-frontend`
nécessaire : `summary()` n'est consommé avec aucune saisie libre d'année côté UI (vérifié dans
`frontend/src/api/services.ts` et les pages consommatrices).

## Test de non-régression

Nouveau fichier : `backend/finance/tests/test_bug117_summary_year_validation.py`
(`SummaryYearValidationTests`, 4 scénarios) :
- `year='abc'` → `400`, `{"detail": ...}` (échouait avant le correctif : `500`).
- `year='20000'` (hors bornes) → `400`.
- `year='2026'` (valeur plausible) → `200` (non-régression).
- Absence de `year` → `200`, comportement « année courante » inchangé (non-régression).

## Résultats des vérifications

- `python manage.py test finance` → 25 tests, OK (0 échec).
- `python manage.py test` (suite complète) → **425 tests, OK, 0 échec** (969,7 s — machine partagée
  très chargée par d'autres sessions d'agents pendant cette exécution, phénomène déjà noté sous
  BUG-115 avec la suite à 1429 s ; sans rapport avec le correctif).
- `python manage.py makemigrations --check --dry-run` → « No changes detected ».
- `PRAGMA integrity_check` sur `backend/db.sqlite3` (pas `data_kiese/`) → `ok`.

## Fichiers modifiés

- `backend/finance/views.py` (`FinancialYearViewSet.summary()`).
- `backend/finance/tests/test_bug117_summary_year_validation.py` (nouveau).
- `docs/qa/REGISTRE_BUGS.md` (ligne de synthèse BUG-117 → CORRIGÉ, fiche détaillée ajoutée).

## Tickets en attente

Aucun autre ticket backend ne m'avait été confié dans cette session — uniquement BUG-117.

## Risques / points d'attention pour le coordinateur

- Aucun risque fonctionnel identifié : correctif isolé, réutilise une fonction de validation déjà
  éprouvée (BUG-114/115), ne touche aucun autre endpoint ni aucun modèle.
- La suite complète a pris 969,7 s à cause d'une charge machine partagée très élevée pendant cette
  session (nombreux autres agents actifs en parallèle, confirmé par `tasklist`/`ps aux` montrant
  plusieurs processus `python.exe` concurrents sans rapport avec ce correctif). Aucune action
  requise — même phénomène déjà documenté et sans conséquence lors de BUG-115.
