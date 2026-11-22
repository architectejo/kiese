# dev-backend 2026-11-22 (a2) : BUG-516

Statut : CORRIGÉ (à vérifier par testeur-permissions).
- Cause : `TamperAlert.node` / `BlockchainSnapshot.node` en CASCADE.
- Fichiers : `backend/blockchain/models.py` (PROTECT), `backend/blockchain/migrations/0002_node_protect.py` (nouvelle ; dépend de core 0020), `backend/blockchain/tests/test_bug516_node_protect.py` (5 tests), `backend/core/tests/test_verif_bug414_c.py` (@expectedFailure retiré sur le test BUG-516).
- Avant : 4/5 tests du nouveau fichier en échec (modèles remis en CASCADE). Après : 5/5 verts. `check` et `makemigrations --check` propres.
- `NodeViewSet.destroy` renvoie déjà 400 « Impossible de supprimer… » sur ProtectedError (core/views.py:233-242), inchangé.
- Sync : blockchain n'est pas synchronisé (aucune référence dans sync/), aucun impact.
- CashbookEntry.node : déjà PROTECT (treasury/models.py:285).
- FK Node encore en CASCADE : `sync/models.py:98` (NodeAuthToken, jeton, non comptable) ; `chat/models.py:22` (Conversation, module B). Aucune autre dans production/sales/treasury/finance (finance n'a pas de FK Node) ; les CASCADE restants de ces apps sont des lignes enfants (InvoiceLine, ProductionLine, BreadDisposal.session...) vers leur parent, pas vers Node.
