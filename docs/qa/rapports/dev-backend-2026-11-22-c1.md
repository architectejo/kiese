# dev-backend 2026-11-22 (c1) — BUG-386 : consommables, vue globale direction

Ticket : BUG-386 (CORRIGÉ backend). Frontend : BUG-387 (OUVERT). remarque.md l.472 reste `[]`.
Migration : `production/0028_bug386_consumable_inventory` (modèle `ConsumableInventory`, FK `ConsumableCount.inventory`).
Tests : `production/tests/test_global_consumables_direction.py` (16 OK) ; + `production.tests.test_consumables`, `finance.tests`,
`core.tests.test_verif_isolation_a_c`, `core.tests.test_permissions_regression_2026_11_19` OK. `makemigrations --check` : aucun changement ; `manage.py check` : OK.
Suite complète non lancée (demande du coordinateur).

Conventions : quantités = chaînes décimales à 3 décimales (`"12.500"`). Erreurs : `{"detail": "..."}` en français.
Stock direction = `ConsumableStock` du nœud technique `SIEGE` (alimenté par `POST /api/production/movements/` avec le stock du SIEGE, ENTRY, par un compte siège).

## 1. GET /api/production/consumables/global/  (ADMIN, DIRECTION, COMPTABLE ; sinon 403)
```json
{
 "types": [{"code":"FLOUR","label":"Farine","unit":"sac"}],
 "direction": {"node": 9, "code": "SIEGE", "stocks": {"FLOUR": "100.000", "YEAST": "0.000"}},
 "nodes": [{"node": 1, "code": "K1", "name": "...", "stocks": {"FLOUR": "5.000"},
            "last_inventory": {"id": "<uuid>", "date": "2026-11-22", "has_comment": true} }],
 "totals_bakeries": {"FLOUR": "12.000"},
 "totals_group": {"FLOUR": "112.000"}
}
```
`last_inventory` = null si aucun inventaire. Seuls les types actifs apparaissent ; SIEGE n'est pas dans `nodes`.

## 2. POST /api/production/consumables/dispatch/  (ADMIN, DIRECTION ; COMPTABLE/gérant/facturier/livreur : 403)
Corps : `{"consumable_type":"FLOUR","note":"optionnel","allocations":[{"node":1|"K1","quantity":"10"},{"node":"K2","quantity":"2.5"}]}`
201 : `{"consumable_type","unit","total_sent":"12.500","direction_remaining":"87.500","sent":[{"node":1,"code":"K1","quantity":"10.000"}]}`
400 : type inconnu/inactif, allocations vides, boulangerie inconnue/SIEGE/inactive/en double, quantité <= 0, non numérique, NaN, > 3 décimales,
**stock direction insuffisant** (rien n'est écrit). Atomique (tout ou rien). Crée un EXIT (SIEGE) et un ENTRY (boulangerie) par ligne, `log_activity`, notification par boulangerie.

## 3. Inventaire physique — /api/production/inventories/
- `POST` (GERANT rattaché à une boulangerie uniquement ; ADMIN/DIRECTION/COMPTABLE/facturier/livreur : 403) :
  `{"comment":"optionnel","lines":[{"consumable_type":"FLOUR","physical_quantity":"4.5","notes":"optionnel"}]}`.
  Nœud = celui du gérant (`node` du corps ignoré), date = jour local du serveur. 201 = objet inventaire (ci-dessous).
  400 si déjà saisi aujourd'hui (« L'inventaire physique du jour a déjà été saisi... »), lignes vides/doublons/type inconnu/quantité négative ou invalide. Quantité 0 acceptée.
  Écart par ligne : `gap = physique - système` (le stock n'est pas modifié).
- `PATCH /<uuid>/` : uniquement `{"comment":"..."}` (gérant du nœud, tout moment) ; tout autre champ => 400 ; `PUT` => 405. Autre boulangerie => 404.
- `GET /today/` (gérant) : `{"date","done":bool,"inventory":{...}|null}` — sert à désactiver le formulaire.
- `GET /` (gérant : son nœud ; siège : tous, filtres `?node=<id|code>` `?date=AAAA-MM-JJ`) : liste sans lignes. `GET /<uuid>/` : détail avec lignes.
- `GET /node/<id|code>/[?date=]` (ADMIN, DIRECTION, COMPTABLE, gérant de ce nœud seulement ; autre => 404; facturier/livreur 403) :
  `{"node","code","name","inventory":{...}|null,"history_dates":["2026-11-22",...]}` (dernier inventaire ou celui de `date`).
Objet inventaire : `{"id","node","node_code","node_name","inventory_date","comment","recorded_by","recorded_by_display","created_at","updated_at","lines_editable":false,
"lines":[{"id","consumable_type","consumable_type_display","unit","system_quantity","physical_quantity","gap","notes"}]}`.

## Autres changements / risques
- `/api/production/counts/` : les lignes liées à un inventaire ne sont plus modifiables/supprimables (400) et la création à la main est refusée le jour d'un inventaire (400).
- `finance/views.py` : les sorties du nœud SIEGE sont exclues du coût de consommation (sinon un envoi direction serait compté en consommation).
- Le commentaire reste modifiable après le jour de saisie (choix ; à confirmer client). Date d'inventaire = date calendaire du serveur (pas la date de relève).
- Synchronisation : `ConsumableInventory` n'est pas encore enregistré dans `sync/` (à traiter avec architecte-sync si nécessaire).
- Entrée de stock direction : pas d'endpoint dédié, utiliser les mouvements existants sur le stock SIEGE (le frontend devra proposer le stock SIEGE ; `_ensure_stock_accounts` ne crée pas les comptes SIEGE, inactif ; `dispatch` les crée à la demande).
