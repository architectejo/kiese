# Rapport dev-backend (dev B) - 2026-11-20c

## BUG-400 - Historique mensuel des opérations d'un client (CORRIGÉ volet backend)
- Endpoint : `GET /api/clients/clients/<uuid>/history/?month=AAAA-MM` (`clients/views.py::ClientViewSet.history`). Contrat JSON complet dans la fiche BUG-400 du registre.
- Réutilise `Invoice` (aucun historique client n'existait ; pas de duplication). Pas de migration.
- Permission `IsGerant` (facturier/livreur 403), nœud via `get_queryset()`, month invalide -> 400 en français, Decimal + quantize, tri déterministe.
- Tests : `clients/tests/test_bug400_client_history.py` (mois courant, mois passé, 400, mois vide, tri, permissions, nœud).

## Risque / en attente
- AUCUN interpréteur Python utilisable sur ce poste (python.exe absent des installations 3.14 et 3.12, disque plein à 99 %) : `python manage.py test clients commissions` et `makemigrations --check` NON exécutés. À lancer avant fusion.
- Frontend : modale à faire par dev-frontend.
