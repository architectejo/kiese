# Rapport dev-backend (B) - 2026-11-21g - BUG-506

Statut : CORRIGÉ (volet core / clients / commissions / sync). Non commité.

## Cause
Aucune validation rôle/nœud à la création ni à la modification d'un utilisateur ; les `get_queryset` ne filtraient que si `user.node_id` était renseigné.

## Correction
- `core/serializers.py` : `BAKERY_BOUND_ROLES` + `check_node_required(role, node)` (400, `{"node": "Une boulangerie est obligatoire pour le rôle Gérant, Facturier ou Livreur."}`).
- `core/views.py` (`UserViewSet.perform_create` / `perform_update`) : appel après les contrôles de droits (BUG-247 reste en 403) ; couvre POST, PATCH `node=null`, changement de rôle vers GERANT/FACTURIER/LIVREUR sans nœud. ADMIN/DIRECTION/COMPTABLE sans nœud restent permis.
- `core/mixins.py` : `is_node_less_non_hq(user)` ; utilisé dans 8 `get_queryset` (core : notifications, colis ; clients : clients, contributions, distributions, lignes ; commissions : périodes, commissions) -> `qs.none()`. sync : routes HQ ou jeton de nœud, rien à changer.
- `core/management/commands/check_users_sans_noeud.py` : commande lecture seule. Pas de migration (aucune modification automatique de comptes).

## Tests
`core/tests/test_bug506_user_sans_noeud.py` (9 tests). Preuve d'échec sans correctif par mock : `test_orphan_defense_depends_on_guard` (garde désactivée -> le facturier orphelin voit les clients) et `test_validation_depends_on_guard` (validation désactivée -> 201).

## Tests `@expectedFailure` de test_verif_matrice_c.py
- `IsolationExtra::test_non_hq_user_cannot_be_created_without_node` : passe en « unexpected success » -> C peut retirer la marque.
- `IsolationExtra::test_node_less_non_hq_sees_nothing_cross_node` et `IsolationProduction::test_bug147_node_less_non_hq_account_cannot_reach_other_nodes` : restent en échec attendu, car dépendent des `get_queryset` de production/sales/treasury (à A). Marque à conserver.

## Risques / à noter
- Un compte orphelin existant en base ne voit plus rien (au lieu de tout) ; lancer `python manage.py check_users_sans_noeud` en production pour les repérer.
- Frontend : la création/édition d'utilisateur reçoit désormais une erreur de champ `node` (400) ; le formulaire doit la afficher (pas de ticket ouvert, à signaler à dev-frontend).
- Les fichiers `core/views.py` ont des fins de ligne mixtes d'origine ; conservées.

## Suite complète (core clients commissions sync)
733 tests : aucun FAIL ni ERROR ; skipped=1, expected failures=6, unexpected successes=1 (le test de création sans nœud de BUG-506, attendu : C retire la marque). Le statut global « FAILED » vient uniquement de ce succès inattendu. `makemigrations --check --dry-run` : voir sortie ci-dessous dans la réponse.

## BUG-511 (CORRIGÉ)
`period__month` et `period__year` ajoutés aux `filterset_fields` de `ClientCommissionViewSet` (commissions/views.py). Tests : `commissions/tests/test_bug511_filtre_periode.py` (4 : mois+année, année seule, mois seul, combiné avec nœud, périmètre gérant conservé). Pas de changement de contrat (paramètres optionnels) ; dev-frontend peut les passer directement.
