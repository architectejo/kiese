# Architecte-sync d48 (2026-11-23) : BUG-1000 à 1003 corrigés

- BUG-1000 : `TransferMirror.peak` (migration 0005) = plus haute borne [envoyé, reçu] vue par le cloud (au push et au pull). Un poste qui n'a pas tiré la dernière modification (`node.last_sync < transfer.updated_at`) peut pousser un marqueur jusqu'à cette valeur historique ; au-delà : MIRROR_OUT_OF_BOUNDS comme avant.
- BUG-1001 : le pull borne le marqueur descendu à min(marqueur, ligne cloud actuelle) ; lignes inconnues et marqueurs vides non descendus.
- BUG-1002 : borne d'envoi = 0 tant que le transfert n'est pas RESPONDED/DISPUTED/CONFIRMED (`_effective_line_bounds`).
- BUG-1003 : le cloud (push de statut) et la copie locale (pull) font avancer `updated_at` avec le statut ; le pull pose l'`updated_at` du cloud sur la copie locale : date de comptage identique des deux côtés (sync/services.py, sync_now.py). `production/views.py` non modifié.
- Observation SOLD_DISCOUNT au push : NON aligné sur REST. Des tests existants créent des BreadDisposal SOLD_DISCOUNT par push (test_verif_production_a8/a9/a10, sync/test_sync_bug004_extension). À trancher par le coordinateur.
- Tests : décorateurs @expectedFailure retirés (a16). 121 tests (a16, a15, a14, a13, d43, d15_demande4, daily_closure_report, verif_sync_v5) OK ; makemigrations --check propre. Log : $TEMP/d48.log. Rien commité.
