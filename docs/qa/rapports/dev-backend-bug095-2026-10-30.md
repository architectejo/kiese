# Rapport dev-backend — BUG-095 (2026-10-30)

## Ticket traité

**BUG-095** (`docs/qa/REGISTRE_BUGS.md`) — Recherche client substring pure (`ClientViewSet`,
`filters.SearchFilter`) sans priorité pour la correspondance exacte/préfixe : « kiese » remontait
« Makiese » au même rang que « Kiese », risque de facturer le mauvais client (remarque.md,
« Réclamation des agents du client », point 2).

Statut : `À CLARIFIER` → **`CORRIGÉ`** (jamais `VÉRIFIÉ`, réservé au testeur d'origine ou au
coordinateur).

### Décision du coordinateur qui lève l'ambiguïté

Tri par pertinence côté serveur (exact > préfixe > substring), **pas** de restriction stricte des
résultats à une seule proposition — le filtre substring existant (`filters.SearchFilter`,
`icontains`) reste inchangé, pour ne jamais masquer un homonyme légitime (risque identifié par le
testeur-clients-commissions dans l'analyse d'impact initiale). Seul l'**ordre** des résultats change.

## Cause

`ClientViewSet` (`backend/clients/views.py`) appliquait un tri uniquement alphabétique
(`ordering = ['last_name']`, via `filters.OrderingFilter`) sans aucune pondération de pertinence pour
les résultats de la recherche (`filters.SearchFilter`, `icontains`). Une correspondance exacte ou en
préfixe du terme recherché se retrouvait mélangée, dans un ordre arbitraire, avec une simple
correspondance de sous-chaîne.

## Correctif

Fichier modifié : `D:\Projects\kiesse\backend\clients\views.py`.

- Ajout de `ClientViewSet.filter_queryset()` : après l'application normale des backends DRF
  (`DjangoFilterBackend`, `filters.SearchFilter`, `filters.OrderingFilter`, qui conservent leur
  comportement intact, y compris le filtrage multi-nœuds préexistant dans `get_queryset()`), si un
  paramètre `search` est présent **et** qu'aucun `ordering` explicite n'est demandé par l'appelant,
  le queryset est réordonné par pertinence.
- `_order_by_relevance()` (méthode statique) annote `code`, `first_name`, `last_name` et les deux
  concaténations du nom complet (`last_name first_name` / `first_name last_name`) en minuscules
  (`Lower`/`Concat`), puis calcule un score `_search_rank` (`Case`/`When`) :
  - **0 — exact** : un des champs/concaténations ci-dessus égale exactement (insensible à la casse)
    le terme recherché ;
  - **1 — préfixe** : un de ces champs commence par le terme (`startswith`) ;
  - **2 — défaut (substring)** : comportement inchangé, tout résultat qui matchait déjà via
    `icontains` sans entrer dans les deux niveaux précédents.
- Tri final : `order_by('_search_rank', 'last_name', 'first_name')` — tri secondaire stable et
  cohérent avec le tri alphabétique par défaut (hors recherche, qui n'est pas affecté).

Le filtrage multi-nœuds des facturiers/livreurs (`get_queryset`, BUG-025/065/069) n'est pas touché :
il reste appliqué en amont, avant les backends DRF ; la nouvelle logique n'ajoute qu'une annotation et
un `order_by` sur un queryset déjà filtré.

## Tests de non-régression (qui échouaient avant / passent après)

Fichier : `D:\Projects\kiesse\backend\clients\tests\test_api.py`, nouvelle classe
`SearchRelevanceOrderingTests` (4 tests) :
- `test_prefix_match_ranked_before_substring_only_match` : "kiese" place "Kiese" (préfixe de
  `last_name`) avant "Makiese" (substring uniquement) — reproduit exactement le scénario du ticket.
- `test_exact_code_match_ranked_first` : une recherche par code exact place ce client en tête.
- `test_explicit_ordering_param_overrides_relevance` : `?ordering=-last_name` explicite reste
  respecté (non-régression pour les écrans qui trient volontairement autrement).
- `test_substring_search_still_returns_all_matches` : les deux homonymes restent tous deux présents
  dans les résultats — pas de restriction/masquage.

Non-régression vérifiée sur les tests existants : `FacturierCrossNodeSearchTests` (recherche
cross-node par nom/code pour FACTURIER, BUG-065/069) et le reste de la suite `clients` passent sans
modification.

## Vérifications demandées

- `python manage.py test clients` → **52 tests, OK**.
- `python manage.py test` (suite complète) → **335 tests, 4 échecs**, mais **aucun dans `clients`**
  et aucun lié à la recherche/pertinence : `production.tests.test_disposal_reconciliation.
  BreadDisposalCategorizationTests` (2 échecs, « pain soldé » bloqué en écriture directe depuis
  Production — cf. BUG-092, déjà ouvert, sans rapport avec ce ticket) et
  `treasury.tests.test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario` +
  `treasury.tests.test_reports_closures.CashClosureNetCashTests.
  test_net_cash_is_cash_sales_minus_local_expenses` (2 échecs, trésorerie/clôtures, hors périmètre
  `clients`). Ces 4 échecs sont **préexistants** à ce correctif : aucun fichier de `production` ou
  `treasury` n'a été touché ici, seul `backend/clients/views.py` et
  `backend/clients/tests/test_api.py` ont été modifiés.
- `python manage.py makemigrations --check --dry-run` → des différences de schéma **préexistantes**
  sont signalées sur `production` (`BreadTransfer`, `BreadTransferLine`, `ConsumableCount`) et
  `clients`/`treasury` (contraintes `unique_together` sur `SocialContribution`,
  `SocialDistribution`, `SocialDistributionLine`, `DailySavings`) — **non liées à ce ticket** : ce
  correctif ne modifie que `views.py`, aucun modèle. Signalé pour mémoire au coordinateur si ce
  n'est pas déjà tracé ailleurs.
- `PRAGMA integrity_check` sur `backend/db.sqlite3` → `ok`.

## Impact contrat d'API

Aucun changement de contrat : même format de réponse (`results`, pagination, champs), même filtrage.
Seul l'**ordre** des éléments change pour les requêtes `?search=...` sans `?ordering=` explicite.
Pas de ticket `dev-frontend` nécessaire : `Sales.tsx` et `Clients.tsx` consomment déjà l'ordre renvoyé
par le serveur sans post-tri côté client (confirmé dans l'analyse d'impact du ticket) — ils
bénéficient du correctif sans modification de code frontend.

## Risques / points d'attention pour la suite

- Le périmètre de `_order_by_relevance` est volontairement limité à `code`/`first_name`/`last_name`
  (et leurs concaténations) — `phone` reste dans `search_fields` (filtrage substring inchangé) mais
  n'entre pas dans le calcul du score de pertinence (un numéro de téléphone n'a pas de notion
  « préfixe pertinent » comparable à un nom). À signaler si le client souhaite étendre la pertinence
  au téléphone.
- Si un futur ticket ajoute un tri de pertinence équivalent côté frontend (désambiguïsation visuelle,
  option B évoquée dans l'analyse d'impact BUG-095), il doit rester cohérent avec cet ordre serveur.
