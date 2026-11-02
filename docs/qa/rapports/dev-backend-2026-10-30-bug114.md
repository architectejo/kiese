# Rapport dev-backend — 2026-10-30 — BUG-114

## Ticket traité

**BUG-114** — `JournalEntryViewSet` : année hors bornes non validée côté serveur → 500 au lieu
de 400 (Trésorerie, backend/frontend, Mineur). Statut final : **CORRIGÉ** (passage à `VÉRIFIÉ`
laissé au testeur-e2e, ouvreur du ticket, conformément à CLAUDE.md §7, règle 3).

## Cause

`JournalEntryViewSet.get_queryset()` et `.monthly_report()` (`backend/treasury/views.py`)
passaient les paramètres `month`/`year` de la requête (chaînes brutes de
`request.query_params`) directement à `QuerySet.filter(date__month=..., date__year=...)`, sans
aucune conversion contrôlée ni borne de validité. Pour une année hors de la plage representable
par le lookup `date__year` (ex. `20000`), Django lève une `ValueError: year 20000 is out of
range` dans `django.db.backends.base.operations.year_lookup_bounds_for_date_field`, non
interceptée, qui remonte en `500 Internal Server Error`. Une valeur `year` non convertible en
entier (`abc`) aurait causé le même type de défaut non maîtrisé (`ValueError` lors du cast
implicite par le moteur SQL / lookup Django).

## Fichiers modifiés

- `backend/treasury/views.py`
  - Import ajouté : `from rest_framework.exceptions import ValidationError` (en tête de fichier ;
    jusqu'ici importé seulement localement dans `perform_create`).
  - Nouvelles constantes `_JOURNAL_YEAR_MIN = 2000`, `_JOURNAL_YEAR_MAX = 2100` et fonction
    `_validate_month_year(month, year)` : valide `month` (1-12 si fourni) et `year` (bornes
    ci-dessus si fourni) ; retourne un message d'erreur en français ou `None`. Plage
    volontairement plus large que les bornes `2024`-`2035` de l'UI (qui ne sont qu'une aide
    visuelle pour le sélecteur par défaut du frontend), pour ne jamais rejeter de données
    historiques légitimes côté serveur.
  - `JournalEntryViewSet.get_queryset()` : appel à `_validate_month_year()` juste avant les
    filtres `date__month=`/`date__year=` existants ; `raise ValidationError({'detail': error})`
    en cas d'erreur → DRF convertit automatiquement en `400`. Le filtrage par nœud (BUG-113, juste
    au-dessus dans la même méthode) est inchangé et a été relu avant modification pour ne pas le
    régresser.
  - `JournalEntryViewSet.monthly_report()` : même validation juste après la lecture de
    `month`/`year` (donc avant le filtrage par nœud BUG-113, qui en est indépendant) ; retourne
    directement `Response({'detail': error}, status=400)`, cohérent avec les autres réponses
    d'erreur explicites déjà présentes dans cette action (ex. `403` sans nœud associé).

- `frontend/src/pages/dashboard/Treasury.tsx`
  - Champ `journalYear` (§5.1.4, navigation mois/année du Journal de Caisse) : `onChange` clampe
    désormais la valeur saisie entre les bornes déjà affichées sur l'`<input type="number">`
    (`min={2024} max={2035}`) :
    `Math.min(2035, Math.max(2024, Number(e.target.value) || 2024))`, même idiome que les autres
    champs numériques de la page (`Math.max(0, ...)` sur la ventilation des billets de la Clôture
    / du bordereau de décaissement). Défense en profondeur côté UX uniquement (le `min`/`max` HTML
    n'étant qu'une aide visuelle pour le picker du navigateur, pas une validation bloquante de
    `fill`/`input`/collage) ; le serveur reste la garantie réelle.

- `backend/treasury/tests/test_bug114_journal_year_validation.py` (nouveau fichier, test de
  non-régression — échouait avant / passe après ce correctif).

## Impact sur le contrat d'API

**Aucun changement de contrat.** Avant le correctif, une valeur hors bornes donnait déjà une
réponse d'erreur (`500`, non exploitable). Après le correctif, elle donne `400
{"detail": "..."}` (format déjà standard CLAUDE.md §4). Les requêtes avec des valeurs plausibles
(`2000` ≤ année ≤ `2100`, mois `1`-`12`) ou sans `month`/`year` du tout se comportent exactement
comme avant (`200`, mêmes formes de réponse). Aucun ticket `dev-frontend` complémentaire nécessaire.

## Test de non-régression

`backend/treasury/tests/test_bug114_journal_year_validation.py` — 8 scénarios :
- `GET /api/treasury/journal/?month=10&year=20000` → `400` (au lieu de `500`).
- `GET /api/treasury/journal/monthly_report/?month=10&year=20000` → `400` (au lieu de `500`).
- `year='abc'` (non entier) → `400` sur les deux endpoints.
- `month=13` et `month=0` (hors bornes) → `400` sur les deux endpoints.
- `month=10&year=2026` (valeurs plausibles) → `200` sur les deux endpoints (non-régression
  explicite du filtrage par nœud BUG-113, déjà VÉRIFIÉ, non touché par ce correctif).

Exécuté isolément avant le correctif (avec `_validate_month_year` commentée/retirée) : les 2
premiers scénarios échouaient effectivement avec `500` (reproduction confirmée). Après le
correctif : 8/8 passent.

## Résultats des vérifications demandées

- `cd backend && .venv\Scripts\python.exe manage.py test treasury.tests.test_bug114_journal_year_validation` → `OK` (8 tests).
- `cd backend && .venv\Scripts\python.exe manage.py test treasury` → `OK` (83 tests).
- `cd backend && .venv\Scripts\python.exe manage.py test` (suite complète) → `OK`, **399 tests**,
  0 échec (`Ran 399 tests in 1148.582s ... OK`).
- `cd backend && .venv\Scripts\python.exe manage.py makemigrations --check --dry-run` →
  `No changes detected` (aucun changement de schéma — correctif purement applicatif, pas de
  migration).
- `PRAGMA integrity_check` sur `backend/db.sqlite3` (base de développement, pas `data_kiese/`) →
  `ok` (lecture seule, aucune donnée modifiée).
- `cd frontend && npx tsc --noEmit` → aucune erreur.
- `cd frontend && npm run build` → build réussi (`tsc && vite build`, warnings habituels sur la
  taille des chunks legacy, sans rapport avec ce correctif).

## Risques / suivi

- Aucun risque identifié : correctif purement défensif (validation d'entrée), pas de changement
  de schéma, pas de changement de logique métier (BP, dette, CM, hash, soldes).
- Le filtrage par nœud BUG-113 (déjà VÉRIFIÉ) a été relu avant modification et n'a pas été touché ;
  les tests de non-régression l'exercent à nouveau pour s'en assurer.
- Ticket laissé à `CORRIGÉ`, pas `VÉRIFIÉ` (règle CLAUDE.md §7, point 3) : à vérifier par
  testeur-e2e (ouvreur du ticket) ou le coordinateur.
