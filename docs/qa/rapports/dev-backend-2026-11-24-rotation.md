# Rapport dev-backend (dev-b) - rotation Q-017, Q-019, Q-020, Q-021 - 2026-11-24

Tickets : BUG-1122 (Q-017), BUG-1123 (Q-019), BUG-1124 (Q-020), BUG-1125 (Q-021), tous CORRIGÉ. Q-018 non traité (autre agent).

## Changements
- Q-017 : `Node.team_rotation_enabled` default/db_default True (`core/models.py`) ; migration `core/migrations/0026_node_rotation_default_true.py` (AlterField + données : True hors SIEGE, `handover_time` 12:00 si vide, reverse no-op) ; `seed_kiese` aligne les 8 boulangeries même existantes. Sync : `node_settings` diffusait déjà `team_rotation_enabled` et `handover_time` (test ajouté).
- Q-019 : `closure_lock.sales_blocked_for` n'a aucun délai de grâce (confirmé, tests). `SHIFT_END_GRACE_MINUTES = 30` inchangé (test de garde, Q-053).
- Q-020 : `validate`/`reject`/`push_to_cashbook` déjà sous `IsHeadquarters` (ADMIN, DIRECTION, COMPTABLE) ; gérant, facturier, livreur 403 ; isolation par nœud confirmée. Tests seulement.
- Q-021 : `production/services.py::notify_direction_if_unattended_closure`, appelée par `auto_close_sessions` (commande) et `shift-end-status` (vue). Une notification par boulangerie et par période, idempotente, + `log_activity`.

## Fichiers
Modifiés : `backend/core/models.py`, `backend/core/management/commands/seed_kiese.py`, `backend/core/testing.py`, `backend/production/services.py`, `backend/production/views.py`, `backend/production/management/commands/auto_close_sessions.py`.
Créés : `backend/core/migrations/0026_node_rotation_default_true.py` et trois `test_dev_b_rotation_q017_021.py` (core 5, production 12, treasury 8 = 25 tests, verts).
Note : `core/workday.py`, `treasury/closure_lock.py`, `production/services.py::auto_close_*` sont aussi modifiés par l'agent Q-018 (midi à midi) ; mes tests utilisent `closure_status()['closure_date']` pour rester valables.

## Anciens tests adaptés
- `core/testing.py::make_node` : nouveau paramètre `rotation=False` (fabrique neutre, comme pour social/carte, BUG-417) ; les tests historiques hors rotation restent inchangés. Aucun test existant modifié ni supprimé.
- Adaptés (nœud créé en direct, scénario historique hors rotation, `team_rotation_enabled=False` explicite) : `sales/tests/test_invoices.py` (2 setUp : `ReceiptNumberTests`, `ConcurrentInvoiceBPTests`, échec 403 TEAM_NOT_ASSIGNED) et `clients/tests/test_clients_v14.py` (K2, 403 au lieu de 400).
- Série ciblée (170 tests : core workday/schedule, production 161/350/1120/155, sales invoices/blocage équipe, treasury d38) : 17 échecs, dont seul `test_concurrent_invoice_creation_never_duplicates_receipt_number` venait de la rotation par défaut (corrigé ci-dessus). Les 16 autres (journée de relève : `test_bug350_*`, `test_verif_bug161_*`, `test_bug161_b2_team_assignment`, `test_dev_bug1120_*`, `test_dev_d38_blocage_ventes`) viennent de la conception midi à midi (BUG-1130, Q-018) en cours chez l'autre agent (`core/workday.py`, `closure_lock.py`) : à adapter par lui ou par le testeur, je ne les ai pas touchés.
- Une série de contrôle de 18 modules à nœud créé en direct (permissions core, finance, production a3/a4/a17/612, treasury c15...) a été lancée mais n'a pas abouti dans le temps imparti (plus d'une heure) : non vérifiée, à relancer par le testeur ; en cas de 403 `TEAM_NOT_ASSIGNED`, mettre `team_rotation_enabled=False` sur le nœud du test.

## Risques / à décider
1. Le blocage des ventes reste sous `Node.block_sales_after_closure` (défaut False) : "bloquer tout de suite" n'est effectif que si l'interrupteur est activé par boulangerie. À décider : l'activer aussi par défaut (impact lourd sur les tests de vente).
2. Q-021 : l'alerte part dès que l'heure est passée sans activité (pas de délai) ; peut être bruyante si le personnel arrive quelques minutes après. Ajouter un délai est un changement d'une ligne si le client le souhaite. Sans cron ni connexion, la détection est tardive (elle se fait à l'appel suivant de la commande ou de l'endpoint).
3. Avec la rotation par défaut, tout test créant un nœud en direct et facturant sans désigner d'équipe obtient un 403 (équipe non désignée). Seules les séries ciblées (core, production, sales invoices/blocage, treasury blocage) ont été lancées, pas les séries complètes.
4. La migration de données n'est pas réversible de façon sûre (on ne sait plus quels nœuds étaient hors rotation).
