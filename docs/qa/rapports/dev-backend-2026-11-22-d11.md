# Rapport dev-backend (Dev B) — 2026-11-22 d11

## Ticket traité
- BUG-863 (Mineur, Trésorerie) : CORRIGÉ.
  - Cause : `CashClosureViewSet.validate` recalculait l'écart (dépense saisie après la clôture) sans notification.
  - Correction : `backend/treasury/views.py` : écart mémorisé avant recalcul ; si écart non nul et changé, `create_notification` « Écart de Caisse — <code> » (WARNING si |écart| < 10 000 FC, sinon DANGER), comme création et resoumission. Pas de notification si écart nul ou inchangé.
  - Test : `backend/treasury/tests/test_verif_tresorerie_c6_v5.py::test_BUG_863_confirmation_with_recalculated_gap_is_notified` (`@expectedFailure` retiré, définitivement à la demande du coordinateur).
  - Fonction de hash non modifiée ; pas de changement d'API ni de migration.

## En attente
Aucun. Vérification (VÉRIFIÉ) à faire par testeur-tresorerie.

## Risques
Faibles : une notification supplémentaire à la confirmation uniquement quand l'écart a changé.
