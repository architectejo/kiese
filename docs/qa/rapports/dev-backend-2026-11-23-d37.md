# Rapport dev-backend d37 (2026-11-23)

Traités (CORRIGÉ, à vérifier par les testeurs) : BUG-970, BUG-969, BUG-972 (nouveau, deux régressions).
- BUG-970 : `build_outbound_payload` envoie `updated_at` / `identity_updated_at` ; la garde utilise `identity_updated_at` sinon `updated_at` ; poste ancien sans version : push appliqué.
- BUG-969 : `SyncConflictLog` (`IDENTITE_OBSOLETE`) + notification WARNING si le push obsolète change des valeurs (pas de bruit sur rejeu identique) ; statut ACCEPTED.
- BUG-972 : (1) premier gagne pour un id Client dupliqué dans un même lot (`process_push_batch`) ; (2) `_bill_int` (entiers stricts) pour `_check_bills` et `_bills_kwargs`. Les tests encodaient le bon comportement, non modifiés.
- Fichiers : sync/services.py, sync/management/commands/sync_now.py, clients/tests/test_clients_v10.py (décorateurs retirés 969/970).
- Tests : 227 OK (1 échec attendu restant), makemigrations : aucun changement. Log : $TEMP/d37.log.
Risques : la garde compare l'horloge du poste à celle du Cloud (identity_updated_at du Cloud = heure serveur) ; une dérive d'horloge peut ignorer un push légitime (désormais tracé en conflit).
