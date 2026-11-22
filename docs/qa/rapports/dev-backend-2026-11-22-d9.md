# Rapport dev-backend, 2026-11-22 (d9)

## Tickets traités (passés à CORRIGÉ)
- BUG-860 : `CashClosureViewSet.perform_update` (treasury/views.py) journalise désormais
  « Resoumission Clôture de Caisse » et notifie l'écart non nul (mêmes seuils que la création).
- BUG-861 : `CashbookEntryViewSet.integrity_check` (treasury/views.py) et
  `_verify_chain_for_node` (blockchain/views.py) remettent `is_tampered=False` (un seul UPDATE)
  pour les écritures de nouveau valides. BUG-842 conservé : la notification n'est créée qu'à la
  transition faux -> vrai ; un GET répété ne notifie pas ; une nouvelle altération après réparation notifie.

## Tests
- `test_verif_tresorerie_c5_v4.py` : marques `@expectedFailure` retirées sur
  `test_BUG_860_*` et les deux `test_BUG_861_*` (aucune autre modification).
- Suite `treasury blockchain` : voir résultat communiqué au coordinateur.
- Aucune migration. Fonction de hash inchangée. Pas de changement de contrat d'API.

## Risques
- Le `is_tampered` ne retombe qu'à l'exécution d'une vérification (integrity_check / run_check),
  pas automatiquement à la réparation.
