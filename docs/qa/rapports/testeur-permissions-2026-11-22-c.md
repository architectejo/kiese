# Rapport testeur-permissions, 2026-11-22 (lot c5)

Base : branche dev-c, 2fcfa0e. Tests : `backend/core/tests/test_verif_c5_routes_noeuds_c.py` (67 tests, 8 `@expectedFailure` référencés). Données fictives. Aucun code applicatif modifié.

## Rejeu de la matrice existante
`test_verif_matrice_c`, `test_verif_isolation_a_c`, `test_verif_params_invalides_c`, `test_bug517_523c_node_delete_guards`, `test_verif_bug414_c` : 114 tests, OK (1 échec attendu : BUG-507, hors périmètre). L'énumération automatique de la matrice (anonyme + 6 rôles sur toutes les routes `/api/`) couvre déjà les nouvelles routes : aucun 5xx, anonyme 401, hiérarchie respectée.

## Verdicts
| Ticket | Verdict | Remarque |
|---|---|---|
| BUG-517 | VÉRIFIÉ | DELETE SIEGE refusé (400) pour ADMIN/DIRECTION, 403 autres rôles, 401 anonyme. Contournement par renommage : BUG-564 |
| BUG-523 | VÉRIFIÉ | nœud avec message dans le fil NODE : 400, message conservé ; fil vide : 204 ; nœud avec historique : 400 (pas de 500) |
| BUG-530 | VÉRIFIÉ | `history` : `node`/`months` illisibles, géants, négatifs, 0 -> jamais 500 (7 comptes) ; pas de fuite K2 |
| BUG-531 | VÉRIFIÉ | `bassins` : gérant K1 avec `node=<K2>` (pk, code, variantes `" 2"`, `+2`) ne voit rien de K2 ; compte sans boulangerie -> vide ; 13 valeurs `node`/`month`/`year` illisibles -> jamais 500 |
| BUG-532 | VÉRIFIÉ | `deficit_report` : 2**31, 2**63, 30 chiffres, ZZZ, 0, -1, 1e3 -> pas de 500 ; gérant ne choisit pas K2. Balayage de toutes les routes GET avec `node/from_node/to_node/client` géant : seul reste treasury journal/savings (BUG-560) |
| BUG-526 à 529 | VÉRIFIÉ (déjà VÉRIFIÉ par testeur-production, rejoué avec 33 variantes x 7 comptes) | entiers géants, dates 0000-00-00, `%00`, 2026-02-30 : 400 `{detail}` ; reste : run_check corps liste (BUG-561) |
| BUG-503/504/505/506/522 | confirmés (déjà VÉRIFIÉS) | rejeu : `node` forgé (pk, code, dict, liste), stock étranger, PATCH d'un mouvement vers un stock étranger, `flour_history?node=`, comptes sans boulangerie (lecture vide, écritures 400/403, création de compte sans nœud refusée, détachement refusé), PATCH/PUT de transferts (10 corps x 2 gérants x 2 méthodes), tiers/facturier/livreur/sans nœud : tous refusés, aucune écriture |

## Extension aux nouvelles routes (BUG-386, versements, envoi direct)
- `production/consumables/global/` : ADMIN/DIRECTION/COMPTABLE 200 ; gérant, facturier, livreur, comptes sans nœud 403 ; anonyme 401 ; POST/PUT/PATCH/DELETE 403/405.
- `consumables/dispatch/` : ADMIN/DIRECTION seuls (201) ; tous les autres 403/401 et le stock SIEGE reste intact ; 27 corps invalides -> 400 (NaN, Infinity, négatif, 4 décimales, booléen, liste, dict, doublon, SIEGE, inactif, stock insuffisant, ligne 2 invalide : rien ne bouge) ; 3 envois de 20 sur 50 : 2 acceptés, stock 10. Défauts : BUG-562 (`1e400`), BUG-541 (`node: true`, existant).
- `inventories` : création = GERANT rattaché uniquement (ADMIN/DIRECTION/COMPTABLE/facturier/livreur/sans nœud 403) ; `node`, `recorded_by`, `inventory_date` forgés ignorés ; liste/détail/PATCH/`node/<ref>` d'un autre nœud -> 404 (pk, code, casse) ; `?node=` ignoré pour gérant ; SIEGE masqué ; PATCH limité à `comment` (400 pour tout autre champ) ; PUT/DELETE 405 ; lignes non modifiables via `counts` ni contournables par un comptage le même jour ; paramètres illisibles (`node/<géant>`, dates) jamais 500.
- `treasury/closures/versements/` : gérant limité à son nœud, `?node=<K2>` (pk/code/casse) 403, sans nœud : liste vide et 403 sur `?node=`, facturier/livreur 403, écriture 403/405 ; aucune donnée K2 dans les réponses. Défaut : BUG-563 (ligne SIEGE).
- `production/transfers/send/` : facturier/livreur 403, ADMIN/DIRECTION/COMPTABLE 400 (pas de nœud), `from_node`, `initiated_by`, `transfer_status`, `node` forgés ignorés, stock étranger intact, 28 corps invalides jamais 500. Défaut : BUG-540 (SIEGE / inactif accepté, existant).

## Tickets ouverts (BUG-560 à 564, tous Mineur, aucune fuite inter-nœuds ni élévation de droits)
- BUG-560 : treasury journal/savings `?node=` invalide -> 500 ; 2e rapport facturier le même jour -> 500.
- BUG-561 : `run_check` avec corps liste -> 500.
- BUG-562 : `dispatch` quantité `1e400` -> 500.
- BUG-563 : `versements` liste le nœud SIEGE.
- BUG-564 : SIEGE renommable puis supprimable (contourne BUG-517).
- Existants confirmés : BUG-540, BUG-541.

## Registre
Passés à VÉRIFIÉ : 517, 523, 530, 531, 532 (lignes et fiches). Lignes 503-506, 522, 526-529 déjà VÉRIFIÉES, non modifiées.
