# Rapport dev-backend d34 (2026-11-23)

BUG-955 à 963 : CORRIGÉ (dev-backend d34). Fichiers : `backend/sync/services.py`, `backend/sync/management/commands/sync_now.py`.

- 958 : création de transfert acceptée en PENDING, ou RESPONDED par l'émettrice seule (envoi direct) sans quantité reçue ; CONFIRMED/DISPUTED/CANCELLED et toute quantity_received par l'émettrice restent refusés.
- 955 : `_resolve_invoice_line` ne se replie sur l'id seul que si la clé `invoice` est absente ; sinon rejet « dépendance manquante : invoice ».
- 956 : `'150000.0'` accepté (normalisé) à la validation générique, à la création et à la mise à jour ; `'1e3'` reste refusé.
- 957 : sac à 0 conservé à la création (même règle que la mise à jour) ; 200000 seulement si absent/vide.
- 959 : `facturier` exporté par `build_outbound_payload` (poste ancien sans clé : inchangé).
- 960 : clôture poussée validée refusée si écart de transfert entrant non résolu ; même blocage avant versement au livre.
- 961/962 : nouveau `_check_local_expense` (date invalide/future avec motif précis, jour de clôture confirmée refusé).
- 963 : contrôle de nœud du facturier ignoré pour les rôles `can_access_all_nodes`.

Tests : 156 tests (2 fichiers + a10, c11, sync v5, charge v4) verts, makemigrations sans changement. Marques `@expectedFailure` retirées pour vérification locale puis remises (le testeur les retire).
Note : `test_cloud_recalcul_de_dette_fait_avancer_updated_at` (charge v4) a échoué une fois dans le lot complet, vert 2 fois isolé : test sensible au timing, non lié.
Risque : l'auto-validation par le poste à la création de clôture reste possible hors écart (conception SYNC.md, tests existants) ; à trancher avec le coordinateur si la règle « seul le comptable confirme » doit s'appliquer aussi au sync.
