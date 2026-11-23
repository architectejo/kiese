# Architecte-sync d46 (2026-11-23) — BUG-997

Correctif dans `backend/sync/views.py::_store_mirrors` : chaque marqueur [envoyé, reçu] est borné par la ligne cloud
(`quantity_sent`, `quantity_received` or 0), lue après `process_push_batch` (donc lignes du même lot incluses). Ligne ou transfert inconnu
ou valeur hors borne : la catégorie est ignorée (non stockée), un `SyncConflictLog` `MIRROR_OUT_OF_BOUNDS` (une ligne ouverte par nœud/transfert,
occurrences incrémentées) est ouvert, le lot n'est pas rejeté. Monotone : max(ancien, nouveau), sauf si l'ancien dépasse la borne actuelle
(rétablissement, ex. résolution d'écart réduisant la ligne). Pas de migration.

Tests : test_verif_production_a15_v15 (décorateur @expectedFailure retiré), a14_v14, test_sync_transfers_d43, a13_v13, sync.test_verif_sync_v5 : 90 OK ;
makemigrations --check : rien. Log : $TEMP/d46.log.
