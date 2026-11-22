# dev-backend a7 — 2026-11-22 — Isolation du module finance (BUG-384)

Résultat : suspicion NON confirmée. Aucun code applicatif modifié ; matrice de non-régression ajoutée.

## Constat avant/après (identique)
`FinancialYearViewSet.get_permissions()` impose `IsHeadquarters` à toutes les actions (BUG-101) ; les
`IsAuthenticated` des `@action` sont ignorés. Routes (13) : `years/` (GET, POST), `years/<pk>/` (GET, PUT, PATCH,
DELETE), `income_statement`, `cashflow`, `balance_sheet`, `comparative`, `summary`, `doc1_report`, `doc1_export`.

| Rôle | sans `?node=` | `?node=<pk K2>` | `?node=<code K2>` | `?node=ZZZ` |
|---|---|---|---|---|
| anonyme | 401 | 401 | 401 | 401 |
| gérant / facturier / livreur K1 | 403 | 403 | 403 | 403 |
| gérant / facturier / livreur sans boulangerie | 403 | 403 | 403 | 403 |
| ADMIN / DIRECTION / COMPTABLE | 200 (GET) | 200 | 200 | 400 (summary, doc1) |

Aucune donnée de K2 dans les corps de réponse des 403. Écritures (POST/PUT/PATCH/DELETE) refusées aux non-sièges.
Chiffres du siège inchangés (DOC 1 par boulangerie, consolidé).

## Fichiers
- Ajouté : `backend/finance/tests/test_isolation_finance_a.py` (11 tests, tous verts). `manage.py test finance` : 41 tests OK (2 expected failures préexistants). `check` et `makemigrations --check` propres.
- Registre : BUG-384 (REJETÉ, non reproduit) ; aucun code de production touché. Les tests n'ont donc pas « échoué avant » : il n'y avait pas de défaut.

## Décisions à confirmer
1. Gérant : pas d'accès au DOC 1 de sa boulangerie (page Finance réservée au siège dans le menu, MATRICE_PERMISSIONS.md 403). Lecture conservatrice conservée ; la consigne « DOC 1 = gérant de sa boulangerie » ajouterait un droit, à valider avant (ticket de fonctionnalité : borne `user.node_id`, `?node=` ignoré).
2. Comptes sans boulangerie non-siège : 403 (pas « vide »), cohérent avec l'accès siège-seul.

## Risques
`get_permissions()` unique masque les `permission_classes` des `@action` : toute future action en lecture partielle pour les gérants devra revoir cette méthode ; le test matriciel le détectera.
