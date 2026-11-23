# dev-backend (Dev B) - 2026-11-24 - B-6 / BUG-1117 : conversion du sel, export et synchronisation

Statut : BUG-1117 CORRIGÉ. Aucune migration (celle de dev-a, `production/0031`, est utilisée telle quelle).

## 1. Export Excel (`production/intrants_export.py`)
- Feuille SEL, colonnes M « RESTE/SAC » et N « RESTE/BOITE » : valeurs `declared_remaining_bags` /
  `declared_remaining_units` produites par `intrants_stats._serialize(row, salt_conversion(ctype), True)`
  (aucun recalcul), pour chaque ligne et pour TOTAUX. Cellule vide si le reste n'est pas déclaré.
  Formats `0.000` (sacs) et `0.0` (boîtes).
- Titre du stock du sel : « STOCK (g) » (unité du type de consommable).
- Commentaire « Conversion à venir » supprimé. Si `bag_weight_g`/`units_per_bag` sont null :
  cellules vides + commentaire « Conversion non configurée… » sur M5 et N5.

## 2. Synchronisation
Contrat du pull (`GET /api/sync/pull/`) : nouvelle clé de premier niveau `consumable_types` (toujours
présente), liste triée par code de `{code, bag_weight_g, units_per_bag}`.
`bag_weight_g` est une chaîne décimale à 3 décimales (ex. `"20000.000"`), `units_per_bag` un entier ou null.
Identique pour tous les nœuds, aucune donnée sensible.
- Choix « toujours présent » : un retour à « non configuré » au cloud descend aussi (liste vide impossible à
  distinguer d'un cloud ancien sinon). Un poste ancien ignore la clé inconnue. `TOP_KEYS`
  (`clients/tests/test_clients_v13.py`) reçoit `consumable_types` (seule modification de ce fichier).
- Poste : `apply_pull_response` -> `_apply_pulled_consumable_types` (sync_now.py).
  - Types EXISTANTS uniquement, jamais de création ; code/libellé/unité/is_active jamais touchés.
  - Paire cohérente : les deux valides ou les deux null. `bag_weight_g` ASCII, 3 décimales max, 0,001 à
    10 000 000 g ; `units_per_bag` entier ASCII 1 à 100 000 (via `core/numeric.py`). Booléens, listes,
    NaN/Infinity, chiffres non ASCII, paire incomplète : ligne ignorée, `log.warning`, jamais de 500.
  - Ligne sans aucune des deux clés : ignorée (absent n'est pas null).
  - Idempotent : aucune écriture (ni `updated_at`) si rien ne change.
  - Cloud ancien sans le bloc : aucun effet.

## 3. Fichiers modifiés
- backend/production/intrants_export.py
- backend/production/tests/test_dev_i4_intrants_export.py (test « SEL colonnes remplies » + test du cas non configuré)
- backend/sync/views.py (`_consumable_types_block`, ajout au payload du pull)
- backend/sync/management/commands/sync_now.py (`_apply_pulled_consumable_types`)
- backend/sync/tests/test_dev_b6_consumable_types.py (nouveau, 9 tests : pull porte les champs, application
  et idempotence, retour à non configuré, 20 valeurs invalides + entrées hostiles, journal, ligne invalide
  sans effet sur les autres, aucune création et champs hors conversion intacts, cloud ancien, indépendance du nœud)
- backend/clients/tests/test_clients_v13.py (TOP_KEYS seulement)
- docs/qa/REGISTRE_BUGS.md (ligne BUG-1117 insérée après BUG-1115, valeurs fictives uniquement)

Non touchés : intrants_stats.py, models.py, frontend, commissions/, migrations.

## 4. Résultats réels (log unique `$TEMP/t4.log`)
Commande : `manage.py test sync.tests.test_dev_b6_consumable_types production.tests.test_dev_i4_intrants_export
production.tests.test_intrants_stats_a production.tests.test_dev_i3_flour_month_stats
sync.tests.test_dev_i5_intrants_postes sync.tests.test_dev_b1030_node_settings clients.tests.test_clients_v13
sync.tests.test_verif_sync_v6 --noinput`
- Found 137 tests, résultat **OK** (0 échec, 0 erreur). (`test_verif_sync_v6` ajouté : il importe TOP_KEYS.)
- `makemigrations --check --dry-run` : **No changes detected**.
- Un premier passage avait 2 échecs de MON test (libellé du seed « Sel (g) » supposé « Sel » ; ligne sans clés
  traitée comme reset). Le second est un vrai défaut corrigé dans le code (clés absentes ignorées).
- Suite complète `manage.py test` NON relancée (hors des modules demandés).

## 5. Risques / remarques
- Un poste dont le type SALT n'existe pas ne reçoit rien (pas de création, voulu ; la migration 0010 sème les 4 types).
- Le pull ne fait descendre que la conversion, pas les autres champs de `ConsumableType` (limite connue BUG-1111).
- Le fichier d'export lit le stock du sel en grammes ; `declared_remaining` dans la feuille reste en g.
