# Rapport dev-backend — 2026-11-22 (a5)

Tickets traités (statut CORRIGÉ) : BUG-526, 527, 528, 529. BUG-530 laissé à B (commissions).

## Cause commune
Paramètres de requête passés bruts aux filtres ORM (ValueError/ValidationError Django non rattrapée) -> 500.

## Correctifs
- `backend/kiese/node_guard.py` : helpers partagés `resolve_node_param` (pk ou code, inconnu -> 400), `parse_date_param`, `month_year_error` (mois 1-12, année 2000-2100).
- production/views.py : `ProductionSessionViewSet.get_queryset` (date_from/date_to -> 400 via `_safe_parse_date`), `flour_history` (month/year).
- sales/views.py : `daily_summary` (date). `bread_summary` l.1209 revu : déjà sûr (400 si non numérique).
- finance/views.py : `summary`, `doc1_report`, `doc1_export` (`?node=`).
- blockchain/views.py : `alerts`, `snapshots`, `run_check` (query ou corps).

## Tests
- Nouveau : `backend/core/tests/test_params_invalides_a.py` (9 tests). AVANT correctif : 7 échecs sur 9 (FAILED failures=7) ; APRÈS : 9 OK.
- `core/tests/test_verif_params_invalides_c.py` : `@expectedFailure` retiré pour 526 à 529 (530 conservé).
- Labels demandés (1440 tests, 1270 s) : seule erreur = `sales...test_makemigrations_check`, causée par des fichiers de production/ (models.py, migration 0027 untracked) modifiés en parallèle par un autre agent pendant la run ; `makemigrations --check --dry-run` relancé ensuite : "No changes detected". `manage.py check` propre. 5 échecs attendus (xfail) restants, 1 skip.

## Contrat d'API (500 -> 400 `{"detail": ...}`, français)
`?node=` de finance/blockchain accepte désormais pk OU code boulangerie. Sans paramètre : comportement inchangé.

## Appels frontend à vérifier (aucun modifié)
Aucun n'envoie de valeur invalide en usage normal :
- `salesApi.dailySummary()` (services.ts:1495) : sans paramètre.
- `productionApi.movements.flourHistory` (services.ts:1590 ; Production.tsx:330, 804) : seulement `node` (pk du sélecteur) ; month/year jamais envoyés.
- `productionApi.sessions.list({date_from})` (Dashboard.tsx:113), ReconciliationPanel.tsx:45 : dates ISO.
- `financeApi.doc1Report/doc1Export` (Finance.tsx:104, 116) : `node` = id de nœud, month/year numériques. `financeApi.summary` : non appelé dans les pages.
- `blockchainApi.alerts.list({resolved})`, `snapshots.list()`, `runCheck(nodeId?)` : node = id.
Risque résiduel : un sélecteur vide enverrait `node=''` (ignoré côté serveur, pas de 400).

## Observation hors périmètre
finance `doc1_report/doc1_export` (IsAuthenticated) ne limitent pas `?node=` au nœud de l'utilisateur non-siège : à examiner (ticket à ouvrir par le coordinateur si confirmé).
