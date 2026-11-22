# architecte-sync — 2026-11-22 (B2) — sync de ConsumableInventory (BUG-386)

## Constat
`ConsumableInventory` (UUID) et `ConsumableCount` (PK entière locale, sans `is_synced`) n'étaient pas dans `PUSH_HANDLERS` : tout lot les contenant était rejeté « modèle non supporté en V1 ».

## Réalisation
- `sync/services.py` : `PUSH_MODEL_ORDER` (+ `production.ConsumableInventory`, puis `production.ConsumableCount`, après `ConsumableMovement`), handlers `_push_consumable_inventory` et `_push_consumable_count`, utilitaires `_strict_uuid`, `_strict_decimal` (Decimal fini, 3 décimales max, 10 chiffres), `_strict_date`.
- `sync/management/commands/sync_now.py` : le lot sortant contient les inventaires `is_synced=False` du nœud et leurs lignes (`inventory` = UUID). Les lignes suivent leur en-tête (même précédent que `BreadTransferLine`), rejeu idempotent.
- Aucun changement de schéma (`makemigrations --check` : aucun changement). Pas de modification de `desktop/`, du frontend ni de `COMMUNICATION_A_B.md`.

## Règles
- Inventaire : id UUID strict ; `node` et `node_origin` doivent égaler le nœud authentifié (sinon REJETÉ) ; `inventory_date` ISO ; `comment` texte. Existant : seul `comment` modifiable (comme côté API) ; nœud tiers => REJETÉ + conflit `NON_PROPRIETAIRE`.
- Unicité (nœud, jour) : second inventaire d'un autre id pour le même jour => REJETÉ + `SyncConflictLog` `CONSUMABLE_INVENTORY_DUPLICATE` (règle du module : pas d'écrasement silencieux, consultable au siège).
- Ligne `ConsumableCount` : identité cross-nœud = clé naturelle (nœud, type, date, inventaire, quantités), jamais la PK locale. `inventory` OPTIONNEL (ancien payload sans ce champ accepté, `inventory=NULL`). Si présent : inventaire connu (sinon « dépendance manquante : inventory »), du même nœud, même date. `gap == physique − système` exigé. `counted_by` non transmis (utilisateurs non partagés).

## Limite connue
Les comptages historiques sans inventaire (`inventory` NULL) n'ont pas de `is_synced` : `sync_now` ne les remonte pas automatiquement (le handler Cloud les accepte si un nœud les envoie). À trancher avec le coordinateur si nécessaire (ajout d'un champ `is_synced` = migration).

## Résultats
- `sync/tests/test_consumable_inventory_sync.py` : 12 tests ; sans les changements source : 7 échecs + 2 erreurs ; avec : OK.
- `manage.py test sync` : 109 tests OK. `makemigrations --check --dry-run` : No changes detected. `manage.py check` : 0 problème.
