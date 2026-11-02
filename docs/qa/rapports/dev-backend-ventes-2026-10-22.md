# Rapport — dev-backend (module Ventes) — 2026-10-22

Périmètre reçu du coordinateur : `backend/sales/` uniquement, tickets BUG-028 à BUG-031
(Majeur), ouverts par `testeur-ventes`. BUG-032 (frontend) et BUG-021 (hors périmètre de
cette itération) non traités, conformément aux instructions.

## Tickets traités

### BUG-028 — `commission_rate` non forcé à 0 côté serveur (vente soldée / occasionnelle)
- Statut : `OUVERT` → `CORRIGÉ` (jamais `VÉRIFIÉ`, laissé à `testeur-ventes`).
- Cause : `comm_rate = data.get('commission_rate', config.default_commission_rate)` faisait
  confiance au payload, retombant sur 25 % par défaut si le champ était omis, même pour une
  vente soldée (`is_soldee=True`) ou une vente occasionnelle sans client.
- Correctif : `backend/sales/views.py::InvoiceViewSet.create` — `comm_rate = Decimal('0.00')`
  imposé si `is_soldee` ou `client is None`, avant toute lecture du payload. Le flux client
  nommé + non soldé continue de lire `commission_rate` du payload (comportement inchangé).
- Test : `backend/sales/tests/test_invoices.py::SoldeeTests::test_soldee_forces_zero_commission_rate_server_side`
  et `::test_occasional_sale_without_client_forces_zero_commission` — `@expectedFailure` retiré,
  passent.
- Impact API : aucun changement de contrat.

### BUG-029 — `cleanup_expired` ne restitue pas le stock de pains
- Statut : `OUVERT` → `CORRIGÉ`.
- Cause : `cleanup_expired` reversait la dette client mais ne rappelait jamais
  `_adjust_bread_stock`, contrairement à `cancel()`.
- Correctif : `backend/sales/views.py::InvoiceViewSet.cleanup_expired` — ajout de
  `prefetch_related('lines__bread_price')` et `select_related('node')` au queryset des
  factures expirées, puis boucle `_adjust_bread_stock(inv.node, line.bread_price, sent=-line.quantity)`
  avant la suppression, même logique que `cancel()`.
- Test : `::ExpiryCleanupTests::test_cleanup_restores_bread_stock_deducted_at_creation` —
  `@expectedFailure` retiré, passe.
- Impact API : aucun.

### BUG-030 — Un facturier peut forcer `node` et usurper une autre boulangerie
- Statut : `OUVERT` → `CORRIGÉ`.
- Cause principale : `node_id = data.get('node') or request.user.node_id` donnait priorité
  au payload sans contrôle de rôle.
- Correctif : `backend/sales/views.py::InvoiceViewSet.create` — pour tout utilisateur
  non-HQ (`not request.user.can_access_all_nodes`), `node_id = request.user.node_id` sans
  jamais lire `data.get('node')`. Seul un utilisateur HQ peut encore préciser un nœud via le
  payload (même critère que `ClientViewSet`/BUG-025, fichier différent, pas de dépendance
  créée).
- **Bug annexe découvert et corrigé dans le même périmètre** : `InvoiceCreateSerializer.node`
  était déclaré `serializers.UUIDField`, alors que `core.models.Node` a une clé entière
  (`BigAutoField`). Tout payload avec un `node` explicite — y compris le scénario de
  reproduction du ticket — était rejeté en 400 avant même d'atteindre la vue. Corrigé en
  `serializers.IntegerField(required=False)` dans `backend/sales/serializers.py`. Sans ce
  correctif, le test de preuve de BUG-030 ne pouvait pas s'exécuter du tout.
- Test : `::NodeIsolationTests::test_facturier_cannot_force_node_field_to_another_bakery` —
  `@expectedFailure` retiré, passe.
- Impact API : aucun changement visible pour un usage légitime actuel (le frontend n'envoie
  pas `node` à la création de facture). Le champ redevient utilisable pour un HQ qui voudrait
  l'envoyer explicitement (corrigé par le même changement de type).

### BUG-031 — `get_permissions()` écrase les `permission_classes` des `@action`
- Statut : `OUVERT` → `CORRIGÉ`.
- Cause exacte : `@action(permission_classes=[...])` range ce kwarg dans
  `func.kwargs['permission_classes']` (vérifié dans le code source de
  `rest_framework/decorators.py::action`), pas comme attribut direct sur la fonction.
  `get_permissions()` ne consultait ni l'un ni l'autre pour les actions `cancel` et
  `cleanup_expired`, et retombait sur `[IsGerant()]`.
- Correctif : `get_permissions()` lit désormais `getattr(self, self.action).kwargs.get('permission_classes')`
  et l'utilise en priorité si déclaré. Branches explicites conservées à l'identique pour
  `create` (→ `IsFacturier`), `list`/`retrieve` (→ `IsAuthenticated`), et le reste par défaut
  (→ `IsGerant`, pour `update`/`partial_update`/`destroy`, qui ne déclarent rien via `@action`
  — comportement volontairement inchangé, hors périmètre du ticket).
- Tests : `::DeliveryAndCancelTests::test_facturier_can_cancel_a_pending_order_he_created` et
  `::ExpiryCleanupTests::test_facturier_can_trigger_cleanup_expired_himself` — `@expectedFailure`
  retiré sur les deux, passent. L'ensemble de `DeliveryAndCancelTests`/`ExpiryCleanupTests` a
  été rejoué pour s'assurer qu'aucune permission existante (livreur/gérant sur `deliver`,
  annulation d'une facture livrée, etc.) n'a été élargie par erreur.
- Impact API : aucun changement de contrat, alignement du comportement réel sur ce que le
  code et remarque.md promettaient déjà.

## Fichiers modifiés
- `backend/sales/views.py`
- `backend/sales/serializers.py`
- `backend/sales/tests/test_invoices.py` (retrait de 6 `@expectedFailure` : BUG-028 ×2,
  BUG-029 ×1, BUG-030 ×1, BUG-031 ×2 — aucun test affaibli ni supprimé)
- `docs/qa/REGISTRE_BUGS.md` (BUG-028 à BUG-031 passés à `CORRIGÉ`, fiches complétées)

## Validation effectuée
- `python manage.py test sales` : 32/32 tests passent (`OK`). Les erreurs
  `OperationalError: database table is locked: core_config` visibles dans la sortie sont du
  bruit SQLite documenté par `testeur-ventes` dans les docstrings de `ConcurrentInvoiceBPTests`
  / `ReceiptNumberTests` (verrouillage mono-fichier sous accès concurrent), pas des échecs —
  le run se termine bien par `OK`.
- `python manage.py test` (suite complète, 189 tests) : `FAILED (failures=1, errors=1,
  expected failures=16)`. Les 2 anomalies restantes sont **hors de mon périmètre** et
  préexistantes/en cours chez d'autres agents en parallèle :
  - `core.tests.test_permissions.CashbookEntryIsolationTests::test_gerant_k1_cannot_read_the_direction_cashbook_at_all`
    → `IntegrityError: UNIQUE constraint failed: treasury_cashbookentry.previous_hash` (module
    trésorerie/blockchain, pas sales).
  - `core.tests.test_permissions.RefreshBlacklistTests::test_refresh_endpoint_rejects_a_blacklisted_refresh_token`
    (BUG-024/BUG-006) → logout renvoie 401 au lieu de 200 ; explicitement signalé dans les
    instructions de cette session comme traité par un autre `dev-backend` (balayage
    permissions) en parallèle sur `core/urls.py` / le flux JWT refresh — **je n'y ai pas
    touché**, conformément à la consigne.
  - Les 16 `expected failures` restantes couvrent d'autres tickets backend non assignés à
    cette session (ex. permissions clients/trésorerie, BUG-025/026, pris en charge par un
    autre agent dev-backend en parallèle).
- `python manage.py makemigrations --check --dry-run` : signale une dérive sur `production`,
  `clients`, `treasury` (changements de `id`/contraintes, probablement issus du travail
  parallèle d'`architecte-sync`/autre `dev-backend` sur ces apps pendant cette session). **Je
  n'ai modifié aucun modèle** dans ces apps. Vérifié isolément : `makemigrations sales --check
  --dry-run` → `No changes detected in app 'sales'`. Signalé au coordinateur pour suivi par
  l'agent responsable de ces apps, pas de ma responsabilité.
- `python manage.py check` : aucun problème.

## Environnement (note technique, hors périmètre fonctionnel)
- `backend/.env` est toujours un dossier venv (pas un fichier texte), comme documenté dans
  CLAUDE.md §3 et BUG-007. J'ai lancé les tests avec le Python de ce venv
  (`backend/.env/Scripts/python.exe`) et `DJANGO_DEBUG=True` en variable d'environnement
  ponctuelle (pas de fichier modifié) pour pouvoir exécuter `manage.py test` localement, sans
  toucher à `settings.py`, `.env*`, ni à aucun fichier hors de `backend/sales/`.

## Registre `db.sqlite3`
- Je n'ai pas touché à `backend/db.sqlite3` ni à `data_kiese/` (règle transversale §0.1).
  Les données `ZZ3-*` laissées par `testeur-ventes` n'ont pas gêné mon travail (tests
  automatisés uniquement, base de test éphémère) — je ne les ai pas nettoyées, laissé tel
  quel à la discrétion du coordinateur.

## Risques / points de vigilance pour la suite
1. Les 2 échecs restants dans `core.tests.test_permissions` (hors périmètre, voir ci-dessus)
   doivent être recoupés avec l'agent dev-backend en charge de BUG-024/006 et de la
   trésorerie/blockchain — je n'ai pas cherché à les corriger.
2. La dérive `makemigrations` sur `production`/`clients`/`treasury` (hors `sales`) doit être
   résolue par l'agent responsable de ces apps avant la fin de la phase 3, sinon le critère
   « `makemigrations --check --dry-run` propre » de fin de session échouera globalement même
   si `sales` est propre.
3. BUG-030 a révélé un bug de type latent (`UUIDField` vs `Node` à clé entière) dans
   `InvoiceCreateSerializer` — je l'ai corrigé car il bloquait directement la vérification du
   ticket assigné, mais signale qu'un audit plus large des types de champs UUID/entier dans
   les autres sérialiseurs de l'app (ou d'autres apps) pourrait révéler des cas similaires non
   couverts par un test existant.
4. BUG-032 (frontend, libellé du bouton) et BUG-021 (case « sans commission » dans Sales.tsx,
   signalé dans la fiche BUG-028) restent hors de mon périmètre, à traiter par `dev-frontend`.
