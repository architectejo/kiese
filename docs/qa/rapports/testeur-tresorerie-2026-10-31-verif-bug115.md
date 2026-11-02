# Rapport — testeur-tresorerie — 2026-10-31 — Vérification BUG-115

## Objet

Vérification indépendante du correctif de **BUG-115** (dev-backend, 2026-10-31) : extension du
motif corrigé par BUG-114 (`_validate_month_year()`) à 5 nouveaux points de filtrage
`date__year=`/`date__month=`/`invoice_date__year=`/`invoice_date__month=` non validés dans
`backend/treasury/views.py` (`LocalExpenseViewSet.get_queryset()`, `DailySavingsViewSet
.get_queryset()`/`.monthly_total()`) et `backend/finance/views.py` (`FinancialYearViewSet
.doc1_report()`/`.doc1_export()`).

Rien n'a été modifié dans le code applicatif (conforme CLAUDE.md §7.2, rôle testeur). BUG-117
(nouveau ticket distinct, resté `OUVERT`) n'a pas été touché, hors périmètre de cette mission.

## Méthode et constats

### 1. Relecture du diff applicatif

- `backend/treasury/views.py` l.199-218 (`LocalExpenseViewSet.get_queryset()`), l.1013-1033
  (`DailySavingsViewSet.get_queryset()`), l.1077+ (`.monthly_total()`) : appel à
  `_validate_month_year(month, year)` (fonction unique introduite par BUG-114, l.52) juste avant
  chaque `qs.filter(date__month=...)`/`qs.filter(date__year=...)`, `raise ValidationError(...)` ou
  `Response({'detail': error}, status=400)` selon le style déjà en place localement. Aucune
  duplication de la fonction.
- `backend/finance/views.py` l.12 : `from treasury.views import _validate_month_year` (import
  direct, pas de copie). `doc1_report()` l.245-268 et `doc1_export()` l.322-344 : appel à
  `_validate_month_year()` juste après la vérification d'existence des 3 paramètres déjà en place,
  avant le `Invoice.objects.filter(..., invoice_date__month=month, invoice_date__year=year)`.

Le diff correspond exactement à la description du correctif consignée dans
`docs/qa/REGISTRE_BUGS.md` (fiche BUG-115).

### 2. Recontrôle indépendant des 3 points écartés par dev-backend

- **`CashbookEntryViewSet`** (`backend/treasury/views.py` l.583-650) : relecture complète de la
  classe. `get_queryset()` ne filtre que par `date__gte=`/`date__lte=` ; `period_summary` reprend
  les mêmes deux bornes. Aucun `date__year=`/`date__month=` n'existe dans ce ViewSet. **Exclusion
  confirmée.**
- **`FinancialYearViewSet.income_statement()`/`.cashflow()`/`.balance_sheet()`/`.comparative()`**
  (`backend/finance/views.py` l.153-192) : les 4 actions sont `detail=True` ; `fy =
  self.get_object()` résout l'instance par `pk` (jamais par un paramètre de requête libre), puis
  `_income_statement_for_year(fy.year)` etc. reçoivent `fy.year`, le champ entier du modèle
  `FinancialYear` — jamais une chaîne brute de `request.query_params`. Les lookups `__year=`
  internes (`invoice__invoice_date__year=`, `created_at__year=`, `date__year=`, `period__year=`)
  ne sont donc exposés à aucune entrée utilisateur non validée par cette voie. **Exclusion
  confirmée.**
- **`FinancialYearViewSet.summary()`** : `int(request.query_params.get('year', ...))` non protégé
  — risque réel de même famille (`year=abc` → `ValueError` → 500), mais porte sur un `int()` direct
  et non un lookup `__year=`/`__month=` Django : hors du périmètre exact formulé par le ticket
  d'ouverture. Correctement reporté par dev-backend sous un ticket séparé (**BUG-117**, `OUVERT`,
  non traité ici conformément à la consigne reçue).

### 3. Reproduction indépendante (sans se fier aux seuls tests de dev-backend)

Script Django isolé (base de test jetable, détruite après usage, aucune donnée réelle), exécuté
depuis `backend/.venv/Scripts/python.exe` :

| Requête | Résultat |
|---|---|
| `GET /api/treasury/expenses/?year=20000` | `400`, « doit être compris entre 2000 et 2100 » |
| `GET /api/treasury/expenses/?year=abc` | `400`, « doit être un entier » |
| `GET /api/treasury/savings/monthly_total/?year=20000` | `400` |
| `GET /api/finance/years/doc1_report/?node=<uuid>&month=10&year=20000` | `400` |
| `GET /api/finance/years/doc1_report/?node=<uuid>&month=10&year=abc` | `400` |
| `GET /api/finance/years/doc1_export/?node=<uuid>&month=13&year=2026` | `400`, « doit être compris entre 1 et 12 » |

Aucun `500` observé. Comportement conforme au contrat attendu (`400 {"detail": "..."}`, même
contrat que BUG-114).

### 4. Relecture des nouveaux fichiers de test

- `backend/treasury/tests/test_bug115_month_year_validation.py` (12 scénarios) :
  `LocalExpenseYearValidationTests` (4) et `DailySavingsYearValidationTests` (8, couvrant
  `get_queryset()` et `monthly_total()` séparément) — hors bornes, non-entier, mois hors 1-12,
  non-régression sur valeur plausible. Cohérent, aucune lacune.
- `backend/finance/tests/test_bug115_doc1_month_year_validation.py` (7 scénarios) : mêmes cas sur
  `doc1_report`/`doc1_export`, y compris la non-régression sur l'export CSV (`StreamingHttpResponse`,
  vérifié via le code de statut uniquement, pas `.content`, ce qui est le bon réflexe pour ce type
  de réponse). Cohérent, aucune lacune.

### 5. Suites de tests

- `python manage.py test treasury finance` (relancé indépendamment, machine non chargée au moment
  du test) → **116 tests, OK, 0 échec** (durée ~300 s).
- Suite complète (421 tests) : déjà relancée par le coordinateur en isolation stricte après le
  correctif, avec confirmation **0 échec** (exit code 0) — non rejouée à l'identique dans cette
  vérification, conformément à la consigne reçue (le point d'attention de dev-backend sur ce point
  est donc déjà levé).

### 6. Intégrité du schéma et de la base

- `python manage.py makemigrations --check --dry-run` → « No changes detected ».
- `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok`.

## Conclusion

Tous les points de vérification demandés sont conformes. Le correctif de BUG-115 est validé de
façon indépendante : les 5 points corrigés renvoient désormais `400` (jamais `500`) pour des
valeurs `month`/`year` hors bornes ou non entières, sans régression sur les valeurs plausibles ; les
3 points écartés par dev-backend sont effectivement hors du défaut initial, confirmé par relecture
directe du code (pas seulement du texte du ticket).

**BUG-115 passé à `VÉRIFIÉ`** dans `docs/qa/REGISTRE_BUGS.md` (table récapitulative + fiche
détaillée, section « Vérification — testeur-tresorerie, 2026-10-31 »).

BUG-117 reste `OUVERT`, non traité ici (hors périmètre de cette mission, conformément à la
consigne reçue).

## Fichiers concernés

- `D:\Projects\kiesse\backend\treasury\views.py`
- `D:\Projects\kiesse\backend\finance\views.py`
- `D:\Projects\kiesse\backend\treasury\tests\test_bug115_month_year_validation.py`
- `D:\Projects\kiesse\backend\finance\tests\test_bug115_doc1_month_year_validation.py`
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md`
- `D:\Projects\kiesse\docs\qa\rapports\testeur-tresorerie-2026-10-31-verif-bug115.md` (ce rapport)
