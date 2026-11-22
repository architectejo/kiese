# Rapport dev-backend B, 2026-11-22 (b5)

Tickets : BUG-517 et BUG-523 (version C, chat) passés à CORRIGÉ.

- Cause : `NodeViewSet.destroy` ne protégeait ni le nœud technique SIEGE ni l'historique du chat (CASCADE).
- Correctif : deux gardes explicites dans `backend/core/views.py` (400 français). SIEGE refusé par son code ; nœud refusé si sa `Conversation(kind=NODE)` contient au moins un message. Aucune migration.
- Tests : `backend/core/tests/test_bug517_523c_node_delete_guards.py` (3). `backend/core/tests/test_verif_bug414_c.py` : test documentant SIEGE supprimable retiré, `@expectedFailure` BUG-517 retiré.
- Risque : participants sans message supprimés avec le nœud (voulu).
