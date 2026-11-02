# Rapport dev-backend — BUG-088 (2026-10-29/30)

## Ticket traité
- **BUG-088** — `ClientCreateSerializer` n'exposait ni `id` ni `code` dans la réponse de création
  d'un client (`POST /api/clients/clients/`). Statut final : **CORRIGÉ** (en attente de
  vérification par testeur-clients-commissions ou le coordinateur — je ne l'ai pas passé à VÉRIFIÉ,
  conformément à CLAUDE.md §7).

## Cause
`backend/clients/serializers.py::ClientCreateSerializer.Meta.fields` ne listait que les champs
d'écriture (`first_name`, `last_name`, `phone`, `address`, `photo`, `node`, `cotisation_sociale`,
`commission_rate`, `credit_limit`, `client_type`, `is_active`, `notes`). `id` (UUID, PK) et `code`
(généré par `_generate_client_code` dans `Client.save()`) existaient bel et bien sur l'instance au
moment de la réponse, mais n'étaient jamais sérialisés en sortie — `ClientViewSet` utilise
`CreateModelMixin` standard (`Response(serializer.data, status=201)`), sans override.

Conséquence côté frontend documentée dans le ticket : `Clients.tsx` (~ligne 596-604) lit
`res.data.id` juste après `clientsApi.create()` pour enchaîner une facture de « Client
Occasionnel » — toujours `undefined`, le bloc suivant est silencieusement sauté.

## Correction appliquée
- `backend/clients/serializers.py` : ajout de `'id'` et `'code'` à
  `ClientCreateSerializer.Meta.fields`, et aux `read_only_fields` (ils ne peuvent donc jamais être
  acceptés en entrée, uniquement renvoyés en sortie — même garde que `ClientSerializer`).
- Aucun champ d'écriture, aucune règle métier, aucun modèle, aucune migration touchés : changement
  strictement limité à la sérialisation de sortie.
- `backend/clients/tests/test_api.py` : retrait du `@expectedFailure` sur
  `ClientCreateResponseContractTests::test_create_response_is_missing_id_and_code_bug_088` (passe
  maintenant normalement) ; retrait de l'import `unittest.expectedFailure` devenu inutile.

## Vérifications effectuées
- Relecture de `ClientViewSet.perform_create`/`perform_update` (backend/clients/views.py) : `id` et
  `code` sont bien disponibles sur l'instance avant la sérialisation de la réponse ; aucun autre
  endroit ne dépend du format actuel (pas de code mort qui supposait l'absence de ces clés).
- Test qui échouait avant / passe après :
  `backend/clients/tests/test_api.py::ClientCreateResponseContractTests::test_create_response_is_missing_id_and_code_bug_088`.
- Suite complète `python manage.py test clients sales core.tests.test_permissions` (132 tests) :
  **5 échecs, aucun lié à ce ticket** —
  - 4 dans `sales/tests/test_bug083_*` et `test_e2e_normal_flow_2026_10_29` : flakiness horaire
    pré-existante (la suite a duré ~14 min et a traversé minuit, 2026-10-29 → 2026-10-30, pendant
    l'exécution — `date.today()` évalué en fin de test ne correspond plus à la date de début de
    test) ; rien à voir avec BUG-088 ni avec le changement de serializer.
  - 1 dans `clients/tests/test_verification_2026_10_22.py::BUG017RealConcurrencyStrictAssertionTests`
    (« database table is locked ») : flakiness SQLite déjà connue et documentée sous BUG-017.
  Aucun échec dans `clients/tests/test_api.py` (y compris le test ci-dessus) ni dans tout autre test
  lié à la création de client ou à la facturation.
- `python manage.py makemigrations --check --dry-run` : **aucune migration nécessaire pour ce
  ticket** — confirmé, le changement est limité au serializer, aucun champ de modèle modifié. Le
  dry-run signale en revanche des migrations en attente déjà présentes dans le dépôt pour
  `production` (0013), `clients` (0007, contraintes `unique_together` historiques) et `treasury`
  (0012) — pré-existantes, sans rapport avec BUG-088 ; signalées ici pour le coordinateur si aucun
  ticket ne les couvre déjà.
- `backend/db.sqlite3` : `PRAGMA integrity_check` → `ok`. Aucune migration appliquée (pas nécessaire,
  changement serializer uniquement).

## Impact contrat d'API
La réponse `POST /api/clients/clients/` contient désormais deux champs supplémentaires (`id`,
`code`) qu'elle ne renvoyait pas avant. Ajout de champs = rétrocompatible pour tout consommateur qui
ignorait déjà ces clés ; vérifié qu'aucun autre écran frontend n'en dépendait négativement.

**Ticket lié recommandé pour dev-frontend** (à ouvrir par le coordinateur si jugé pertinent) :
`frontend/src/pages/dashboard/Clients.tsx` (~ligne 596-604) devrait vérifier explicitement
`res.data.id` avant d'enchaîner `salesApi.create(...)`, et `src/api/services.ts` devrait typer
précisément la réponse de `clientsApi.create()` (actuellement un contrat `any`/`Client` trop
optimiste) pour qu'une régression future échoue bruyamment plutôt que silencieusement.

## Tickets en attente / risques
- BUG-088 reste en attente de vérification (testeur d'origine ou coordinateur).
- Flakiness d'horloge dans `sales/tests/test_bug083_*` (suite longue traversant minuit) — à signaler
  au coordinateur si pas déjà suivi ; non corrigé ici, hors mandat de ce ticket.
- Migrations en attente non liées à BUG-088 (`production/0013`, `clients/0007`, `treasury/0012`,
  détails ci-dessus) — à vérifier si déjà couvertes par un ticket existant.

## Fichiers modifiés
- `d:\Projects\kiesse\backend\clients\serializers.py`
- `d:\Projects\kiesse\backend\clients\tests\test_api.py`
- `d:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (BUG-088 → CORRIGÉ)
