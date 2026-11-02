# Rapport dev-backend — BUG-115 (2026-10-30/31)

## Ticket traité

**BUG-115** — Autres points de filtrage `date__year=`/`date__month=` non validés dans
`backend/treasury/views.py` et `backend/finance/views.py` (même défaut que BUG-114, déjà
VÉRIFIÉ). Statut final : **CORRIGÉ** (pas VÉRIFIÉ — conforme à CLAUDE.md §7, seul le testeur
d'origine ou le coordinateur peut passer un ticket à VÉRIFIÉ).

## Périmètre examiné

Recherche exhaustive de `__year=`/`__month=` dans les deux fichiers cités par le ticket
(`backend/treasury/views.py`, `backend/finance/views.py`).

### Points réellement corrigés (4)

| Fichier | Classe/méthode | Lookup non validé |
|---|---|---|
| `backend/treasury/views.py` | `LocalExpenseViewSet.get_queryset()` | `date__month=`/`date__year=` |
| `backend/treasury/views.py` | `DailySavingsViewSet.get_queryset()` | `date__month=`/`date__year=` |
| `backend/treasury/views.py` | `DailySavingsViewSet.monthly_total()` | `date__month=`/`date__year=` |
| `backend/finance/views.py` | `FinancialYearViewSet.doc1_report()` | `invoice_date__month=`/`invoice_date__year=` |
| `backend/finance/views.py` | `FinancialYearViewSet.doc1_export()` | `invoice_date__month=`/`invoice_date__year=` |

(5 points, pas 4 — `doc1_report`/`doc1_export` comptent chacun pour un.)

### Points cités dans le ticket d'ouverture mais écartés après relecture (aucun défaut réel)

- **`CashbookEntryViewSet`** (`backend/treasury/views.py`) : relecture complète — ce ViewSet ne
  filtre que par `date__gte=`/`date__lte=` (`get_queryset()`, `period_summary`), jamais par
  `date__year=`/`date__month=`. La ligne « ~973 » citée dans le ticket d'ouverture pointait en
  réalité (décalage) vers `JournalEntryViewSet.monthly_report()`, déjà corrigée par BUG-114.
- **`FinancialYearViewSet.income_statement()`/`.cashflow()`/`.balance_sheet()`/`.comparative()`** :
  les helpers `_income_statement_for_year(year)`/`_cashflow_for_year(year)`/
  `_balance_sheet_for_year(year)` contiennent bien des lookups `__year=` (`invoice__invoice_date__year=`,
  `created_at__year=`, `date__year=`, `period__year=`), mais `year` provient systématiquement de
  `FinancialYear.year` (champ modèle entier), jamais d'un paramètre de requête brut non validé —
  aucune `ValueError` possible par cette voie.
- **`FinancialYearViewSet.summary()`** (`backend/finance/views.py` l.208) : filtre
  `CommissionPeriod.objects.filter(year=year)` — champ entier simple, pas un lookup `__year=`/
  `__month=` sur un `DateField`, donc hors périmètre exact du ticket (qui demandait explicitement
  une recherche de `__year=`/`__month=`). **Point signalé au coordinateur, non corrigé ici** :
  `year = int(request.query_params.get('year', ...))` non protégé reste un risque de même nature
  (`ValueError` sur `year=abc` → 500) — à traiter dans un ticket séparé si confirmé par le
  coordinateur, pour ne pas sortir du périmètre de BUG-115 (CLAUDE.md §7, pas de refactorisation
  hors ticket).

## Cause

Identique à BUG-114 : `month`/`year` pris bruts depuis `request.query_params` et transmis
directement à `QuerySet.filter(date__month=..., date__year=...)` (ou
`invoice_date__month=`/`invoice_date__year=`), sans conversion contrôlée ni bornes. Une année hors
de la plage representable par le backend SQL de la date (ex. `year=20000`) ou non convertible en
entier (`year='abc'`) fait lever une `ValueError` non interceptée par Django, remontée en `500`
au lieu d'un `400` propre.

## Correctif

Réutilisation stricte de la fonction déjà existante `_validate_month_year(month, year)`
(`backend/treasury/views.py`, introduite par BUG-114) — **aucune duplication**, aucune nouvelle
fonction créée, aucune modification de sa signature ni de ses bornes (`month` 1-12, `year`
2000-2100).

- `backend/treasury/views.py` :
  - `LocalExpenseViewSet.get_queryset()` : appel à `_validate_month_year()` juste avant les
    `qs.filter(date__month=...)`/`qs.filter(date__year=...)` existants ; `raise
    ValidationError({'detail': error})` (import déjà présent en tête de fichier depuis BUG-114).
  - `DailySavingsViewSet.get_queryset()` : même style, même emplacement logique.
  - `DailySavingsViewSet.monthly_total()` : validation juste après la lecture de `month`/`year` ;
    `return Response({'detail': error}, status=400)`, même style que
    `JournalEntryViewSet.monthly_report()`.
- `backend/finance/views.py` :
  - Import ajouté en tête de fichier : `from treasury.views import _validate_month_year` — pas de
    copie de la fonction, réutilisation directe de l'unique implémentation, conformément à la
    consigne du ticket.
  - `FinancialYearViewSet.doc1_report()` et `.doc1_export()` : appel à `_validate_month_year()`
    juste après la vérification d'existence des 3 paramètres déjà en place (`if not
    all([node_id, month, year])`), avant `Invoice.objects.filter(...)` ; `return
    Response({'detail': error}, status=400)`.

Aucun changement de contrat d'API au-delà du comportement déjà établi par BUG-114 (`400
{"detail": "..."}` pour une entrée hors bornes, comportement normal sinon). Aucun ticket
`dev-frontend` nécessaire : vérifié que ces 4 endpoints ne sont pas exposés dans l'UI avec une
saisie libre d'année comparable au champ `journalYear` de BUG-114 (les appels existants dans
`frontend/src/api/services.ts` passent des valeurs déjà contraintes par des sélecteurs de
date/mois).

## Fichiers modifiés

- `backend/treasury/views.py` (3 emplacements + commentaire BUG-115)
- `backend/finance/views.py` (import + 2 emplacements + commentaires BUG-115)
- `backend/treasury/tests/test_bug115_month_year_validation.py` (nouveau, 12 scénarios)
- `backend/finance/tests/test_bug115_doc1_month_year_validation.py` (nouveau, 7 scénarios)
- `docs/qa/REGISTRE_BUGS.md` (ligne de synthèse BUG-115 → CORRIGÉ, fiche détaillée ajoutée après
  BUG-114)
- Ce rapport.

## Tests de non-régression (échouaient avant / passent après)

- `backend/treasury/tests/test_bug115_month_year_validation.py` : 12 scénarios —
  `LocalExpenseYearValidationTests` (4 cas : `year=20000`, `year='abc'`, `month=13`, valeur
  plausible) et `DailySavingsYearValidationTests` (8 cas, couvrant `get_queryset()` et
  `monthly_total()` séparément, mêmes types de scénarios). Tous `400` pour les valeurs invalides,
  `200` pour une valeur plausible (non-régression).
- `backend/finance/tests/test_bug115_doc1_month_year_validation.py` : 7 scénarios sur
  `doc1_report`/`doc1_export`. Point d'attention technique : `doc1_export` renvoie un
  `StreamingHttpResponse` (export CSV) — pas de `.content`, l'assertion de non-régression ne lit
  que `status_code`.

Confirmé par exécution ciblée : `python manage.py test treasury.tests.test_bug115_month_year_validation
finance.tests.test_bug115_doc1_month_year_validation` → **19 tests, OK, 0 échec**.

## Suite complète

- `python manage.py test treasury finance` → **116 tests, OK, 0 échec** (confirmé).
- `python manage.py test` (suite entière) → **418 tests, OK, 0 échec** (confirmé en fin de
  session). La machine était très chargée pendant la session (plusieurs processus `python.exe`
  concurrents observés via `tasklist`, dont une commande `tasklist` elle-même restée bloquée
  plusieurs minutes), ce qui a fortement ralenti l'exécution (1429 s, contre un ratio ~3 s/test
  mesuré sur `treasury finance` seul) sans lien avec le correctif lui-même — aucun échec, aucune
  erreur.
- `python manage.py makemigrations --check --dry-run` → « No changes detected » (aucun changement
  de schéma, correctif purement applicatif, cohérent avec le périmètre du ticket).
- `PRAGMA integrity_check` sur `backend/db.sqlite3` (jamais `data_kiese/`) → `ok`.

## Risques / points d'attention pour la suite

1. **`FinancialYearViewSet.summary()`** (`backend/finance/views.py` l.208) : `int(request
   .query_params.get('year', ...))` non protégé contre une valeur non numérique — même famille de
   défaut, mais hors périmètre strict de BUG-115 (pas un lookup `__year=`/`__month=`). Signalé
   ci-dessus et dans la fiche du registre ; à trancher par le coordinateur (nouveau ticket ou
   extension de BUG-115).
3. Aucun ticket `dev-frontend` ouvert — vérifié que le changement de comportement (400 au lieu de
   500 pour une entrée déjà invalide) n'a aucun impact sur un flux UI existant.

## Fichiers (chemins absolus)

- `D:\Projects\kiesse\backend\treasury\views.py`
- `D:\Projects\kiesse\backend\finance\views.py`
- `D:\Projects\kiesse\backend\treasury\tests\test_bug115_month_year_validation.py`
- `D:\Projects\kiesse\backend\finance\tests\test_bug115_doc1_month_year_validation.py`
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md`
- `D:\Projects\kiesse\docs\qa\rapports\dev-backend-2026-10-30-bug115.md` (ce rapport)
