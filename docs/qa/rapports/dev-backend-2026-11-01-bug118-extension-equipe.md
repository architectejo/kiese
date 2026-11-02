# Rapport dev-backend — 2026-11-01 — BUG-118 (extension équipe A/B)

## Contexte

Extension du ticket **BUG-118** (`docs/qa/REGISTRE_BUGS.md`, fiche détaillée à la ligne ~10038).
Le correctif initial du même jour avait ajouté `DailyBreadStockSnapshot` et les méthodes
`reste_du_jour`/`reste_du_hier`, en signalant au coordinateur une ambiguïté : dans
`data_kiese/DOC 01- RAPPORT  BOULANGERIES AOUT  2026.xlsx` (feuille ZADIM), une seconde chaîne
parallèle de `RESTE DU HIER` ne suivait pas `reste_du_hier(jour N) = −reste_du_jour(jour N-1)`,
avec l'hypothèse que les deux chaînes correspondaient aux équipes A et B.

**Le client a confirmé cette hypothèse le 2026-11-01** : `RESTE DU HIER` dépend bien de l'équipe
(A/B, CLAUDE.md §5.2) qui a clôturé en dernier.

## Ticket traité

- **BUG-118** (extension) — `docs/qa/REGISTRE_BUGS.md` — Statut : **CORRIGÉ** (reste à vérifier par
  un testeur pour l'ensemble correctif initial + extension, règle CLAUDE.md §7).

## Point de conception (décision prise et documentée)

- `BreadStock.qty_available` reste un solde **GLOBAL** partagé par nœud+catégorie (un seul tas de
  pains physiques, peu importe l'équipe qui vend) — **non modifié**, conformément à l'instruction
  explicite de ne pas y toucher.
- Ce qui devient « par équipe » est une donnée **déclarative** distincte : le solde que chaque
  équipe rapporte comme « stock restant à vendre » à SA propre clôture de session.
- Source de cette quantité par équipe : les dispositions `BreadDisposal` de type `REMAINING`
  rattachées à la session qui clôture (`session` FK déjà existante sur `BreadDisposal`). Ces
  dispositions ne touchent jamais `BreadStock` (`BreadDisposalViewSet.perform_create` les exclut
  explicitement de l'ajustement de stock, commentaire « REMAINING breads are not disposed — they
  stay in stock and roll into the next batch ») — c'était déjà, avant ce ticket, le champ exact
  utilisé par le gérant pour déclarer un reste par catégorie à la clôture d'UNE session précise
  (donc par équipe, puisque `ProductionSession` a `node+team+date` unique). Une catégorie produite
  par la session sans ligne `REMAINING` associée est traitée comme intégralement écoulée par cette
  équipe (valeur 0, pas une absence de valeur).
- `_compute_reconciliation`/`_build_reconciliation_querysets` (agrégation nœud/date tous-équipes,
  utilisée par `reconciliation` et par `close()` pour le recoupement production/ventes/dispositions)
  **n'ont pas été modifiées** : elles répondent à une question différente (écart théorique du jour,
  tous-équipes confondues) qui reste pertinente telle quelle.

## Modifications

### `backend/production/models.py`
- `DailyBreadStockSnapshot` :
  - Nouveau champ `team` (choix repris de `ProductionSession.Team`, A/B).
  - `unique_together` étendu : `[node, bread_price, date, team]`.
  - `reste_du_jour(node, bread_price, date, team)` : filtre maintenant sur `team`.
  - `reste_du_hier(node, bread_price, date, team)` : cherche le dernier snapshot antérieur à `date`
    **pour cette équipe** (pas forcément la veille calendaire — une équipe qui n'a pas clôturé un
    jour donné garde son solde inchangé jusqu'à sa prochaine clôture). Retourne `0` si l'équipe n'a
    jamais clôturé avant `date` pour ce nœud/catégorie.
  - `record_snapshot(session)` : signature changée (prend la `ProductionSession` qui clôture, plus
    `node`/`date` séparés). Calcule, pour chaque catégorie produite par la session et/ou avec un
    reste `REMAINING` déclaré, la somme des quantités `REMAINING` de CETTE session, et fait un
    upsert sur `(node=session.node, bread_price, date=session.date, team=session.team)` — borné par
    construction à l'équipe de la session, ne peut jamais écraser le snapshot d'une autre équipe
    clôturant le même jour.
- Docstring du modèle entièrement révisé : documente la confirmation client, la distinction
  stock physique global / solde déclaratif par équipe, et la nouvelle formule `reste_du_hier`.

### `backend/production/views.py`
- `ProductionSessionViewSet.close()` : l'appel `DailyBreadStockSnapshot.record_snapshot(session.node,
  session.date)` devient `DailyBreadStockSnapshot.record_snapshot(session)`.

### Migration
- `backend/production/migrations/0016_alter_dailybreadstocksnapshot_options_and_more.py` (nouvelle,
  générée par `makemigrations`) : `AlterModelOptions` (ordering), `AlterUniqueTogether` (retrait puis
  ajout avec `team`), `AddField(team, default='A', preserve_default=False)`, `AlterField(qty_at_close,
  verbose_name)`. Migration standard, aucune donnée réelle perdue : le modèle `DailyBreadStockSnapshot`
  a été introduit par la migration `0015` plus tôt le même jour (correctif initial de ce même ticket)
  et ne contient, à ce stade, que des lignes créées par les tests automatisés — aucune donnée de
  production réelle n'existe pour ce modèle. `backend/data_kiese/` et `db.sqlite3` n'ont pas été
  touchés.

### Tests
- `backend/production/tests/test_daily_stock_snapshot.py` : entièrement révisé (7 tests, tous sans
  `@expectedFailure` — pas de test préexistant à retirer d'`@expectedFailure`, le module n'en avait
  jamais eu). Points clés :
  - `test_close_creates_snapshot_matching_declared_remaining` : la clôture crée un snapshot par
    équipe égal au solde `REMAINING` déclaré, et vérifie explicitement que `BreadStock.qty_available`
    (global) n'est pas affecté par cette dimension équipe.
  - `test_second_closure_same_day_keeps_separate_team_snapshots` : deux clôtures le même jour
    (équipe A puis B) produisent **deux** lignes `DailyBreadStockSnapshot` distinctes, chacune avec
    sa propre valeur — remplace l'ancien test qui attendait un upsert écrasant.
  - `test_reste_du_hier_is_negative_of_previous_snapshot_same_team` : formule de base par équipe.
  - `test_reste_du_hier_is_zero_on_first_day_of_activity` : cas limite inchangé, par équipe.
  - `test_reste_du_hier_skips_days_with_no_closure_for_that_team` : **scénario de l'ambiguïté
    résolue** — équipe A clôture le 10 et le 11, équipe B clôture seulement le 10 ;
    `reste_du_hier` de B au 12 = `−reste_du_jour` de B au 10 (son dernier jour clôturé), tandis que
    `reste_du_hier` de A au 12 = `−reste_du_jour` de A au 11 — les deux équipes ne se mélangent
    jamais.
  - `test_reste_du_jour_is_none_when_not_yet_closed` : inchangé, par équipe.
  - `test_remaining_disposal_never_adjusts_global_bread_stock` : non-régression explicite sur le
    comportement déjà en place (`REMAINING` ne décrémente jamais le stock physique global).

## Résultats des tests

- `backend/.venv/Scripts/python.exe manage.py test production` → **45/45 OK**.
- `backend/.venv/Scripts/python.exe manage.py test` (suite complète) → **441/441 OK**.
- `backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → « No changes
  detected ».
- `backend/.venv/Scripts/python.exe manage.py check` → « System check identified no issues
  (0 silenced) ».

## Impact API / frontend

Aucun. Toujours aucun endpoint REST dédié exposé pour `reste_du_jour`/`reste_du_hier` (méthodes de
classe backend uniquement, comme pour le correctif initial) — pas de ticket `dev-frontend` ouvert.

## Registre

`docs/qa/REGISTRE_BUGS.md` :
- Ligne du tableau récapitulatif (BUG-118) mise à jour pour mentionner la confirmation client et
  l'extension équipe.
- Fiche détaillée BUG-118 complétée : ambiguïté explicitement levée (« confirmée par le client le
  2026-11-01 »), section « Extension — dev-backend, 2026-11-01 » ajoutée avec cause, fichiers
  modifiés, tests de non-régression et résultats. Statut final laissé à **CORRIGÉ** (pas
  `VÉRIFIÉ`) : un testeur doit vérifier l'ensemble du ticket (correctif initial + cette extension)
  avant de le passer à `VÉRIFIÉ`, conformément à CLAUDE.md §7.

## Fichiers modifiés

- `D:\Projects\kiesse\backend\production\models.py`
- `D:\Projects\kiesse\backend\production\views.py`
- `D:\Projects\kiesse\backend\production\migrations\0016_alter_dailybreadstocksnapshot_options_and_more.py`
  (nouveau)
- `D:\Projects\kiesse\backend\production\tests\test_daily_stock_snapshot.py`
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md`
- `D:\Projects\kiesse\docs\qa\rapports\dev-backend-2026-11-01-bug118-extension-equipe.md` (ce
  rapport)

Aucun autre fichier n'a été touché (conformément au périmètre fixé par la mission).

## Risques / points d'attention pour le testeur

1. **Attribution par `BreadDisposal.REMAINING`** : le choix de source retenu pour le solde déclaré
   par équipe repose sur une donnée déjà saisie par le gérant à la clôture (REMAINING), et non sur
   une nouvelle saisie dédiée. Si en pratique les gérants ne saisissent pas systématiquement de
   ligne `REMAINING` par catégorie à chaque clôture, le snapshot de cette catégorie pour cette
   équipe vaudra 0 (« intégralement écoulée ») même si ce n'est pas rigoureusement exact — à vérifier
   avec des données réelles de clôture (`data_kiese/`, sans jamais les copier dans des fixtures de
   test) une fois le testeur en mesure de recouper avec `auditeur-comptable`.
2. Le défaut `'A'` posé par la migration pour les lignes déjà existantes (uniquement des lignes de
   test à ce stade) est arbitraire — si une vraie clôture avait déjà créé un snapshot avant cette
   extension (peu probable, le modèle datant du même jour), son équipe réelle serait perdue. À
   signaler si un environnement avec des données plus anciennes est utilisé pour la vérification.
