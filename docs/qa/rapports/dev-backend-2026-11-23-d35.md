# Dev B d35 - BUG-964 a 968 (sync des transferts) - 2026-11-23

Tests : a12_v12, a11, a10, a9, a8, test_transfers, envoi_direct, sync v5/v4/bug004 : 256 tests OK ; makemigrations --check : aucun changement. Les 5 `@expectedFailure` de a12_v12 sont supprimes (assertions inchangees).

## Contrat pull (`GET /api/sync/pull/`)
Nouvelles cles `transfers` et `transfer_lines` : tous les `BreadTransfer` dont le poste est emettrice OU receptrice (sauf CONFIRMED/CANCELLED inactifs depuis > 30 jours), sans curseur (idempotent).
- transfert : id, from_node, to_node (codes), bread_price, quantity_sent, quantity_received, transfer_status, flow, notes, node_origin, updated_at.
- ligne : transfer, bread_price, quantity_sent, quantity_received.
`apply_pull_response` : cree le transfert inconnu (`is_synced=True`, statut du cloud) et ses lignes (get_or_create sur transfer+bread_price) ; sur un transfert connu, applique seulement une avance de statut stricte et seulement si la copie locale n'a pas de modification non poussee ; jamais de regression ; terminaux intouches. AUCUN mouvement de stock (les miroirs restent produits par send/respond/confirm_reception REST) : pas de double mouvement.

## Contrat export (BUG-965)
`build_outbound_payload` : transferts `is_synced=False` ou `node_origin`, `from_node` ou `to_node` = poste. Les restrictions de role du push (874/888/891) restent.

## Push
- BUG-966 : `DISPUTED -> CONFIRMED` accepte pour la receptrice et l'emettrice, a condition que toutes les lignes cloud n'aient plus d'ecart (recue non nulle et egale a l'envoyee) ; sinon rejet motive. Cote poste, l'ordre du lot (transfert avant lignes) fait que la premiere tentative peut etre rejetee puis acceptee au cycle suivant.
- BUG-967 : quantites a la creation normalisees en entiers ('5.0', '1e1', 5.0 -> 5), rejet motive sinon.
- BUG-968 : `BreadDisposal` : quantity / unit_price_sold normalises par `_sync_int`, rejet motive (plus de TypeError).

## Risques / limites
- Resolution `resolve_dispute` ALIGN_ON_RECEIVED/ALIGN_ON_SENT faite par l'emettrice : la modification de `quantity_sent`/`quantity_received` par l'emettrice n'est pas acceptee par le push de lignes (regle BUG-788/920) ; le cloud ne se debloque que si la receptrice repousse des lignes alignees. Le siege (jeton SIEGE) n'est pas partie du transfert : ses resolutions ne passent pas par push. A traiter dans un ticket separe si le client le souhaite.
- Un transfert CONFIRME ailleurs descendu vers un poste dont la copie locale est RESPONDED met le statut a jour sans crediter le stock local (cas non nominal).
- Fichiers : sync/services.py, sync/views.py, sync/management/commands/sync_now.py, production/tests/test_verif_production_a12_v12.py. Pas de migration.
