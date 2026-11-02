# Rapport testeur-production — 2026-11-01/02 — Vérification BUG-118

## Mission

Vérifier **BUG-118** (`docs/qa/REGISTRE_BUGS.md`) dans son ensemble : correctif initial
(`DailyBreadStockSnapshot` sans équipe) + extension équipe A/B (confirmée par le client le
2026-11-01), les deux à vérifier ensemble avant de passer le ticket à `VÉRIFIÉ`.

Rappel règle CLAUDE.md §7 : un testeur ne corrige pas le code applicatif ; aucun fichier
applicatif n'a été modifié pendant cette vérification.

## Méthode et résultats

### 1. Relecture du code

- `backend/production/models.py` : `DailyBreadStockSnapshot` (champs `node`, `bread_price`, `date`,
  `team`, `qty_at_close`, `unique_together=[node, bread_price, date, team]`), méthodes de classe
  `reste_du_jour(node, bread_price, date, team)`, `reste_du_hier(node, bread_price, date, team)`,
  `record_snapshot(session)`.
- `backend/production/views.py::ProductionSessionViewSet.close()` : appelle
  `DailyBreadStockSnapshot.record_snapshot(session)` immédiatement après avoir figé
  `is_closed`/`closed_at`/`closure_summary`.
- Conclusion : l'implémentation correspond **exactement** à ce qui est décrit dans la fiche du
  registre (correctif initial + extension). Aucun écart constaté entre le code et la documentation.

### 2. Indépendance `BreadStock` / snapshot déclaratif

Confirmé dans `BreadDisposalViewSet.perform_create` (`backend/production/views.py`) :

```python
# REMAINING breads are not disposed — they stay in stock and roll into the next batch
if disposal.disposal_type != BreadDisposal.DisposalType.REMAINING:
    _adjust_bread_stock(disposal.node, disposal.bread_price, disposed=disposal.quantity)
```

Une disposition `REMAINING` (source de `qty_at_close`) ne modifie donc **jamais**
`BreadStock.qty_available`, qui reste le solde physique global partagé par nœud+catégorie,
totalement indépendant du solde déclaratif par équipe. Vérifié aussi par les tests (voir ci-dessous)
et par mon propre scénario de reproduction.

Aucune référence à `DailyBreadStockSnapshot`/`reste_du_jour`/`reste_du_hier` trouvée dans
`serializers.py`, `admin.py` du module, ni dans `frontend/src/pages/dashboard/Production.tsx` —
cohérent avec l'affirmation « aucun contrat d'API modifié, aucun endpoint exposé ».

### 3. Reproduction indépendante du scénario clé (A jour1+jour3, B jour1 seulement)

J'ai écrit un test temporaire (`production/tests/test_zzz_verif_bug118_scratch.py`, supprimé après
exécution — ne fait pas partie de la suite permanente) reproduisant :
- Jour 1 (2026-10-01) : équipe A clôture avec un reste déclaré de -70 ; équipe B clôture avec un
  reste déclaré de -20.
- Jour 3 (2026-10-03) : seule l'équipe A clôture, avec un reste déclaré de -40.

Résultats obtenus (`python manage.py test production.tests.test_zzz_verif_bug118_scratch` → OK) :
- `reste_du_hier(B, jour 3)` = **-20** (dernier jour où B a clôturé = jour 1), jamais une valeur de A
  ni 0 par erreur.
- `reste_du_hier(B, jour 4)` = **-20** également (B n'a toujours pas retravaillé).
- `reste_du_hier(A, jour 3)` = **-70** (dernier jour antérieur à jour 3 où A a clôturé = jour 1 ; le
  jour 2, qui n'existe pour aucune des deux équipes, est correctement ignoré).
- `BreadStock.qty_available` = 240 (100+50+90, somme brute des 3 fournées), **jamais** modifié par
  les déclarations REMAINING.
- Deux lignes distinctes `DailyBreadStockSnapshot` créées le jour 1 (une par équipe), aucun
  écrasement.

Conforme en tout point à la formule confirmée par le client et à la mission.

### 4. Suite de tests dédiée

`backend/production/tests/test_daily_stock_snapshot.py` (7 tests, relus intégralement) :
- `test_close_creates_snapshot_matching_declared_remaining`
- `test_second_closure_same_day_keeps_separate_team_snapshots`
- `test_reste_du_hier_is_negative_of_previous_snapshot_same_team`
- `test_reste_du_hier_is_zero_on_first_day_of_activity`
- `test_reste_du_hier_skips_days_with_no_closure_for_that_team`
- `test_reste_du_jour_is_none_when_not_yet_closed`
- `test_remaining_disposal_never_adjusts_global_bread_stock`

Tous pertinents, couvrent les scénarios demandés par la mission (y compris le cas exact « équipe A
clôture jour 1 et jour 2, équipe B clôture seulement jour 1 »). Aucun ajout nécessaire.

### 5. Exécution des tests

- `python manage.py test production.tests.test_daily_stock_snapshot` → **7/7 OK**.
- `python manage.py test production` (suite complète du module, rejouée après reprise de session) →
  **45/45 OK**.
- `python manage.py makemigrations --check --dry-run` → **« No changes detected »** (tout le projet,
  pas seulement `production`).
- `PRAGMA integrity_check` sur `backend/db.sqlite3` → **`ok`**.
- `python manage.py test` (suite complète projet, 441 tests) : dev-backend l'a exécutée le
  2026-11-01 avec ce même code (441/441 OK, voir son rapport). J'ai relancé une exécution
  indépendante de cette suite complète ; la session de travail a été interrompue pendant l'attente
  et, en relançant après reprise, un enchaînement d'appels d'outillage a lancé **trois exécutions
  concurrentes** de `manage.py test` (une simple + une seconde avec `--parallel=4`, lancée par erreur
  en pensant continuer d'attendre la première) sur une machine à 4 cœurs — ce qui a fortement
  ralenti les trois. **Mise à jour** : une des exécutions parallèles s'est terminée après la rédaction
  initiale de ce rapport (notification reçue après coup) : `Ran 441 tests in 675.186s — OK`, exit
  code 0, aucun échec. **Confirmation indépendante obtenue** : 441/441 OK, cohérent avec le résultat
  de dev-backend.

### 6. Recommandation sur « 0 vs jamais renseigné » (demandée explicitement par la mission)

Le choix actuel : une catégorie produite par la session sans ligne `BreadDisposal(REMAINING)`
associée ⇒ `qty_at_close = 0` (« intégralement écoulée »). C'est un comportement **acceptable comme
valeur par défaut d'affichage**, mais il ne distingue pas :
- « l'équipe a vérifié et il ne reste vraiment rien » (vrai zéro) ;
- « l'équipe a simplement omis de saisir la ligne REMAINING à la clôture » (zéro par défaut, pas
  forcément exact).

**Recommandation (non bloquante pour ce ticket)** : si `RESTE DU JOUR`/`RESTE DU HIER` doivent un
jour alimenter un calcul comptable fort (CM, contrôle de caisse, rapprochement avec le rapport papier
du client), envisager de distinguer les deux cas — par exemple un champ `is_declared` ou
`declared_at` sur `DailyBreadStockSnapshot`, ou le simple fait de n'avoir **aucune** ligne
`BreadDisposal` pour la session comme signal « inventaire non renseigné par cette équipe » plutôt
qu'un zéro silencieux. Aucune exigence fonctionnelle actuelle n'impose cette distinction ; à garder
en tête si des écarts apparaissent plus tard entre le rapport papier du client et l'affichage de
cette rubrique côté frontend (qui n'existe pas encore — aucun endpoint REST n'expose ces méthodes à
ce jour).

## Verdict

Aucun défaut trouvé sur les points de la mission :
- La source du solde déclaré (`BreadDisposal` de type `REMAINING` rattaché à la session) est bien
  utilisée, et non `BreadStock.qty_available`.
- `BreadStock.qty_available` n'est jamais lu ni modifié par ce correctif.
- Deux équipes clôturant le même jour créent bien deux lignes distinctes (`unique_together` incluant
  `team`, bornage de `record_snapshot` par construction à l'équipe de la session).
- `reste_du_hier` se réfère bien au dernier jour où **cette équipe précise** a clôturé, pas à un jour
  calendaire fixe ni à l'autre équipe — confirmé par mon scénario indépendant.

**BUG-118 passé à `VÉRIFIÉ` dans `docs/qa/REGISTRE_BUGS.md`** (fiche détaillée complétée avec la
section « Vérification — testeur-production, 2026-11-02 », tableau de suivi mis à jour).

## Fichiers consultés / concernés

- `D:\Projects\kiesse\backend\production\models.py` (lecture seule)
- `D:\Projects\kiesse\backend\production\views.py` (lecture seule)
- `D:\Projects\kiesse\backend\production\tests\test_daily_stock_snapshot.py` (lecture seule)
- `D:\Projects\kiesse\backend\production\migrations\0015_dailybreadstocksnapshot.py` (lecture seule)
- `D:\Projects\kiesse\backend\production\migrations\0016_alter_dailybreadstocksnapshot_options_and_more.py`
  (lecture seule)
- `D:\Projects\kiesse\backend\production\tests\test_zzz_verif_bug118_scratch.py` (créé puis supprimé
  — script de vérification temporaire, pas livré)
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (mis à jour : statut `VÉRIFIÉ`, fiche complétée)
- `D:\Projects\kiesse\docs\qa\rapports\dev-backend-2026-11-01-bug118-extension-equipe.md` (lu, pour
  recoupement)
- Aucun fichier applicatif modifié.
