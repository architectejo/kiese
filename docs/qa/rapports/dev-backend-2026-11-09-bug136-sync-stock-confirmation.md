# Rapport dev-backend — 2026-11-09 — BUG-136

## Ticket traité

**BUG-136** — La confirmation « stock de départ du jour » (BUG-133/134) n'ajustait jamais le
stock réel `BreadStock.qty_available`. Statut final : **CORRIGÉ** (non auto-vérifié, conformément
à CLAUDE.md §7 règle 3 — à passer `VÉRIFIÉ` par le testeur d'origine ou le coordinateur).

Fiche détaillée complète dans `docs/qa/REGISTRE_BUGS.md` (section "### BUG-136"), ligne de suivi
ajoutée au tableau récapitulatif juste après BUG-135.

## Cause

`DailyOpeningConfirmationView.post()` (`backend/production/views.py`) persistait
`DailyOpeningConfirmation`/`DailyOpeningConfirmationLine` (BUG-133/134), mais n'avait aucun effet
sur `BreadStock.qty_available` — le stock affiché sur l'écran « Production & Stocks » restait
inchangé après confirmation/correction dans la boîte modale.

## Décision client (clarification demandée, CLAUDE.md §7 règle 6)

Question posée : la confirmation doit-elle aussi mettre à jour le stock disponible ? Réponse du
client : **oui, toujours synchroniser**, y compris en no-op (valeur proposée validée telle
quelle) ou en ajustement (valeur corrigée), de façon traçable, à la manière d'un écart
manquant/excédent (CLAUDE.md §5.4). Appliqué tel que demandé, aucune ambiguïté résiduelle.

## Correction

1. **`backend/production/models.py`**
   - Nouveau champ `BreadStock.qty_adjusted` (`IntegerField`, `default=0`) : cumul des
     corrections MANUELLES décidées par un gérant, distinct des mouvements métier réels
     (`qty_produced`/`qty_received`/`qty_sent`/`qty_disposed`, non réutilisés — sémantique
     trompeuse sinon).
   - `qty_available` devient `produced + received - sent - disposed + adjusted`. Convention de
     signe documentée : positif = excédent constaté, négatif = manquant constaté.
   - `_adjust_bread_stock()` étendu avec `adjusted=0` (mise à jour `F()`, rétro-compatible pour
     tous les appelants existants qui ne passent pas ce paramètre).

2. **`backend/production/views.py::DailyOpeningConfirmationView.post()`**
   - Après la persistance de la confirmation (inchangée), pour chaque ligne soumise : verrouillage
     explicite de la ligne `BreadStock` (`get_or_create` puis `select_for_update().get(pk=...)`
     DANS la transaction atomique déjà ouverte), calcul du delta `qty_confirmed - qty_available
     courant`, application via `_adjust_bread_stock(node, bread_price, adjusted=delta)` si delta
     non nul.
   - Le delta est recalculé par rapport à l'état COURANT de `BreadStock` à chaque soumission
     (jamais par rapport à une ancienne confirmation mémorisée) → pas de double application en
     cas de resoumission le même jour.
   - `log_activity` appelé pour chaque ajustement effectif (nœud, équipe, catégorie, avant/après,
     delta, utilisateur). Pas de `create_notification` ajoutée : aucun pattern de seuil d'alerte
     existant pertinent trouvé pour ce cas précis, et la consigne demandait de ne pas
     sur-ingénierier — un `log_activity` systématique est jugé suffisant pour ce ticket.
   - Réponse POST enrichie d'un champ additif `stock_adjustments` (liste
     `{bread_price_id, before, after, delta}`).

3. **`backend/production/serializers.py::BreadStockSerializer`**
   - `qty_adjusted` ajouté aux champs exposés (lecture seule), purement additif.

4. **Migration** `backend/production/migrations/0020_breadstock_qty_adjusted.py` — `AddField`
   simple, `default=0`, aucune donnée existante à migrer. **Appliquée** sur la vraie base de dev
   `backend/db.sqlite3` (`python manage.py migrate production` → `Applying
   production.0020_breadstock_qty_adjusted... OK`).

## Non-régression vérifiée

- `DailyBreadStockSnapshot.reste_du_hier()`/`_build_daily_closure_report` (BUG-118/120/135) :
  logique de calcul intouchée — vérifié par les tests existants
  `test_confirmed_value_overrides_reste_du_hier_in_daily_closure_report` et
  `test_confirmed_reste_du_hier_matches_auto_derived_in_total_du_jour`, toujours verts.
- Recensement (`grep qty_available`/`_adjust_bread_stock`) de tous les consommateurs de
  `BreadStock.qty_available` : ventes (déstockage à la livraison, `sales/views.py`), production
  (fournée), transferts inter-boulangeries, disposals. Tous passent par la même propriété
  `qty_available`, désormais `+ qty_adjusted` (0 par défaut, donc strictement neutre pour tout
  nœud/catégorie sans confirmation BUG-136). Aucun de ces appelants n'écrit lui-même dans
  `qty_adjusted`.
- Idempotence : `test_resubmission_does_not_double_apply_adjustment` (confirmer 120→100 puis
  100→90 le même jour amène le stock à 90, pas 80).
- Équipe B voit l'ajustement fait par équipe A : `test_second_team_get_reflects_first_team_adjustment`.
- Isolation par catégorie et par nœud : `test_adjustment_does_not_affect_other_category_stock`,
  `test_adjustment_does_not_affect_other_node_stock`.

## Tests

Nouveaux tests (échouaient avant correctif, passent après) dans
`backend/production/tests/test_daily_opening_confirmation.py` :
- `test_post_with_corrected_value_adjusts_real_stock_exactly`
- `test_post_validating_proposed_value_as_is_is_a_stock_noop`
- `test_post_with_higher_value_than_proposed_increases_real_stock`
- `test_resubmission_does_not_double_apply_adjustment`
- `test_second_team_get_reflects_first_team_adjustment`
- `test_adjustment_does_not_affect_other_category_stock`
- `test_adjustment_does_not_affect_other_node_stock`

Résultats :
- `python manage.py test production.tests.test_daily_opening_confirmation` → **30 tests, OK**.
- `python manage.py test production sales finance` → **192 tests, OK**.
- `python manage.py test` (suite complète du dépôt) → **534 tests, OK**.
- `python manage.py makemigrations --check --dry-run` → **« No changes detected »**.
- Migration `0020_breadstock_qty_adjusted` **appliquée** sur la vraie base de dev
  `backend/db.sqlite3` (`python manage.py migrate production`).

## Impact API / frontend (additif, non cassant)

- `GET /api/production/breadstock/...` (`BreadStockSerializer`) expose un nouveau champ
  `qty_adjusted` (lecture seule). Aucun champ existant renommé/retiré.
- `POST /api/production/opening-confirmation/` renvoie en plus `stock_adjustments` (vide si aucun
  ajustement). Additif — le frontend existant (BUG-134, `OpeningStockConfirmationModal.tsx`)
  continue de fonctionner sans modification requise.
- **Sous-ticket proposé pour `dev-frontend`** (non implémenté ici, hors périmètre backend) :
  afficher un message « le stock disponible a été ajusté de X à Y » dans
  `frontend/src/components/production/OpeningStockConfirmationModal.tsx` en consommant
  `stock_adjustments` de la réponse POST, et/ou afficher `qty_adjusted` sur l'écran
  « Production & Stocks » (`BreadStockSerializer`) pour la traçabilité visuelle de l'écart.

## Fichiers modifiés

- `backend/production/models.py`
- `backend/production/views.py`
- `backend/production/serializers.py`
- `backend/production/migrations/0020_breadstock_qty_adjusted.py` (nouveau)
- `backend/production/tests/test_daily_opening_confirmation.py`
- `docs/qa/REGISTRE_BUGS.md` (ouverture et clôture de la fiche BUG-136)

## Ambiguïtés signalées

Aucune ambiguïté résiduelle non tranchée — la seule question métier réelle (faut-il synchroniser
le stock ?) avait déjà été posée explicitement au client par la tâche confiée, et tranchée avant
le début de la correction.

## Risques / points d'attention pour la vérification

- Vérifier que `stock_adjustments` (nouveau champ de réponse) et `qty_adjusted` (nouveau champ
  serializer) ne cassent aucun test e2e/Playwright existant qui vérifierait une forme stricte de
  réponse JSON (recherche rapide suggère qu'aucun test frontend actuel ne fait d'assertion stricte
  sur la forme exacte de ces réponses, mais à confirmer côté `testeur-e2e`/`dev-frontend`).
- Le sous-ticket `dev-frontend` proposé ci-dessus n'a pas été ouvert formellement dans le registre
  (laissé à l'appréciation du coordinateur) — je le mentionne explicitement ici au cas où il
  faudrait lui attribuer un numéro `BUG-137`.
