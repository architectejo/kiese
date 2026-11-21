# architecte-sync (dev B) — 2026-11-21 — BUG-146

- Cause : sortie de consommable reçue avant son entrée figée à 0 FC (CUMP de la ligne créée paresseusement), jamais corrigée.
- Correction : `backend/sync/services.py` (`_track_orphan_exit`, `_restamp_orphan_exits`). Marqueur dans `SyncConflictLog` (`CONSUMABLE_EXIT_ORPHAN`), ré-estampillage à l'arrivée d'une ENTRY valorisée, même transaction (atomique, reprise après coupure sûre), `select_for_update`, idempotent, Decimal.
- Fonction BUG-126 (migration 0018) non réutilisée : rejoue dans l'ordre de `created_at` (= ordre d'arrivée au Cloud), redonne 0. production/ non modifié.
- Limite : pas d'horodatage d'origine dans le push ; prix = moyenne pondérée de toutes les entrées reçues.
- Tests : `sync/tests/test_bug146_exit_before_entry.py` (4 OK) ; `manage.py test sync` + consommables/BUG-143 production : 73 tests, 1 échec = test périmé BUG-143 (documentait le défaut), voir BUG-402. Les 8 rouges préexistants production/sales non recomptés.
- Ticket BUG-402 (CUMP gonflé sur stock négatif, test périmé) pour le dev A. BUG-146 : CORRIGÉ.
