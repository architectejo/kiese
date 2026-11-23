# dev-backend d40 (2026-11-23) : BUG-981 à 984 (sync) -> CORRIGÉ

Fichiers : `backend/sync/services.py`, `backend/sync/views.py` (PullView), `backend/sync/management/commands/sync_now.py`, test `backend/treasury/tests/test_verif_tresorerie_c14_v13.py` (décorateurs `@expectedFailure` retirés, assertions inchangées). Aucune migration. `treasury/views.py` non modifié.

- **983** : `_push_cash_closure` lève le rejet d'une clôture infirmée non confirmée quand le contenu est CORRIGÉ (billetage ou totaux différents, règle REST BUG-034/860) ; un simple rejeu ne le lève pas ; jamais de confirmation par le poste (BUG-971) ; journalisé (`log_activity`). `PullView` renvoie `closures` (nœud du jeton uniquement, 60 jours : id, date, is_validated, is_rejected, rejection_reason, is_paid) ; `apply_pull_response` applique l'état par `update()` sans toucher aux montants, ignore l'infirmation si une resoumission locale est en attente de push.
- **981** : horodatage poussé > 5 min dans le futur : l'édition reste appliquée (non-empoisonnement conservé) mais un conflit `HORLOGE_POSTE_EN_AVANCE` conserve les valeurs écrasées (SyncConflictLog).
- **982** : pas de nouvelle notification tant que le conflit ouvert du client a déjà sa notification.
- **984** : dédoublonnage de lot sur UUID normalisé (`_strict_uuid`). Note : le dédoublonnage de lot ne s'applique qu'à `clients.Client` (comme BUG-972) ; les autres modèles passent par leur upsert idempotent.

Impact contrat : nouvelle clé `closures` dans la réponse du pull (additive). Risque : une resoumission à l'identique (aucun chiffre changé) ne lève pas le rejet.
Résultats des tests : voir message de retour.
