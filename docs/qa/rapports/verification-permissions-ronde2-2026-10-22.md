# Rapport testeur-permissions — vérification ronde 2 — 2026-10-22

## Mission
Relecture et contre-vérification du correctif ciblé livré par `dev-backend` (rapport `docs/qa/rapports/dev-backend-residuel-phase4-2026-10-22.md`) sur BUG-022 (fuite en écriture, 5 ViewSets) et BUG-025 (`ClientViewSet.perform_update`), avant de passer ces tickets à `VÉRIFIÉ` ou de les rouvrir.

## Méthode
1. Relecture indépendante du code actuel (pas du rapport dev) de :
   - `backend/core/views.py::ColisDistributionViewSet` (`perform_create`/`perform_update`), `SystemNotificationViewSet` (`get_permissions`).
   - `backend/clients/views.py::SocialContributionViewSet.perform_create`, `SocialDistributionViewSet.perform_create`, `ClientViewSet.perform_update`.
   - `backend/production/views.py::ConsumableMovementViewSet.perform_create`.
2. Relance des tests de preuve existants : `backend/core/tests/test_permissions_verif_2026_10_22.py` (`ForgedNodeOnWriteTests`, `NotificationForgedOriginTests`, `ClientNodeMoveViaUpdateTests`).
3. Relecture indépendante du frontend (`frontend/src/components/layout/DashboardLayout.tsx`), sans se fier au rapport dev-backend, pour confirmer l'absence d'impact réel du ticket BUG-022-FE.
4. Reproduction manuelle du scénario `PATCH /api/clients/clients/<id>/ {"node": "<autre nœud>"}` en GERANT.
5. Suite complète : `python manage.py test core clients production`.

## Constats

### 1. `node = user.node` imposé sans lecture du payload (5 ViewSets)
Confirmé sur les cinq points corrigés :
- `ColisDistributionViewSet.perform_create`/`.perform_update` : pour un non-HQ, `serializer.save(node=user.node)` ; branche HQ seule lit `serializer.save()` tel quel.
- `SocialContributionViewSet.perform_create`, `SocialDistributionViewSet.perform_create` : pour un non-HQ, `node = user.node` sans jamais appeler `validated_data.get('node')` ; branche HQ seule fait `validated_data.get('node') or user.node`.
- `ConsumableMovementViewSet.perform_create` : même motif ; le repli sur `stock.node` (quand `node` est absent du payload) n'est conservé que pour la branche HQ — un non-HQ reçoit toujours `node = user.node`, jamais `stock.node` d'un stock d'une autre boulangerie.

Aucune des cinq branches non-HQ ne lit plus `request.data`/`validated_data` pour le champ `node`/`node_origin`.

### 2. `SystemNotificationViewSet` — restriction `IsHeadquarters` sur l'écriture, aucun flux cassé
`get_permissions()` réserve `create`/`update`/`partial_update` à `IsHeadquarters()` ; `list`/`retrieve`/`destroy`/`mark_read`/`mark_all_read` restent à `IsAuthenticated()`, filtrés par `get_queryset()` (inchangé).

J'ai relu moi-même `frontend/src/components/layout/DashboardLayout.tsx` (ligne par ligne, sans me fier au rapport dev-backend) :
- l.81 : `GET /api/core/notifications/`
- l.108 : `POST /api/core/notifications/${id}/mark_read/`
- l.117 : `POST /api/core/notifications/mark_all_read/`
- l.126 : `DELETE /api/core/notifications/${id}/`

Une recherche globale sur `frontend/src` pour `notifications/` ne renvoie que ces quatre appels, tous dans ce même fichier. Aucun `POST`/`PATCH`/`PUT` brut (création/modification de notification) n'existe côté frontend. **Confirmé : aucun flux légitime n'est cassé pour un non-HQ.**

### 3. BUG-022-FE — pas d'impact réel
Confirmé indépendamment (point 2 ci-dessus). Le changement de code HTTP (403 au lieu de 200/201 sur `POST/PATCH/PUT /api/core/notifications/` pour un non-HQ) documenté par dev-backend est réel au niveau du contrat API, mais **aucun écran actuel ne l'appelle**. Ticket passé à `REJETÉ` dans le registre (conservé comme documentation du changement de contrat, à rouvrir si un futur écran de création manuelle de notification est exposé à un rôle non-HQ).

### 4. `ClientViewSet.perform_update` — scénario PATCH reproduit et bloqué
Code actuel (l.76-89 de `backend/clients/views.py`) :
```python
def perform_update(self, serializer):
    user = self.request.user
    if not user.can_access_all_nodes:
        serializer.validated_data.pop('node', None)
        client = serializer.save(node=user.node)
    else:
        client = serializer.save()
    client.refresh_category()
    client.save(update_fields=['category'])
```
Reproduction du scénario exact demandé : GERANT K1 crée un client sur K1, puis `PATCH /api/clients/clients/<id>/ {"node": "<uuid K2>"}`. Résultat : le client reste rattaché à K1 après rafraîchissement depuis la base (`client_k1.node_id == self.k1.pk`). Test de preuve `ClientNodeMoveViaUpdateTests::test_gerant_k1_cannot_move_its_own_client_to_k2_via_patch` : **ok**.

## Tests exécutés

- `python manage.py test core.tests.test_permissions_verif_2026_10_22 -v 2` → **10 tests, OK** (`ForgedNodeOnWriteTests` 4/4, `NotificationForgedOriginTests` 1/1, `ClientNodeMoveViaUpdateTests` 1/1, `BreadTransferForgedIdTests` 1/1, `CashbookHQRoleTests` 2/2, `RefreshCycleIndependentTests` 1/1).
- `python manage.py test core clients production -v 2` → **108 tests, 1 échec** : `clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests.test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db` — verrou SQLite (`database table is locked`) sous vrais threads concurrents, scénario du ticket **BUG-017** déjà distinct et documenté comme peu fiable sous SQLite (test jumeau `..._is_unreliable` dans la même classe). **Sans rapport avec le périmètre de cette mission** (BUG-022/BUG-025) ; aucun des fichiers touchés par dev-backend dans ce correctif (`core/views.py`, `clients/views.py` hors `ClientViewSet`, `production/views.py::ConsumableMovementViewSet`) n'affecte ce scénario.

`manage.py test core clients production` ne passe donc pas à 100 % globalement, mais **la cause est préexistante, hors périmètre (BUG-017), déjà connue et non introduite par le correctif vérifié ici.**

## Décisions prises dans le registre (`docs/qa/REGISTRE_BUGS.md`)
- **BUG-022** : statut → `VÉRIFIÉ`, section « Vérification (ronde 2) » ajoutée.
- **BUG-025** : statut → `VÉRIFIÉ`, section « Vérification (ronde 2) » ajoutée.
- **BUG-022-FE** : statut → `REJETÉ` (pas d'impact réel confirmé indépendamment), section « Vérification » ajoutée, ticket conservé pour traçabilité du changement de contrat API.

## Aucun fichier de code applicatif modifié
Seul `docs/qa/REGISTRE_BUGS.md` a été édité (sections de vérification), conformément à la règle « les testeurs ne corrigent pas le code applicatif ».

## Reste en suspens (hors mission, signalé pour le coordinateur)
- **BUG-017** (concurrence `_generate_client_code` sous SQLite) reste la seule cause d'échec de `manage.py test core clients production` ; déjà un ticket distinct, pas rouvert ici.
- `BUG-023`, `BUG-026` restent `VÉRIFIÉ` (déjà traités en ronde 1, non retouchés par ce correctif, non re-vérifiés dans cette ronde — hors périmètre de la demande).
