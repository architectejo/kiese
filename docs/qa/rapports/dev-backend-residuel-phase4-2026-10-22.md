# Rapport dev-backend — reprise résiduelle phase 4 — 2026-10-22

## Tickets traités (passés à CORRIGÉ — jamais VÉRIFIÉ, laissé au testeur d'origine)

### BUG-022 (Bloquant) — fuite en écriture sur 5 ViewSets
- `backend/core/views.py::ColisDistributionViewSet.perform_create`/`.perform_update` : `node=user.node` imposé pour un non-HQ, sans jamais lire le payload.
- `backend/clients/views.py::SocialContributionViewSet.perform_create`, `SocialDistributionViewSet.perform_create` : même correctif.
- `backend/production/views.py::ConsumableMovementViewSet.perform_create` : même correctif (repli sur `stock.node` conservé uniquement pour la branche HQ).
- `backend/core/views.py::SystemNotificationViewSet.get_permissions()` : `create`/`update`/`partial_update` réservés à `IsHeadquarters()` ; `list`/`retrieve`/`destroy`/`mark_read`/`mark_all_read` inchangés. Vérifié au préalable qu'aucun flux frontend (`frontend/src/components/layout/DashboardLayout.tsx`) ne crée/modifie une notification via l'API (uniquement GET, mark_read, mark_all_read, delete) — `create_notification()` (core/utils.py) est appelé côté serveur uniquement.
- Ticket lié ouvert pour traçabilité (pas d'action requise à ce jour) : **BUG-022-FE**, information pour dev-frontend/coordinateur sur le changement de code HTTP (403 au lieu de 200/201) pour un non-HQ sur `POST/PATCH/PUT /api/core/notifications/`.
- Test de preuve : `backend/core/tests/test_permissions_verif_2026_10_22.py::ForgedNodeOnWriteTests` (4 tests) + `::NotificationForgedOriginTests` (1 test) — tous passent désormais (ils n'avaient pas de `@expectedFailure`, ils retournent tôt si la requête est rejetée ; avant correction, l'assertion interne échouait).

### BUG-025 (Majeur) — `perform_update` toujours vulnérable
- `backend/clients/views.py::ClientViewSet.perform_update` : pour un non-HQ, `node` est retiré de `validated_data` puis `node=user.node` réimposé explicitement avant `serializer.save()`. Comportement HQ inchangé.
- Choix documenté dans le registre : correctif dans `perform_update` plutôt que champ `node` en lecture seule dans le serializer, car `IsGerant` couvre aussi les rôles HQ pour qui `node` doit rester modifiable — la distinction se fait par rôle de la requête, pas uniquement par le champ.
- Test de preuve : `backend/core/tests/test_permissions_verif_2026_10_22.py::ClientNodeMoveViaUpdateTests::test_gerant_k1_cannot_move_its_own_client_to_k2_via_patch` — passe désormais (le client reste sur K1 malgré le `PATCH node=K2` forgé).

### BUG-053 (Majeur) — `Invoice.deliver()` non-atomique
- `backend/sales/models.py` : import `transaction` ; tout le corps de `Invoice.deliver()` encapsulé dans `with transaction.atomic():` (option recommandée par le testeur).
- `backend/sales/views.py::InvoiceViewSet.deliver` : ajout de `@transaction.atomic` (symétrique à `InvoiceViewSet.create`).
- Test de preuve : `backend/treasury/tests/test_bug053_signal_side_effects.py::DeliveryBlockedSideEffectTests::test_blocked_delivery_still_leaves_client_bread_counter_incremented` — `@unittest.expectedFailure` retiré, le test passe (le compteur de pains du client reste inchangé après une livraison bloquée par le signal BUG-036). Les 5 tests `SignalDoesNotAffectNormalFlowsTests` du même fichier passent toujours sans régression.
- Note : l'import `unittest` du fichier de test est devenu inutilisé après le retrait du décorateur ; je n'ai pas touché ce fichier au-delà de retirer le décorateur, conformément à la consigne (« ne pas supprimer/affaiblir un test », et c'est le testeur qui en a la propriété).

## Vérifications effectuées avant de rendre la main
- `python manage.py check` → `System check identified no issues (0 silenced).`
- `python manage.py test core production sales treasury` → **136 tests, OK, 0 échec, 0 succès inattendu.**
- `python manage.py test treasury.tests.test_bug053_signal_side_effects core.tests.test_permissions_verif_2026_10_22 -v 2` → 16 tests, OK (vérification ciblée des tests de preuve).
- `python manage.py makemigrations --check --dry-run` → dérive détectée sur `production` (alter `transfer_status`/`id`), `clients` (contraintes `unique_social_*`/`id`), `treasury` (`unique_daily_savings_node_date`/`id`). **Cette dérive est préexistante et sans rapport avec mon travail** : aucun des fichiers que j'ai modifiés (`core/views.py`, `clients/views.py`, `production/views.py` — ConsumableMovementViewSet uniquement, `sales/models.py`, `sales/views.py`) ne touche à un modèle Django ; je n'ai modifié aucun champ ni contrainte. À signaler au coordinateur si ce n'est pas déjà tracé ailleurs dans le registre (semble lié à des changements de `Meta`/`id` non encore migrés sur ces 3 apps, hors périmètre de ma mission).

## Fichiers modifiés
- `backend/core/views.py`
- `backend/clients/views.py`
- `backend/production/views.py` (uniquement `ConsumableMovementViewSet.perform_create`)
- `backend/sales/models.py`
- `backend/sales/views.py`
- `backend/treasury/tests/test_bug053_signal_side_effects.py` (retrait du seul décorateur `@unittest.expectedFailure`)
- `docs/qa/REGISTRE_BUGS.md` (BUG-022 → CORRIGÉ avec section « Correction (reprise écriture) » ajoutée sans remplacer la section Vérification existante ; nouveau ticket BUG-022-FE pour dev-frontend/coordinateur ; BUG-025 → CORRIGÉ avec section « Correction (reprise update) » ajoutée ; BUG-053 → CORRIGÉ avec section « Correction » ajoutée)

## En attente / à faire par d'autres agents
- testeur-permissions : vérifier et faire passer BUG-022 et BUG-025 à `VÉRIFIÉ` (ou rouvrir si une faille résiduelle est trouvée).
- testeur-tresorerie : vérifier et faire passer BUG-053 à `VÉRIFIÉ`.
- coordinateur/dev-frontend : décider si BUG-022-FE nécessite une action (à ce jour, aucun écran frontend connu n'est impacté).

## Risques résiduels signalés (hors périmètre de cette mission, non corrigés)
- La dérive de migrations détectée sur `production`/`clients`/`treasury` (ci-dessus) n'a pas été investiguée en profondeur ni corrigée — je n'ai pas touché aux modèles de ces apps et il ne m'a pas été demandé de le faire. À signaler au coordinateur pour attribution.
- BUG-023, BUG-024, BUG-026 et les autres tickets du registre non mentionnés dans ma mission n'ont pas été traités ici.
