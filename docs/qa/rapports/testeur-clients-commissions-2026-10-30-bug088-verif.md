# Rapport testeur-clients-commissions — vérification BUG-088 (2026-10-30)

## Mission
Vérification indépendante de BUG-088 (`ClientCreateSerializer` n'exposait ni `id` ni `code` à la
création) suite à la correction de dev-backend (CORRIGÉ, rapport
`docs/qa/rapports/dev-backend-bug088-2026-10-29.md`).

## Étapes réalisées

1. **Relecture du code corrigé** : `backend/clients/serializers.py::ClientCreateSerializer.Meta`
   contient désormais `'id'` et `'code'` dans `fields` et `read_only_fields`. Conforme au rapport de
   dev-backend, changement strictement limité à la sortie du serializer.

2. **Relance du test de dev-backend** : `backend/clients/tests/test_api.py::
   ClientCreateResponseContractTests::test_create_response_is_missing_id_and_code_bug_088` → **OK**.
   Vérifié le contenu réel de la réponse (pas seulement l'absence d'`@expectedFailure`) :
   `resp.data['id']` et `resp.data['code']` sont bien présents et correspondent au client créé en
   base.

3. **Reproduction indépendante de bout en bout** (nouveau test, écrit par ce testeur, sans réutiliser
   celui de dev-backend) :
   `backend/clients/tests/test_verification_bug088_2026_10_30.py::
   Bug088EndToEndOccasionalClientInvoiceTests::test_occasional_client_creation_then_invoice_creation_end_to_end`.
   Reproduit exactement le flux cassé de `Clients.tsx` (~ligne 596-604, vente directe au comptoir) :
   - `POST /api/clients/clients/` pour créer le « Client Occasionnel » ;
   - lecture de `resp.data['id']`, comme le fait le frontend ;
   - `POST /api/sales/invoices/` avec cet `id` comme `client`, deux lignes de pain, paiement CASH.
   **Résultat : la facture est créée avec succès (201)**, `invoice.client_id` correspond bien à l'id
   reçu à l'étape 1. Avant la correction, `resp.data['id']` aurait été `undefined` et cette deuxième
   requête n'aurait jamais été envoyée (échec silencieux) — confirmé en relisant le code frontend
   (`Clients.tsx` lignes 588-605).
   Utilisateur de test : GERANT, pour respecter le scénario de reproduction d'origine du ticket.

4. **Suite complète** : `python manage.py test clients sales` → 99 tests, 5 échecs, **aucun dans
   `clients/tests/test_api.py` ni dans tout autre test lié à la création de client ou à la
   facturation** :
   - 4 échecs dans `sales/tests/test_bug083_backdated_sales.py`,
     `test_bug083_verification_2026_10_29.py`, `test_e2e_normal_flow_2026_10_29.py` — relancés
     isolément (7,8 s, bien après minuit, sans traversée de jour pendant l'exécution) : **ils
     échouent encore**, de façon identique (écart constant d'un jour). Ce n'est donc pas la
     flakiness « traversée de minuit sur une suite longue » signalée par dev-backend, mais quelque
     chose de reproductible dans le module Ventes/BUG-083 — **sans rapport avec BUG-088** (aucun
     chemin ne passe par `ClientCreateSerializer`). Signalé au coordinateur pour routage vers
     testeur-ventes, hors périmètre de cette mission.
   - 1 échec `clients/tests/test_verification_2026_10_22.py::
     BUG017RealConcurrencyStrictAssertionTests` (« database table is locked ») : flakiness SQLite
     déjà connue et documentée sous BUG-017 — sans rapport avec BUG-088.
   - `python manage.py test commissions` → 23/23 OK (vérification complémentaire du module).

5. **Découverte annexe, hors périmètre strict de BUG-088** : en testant le même scénario avec un
   utilisateur `FACTURIER` (qui a aussi accès à `/clients` et au bouton « Vente Directe » côté
   frontend, sans garde de rôle supplémentaire dans `Clients.tsx`), `POST /api/clients/clients/`
   renvoie **403** (`ClientViewSet.get_permissions()` exige `IsGerant`, qui n'inclut pas FACTURIER).
   Le flux « Client Occasionnel » reste donc cassé — silencieusement — pour ce rôle, avec une cause
   racine différente de BUG-088. Documenté séparément comme **BUG-089** (OUVERT, Majeur, non corrigé,
   en attente de clarification sur le comportement voulu) pour ne pas polluer la fiche BUG-088.

## Conclusion

**BUG-088 → passé à VÉRIFIÉ** dans `docs/qa/REGISTRE_BUGS.md`. La correction de dev-backend est
correcte et suffisante pour le scénario d'origine (rôle GERANT). Aucune régression détectée dans
`clients`, `sales`, `commissions`.

**BUG-089 ouvert** (nouveau, Majeur, OUVERT) : FACTURIER ne peut pas créer de client (y compris le
« Client Occasionnel » auto-créé par la vente directe au comptoir) — 403 côté API, échec silencieux
côté frontend. Nécessite une clarification métier avant correction (le bouton doit-il être masqué
pour FACTURIER, ou FACTURIER doit-il pouvoir créer un client occasionnel ?).

**Point signalé au coordinateur, non traité ici (hors module)** : 4 tests de `sales/tests/
test_bug083_*` et `test_e2e_normal_flow_2026_10_29.py` échouent de façon reproductible (écart d'un
jour, pas une simple traversée de minuit) — à router vers testeur-ventes.

## Fichiers modifiés/créés
- `d:\Projects\kiesse\backend\clients\tests\test_verification_bug088_2026_10_30.py` (nouveau test de
  reproduction indépendant).
- `d:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (BUG-088 → VÉRIFIÉ avec section « Vérification »
  détaillée ; nouvelle fiche BUG-089 OUVERT).
- `d:\Projects\kiesse\docs\qa\rapports\testeur-clients-commissions-2026-10-30-bug088-verif.md` (ce
  rapport).
