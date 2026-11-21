# Rapport testeur-permissions B, 2026-11-21d : vérification de BUG-407

Verdict : **BUG-407 VÉRIFIÉ** (lecture de code + test statique ; aucun navigateur).

## Contrôles
1. Cohérence backend : `/activities` = ADMIN, DIRECTION, COMPTABLE (`ActivityLogViewSet` = `IsHeadquarters`). `/admin/nodes`, `/admin/users`, `/settings` = ADMIN, DIRECTION (écritures `IsDirection` sur Node, User, Config, prix). Aucun rôle légitime bloqué ; aucun rôle non autorisé admis. Le superuser passe (`!user.is_superuser`), comme côté API. Note : COMPTABLE lit `/users/` via l'API (`IsHeadquarters`) mais n'a ni menu ni route, ce qui est restrictif et voulu.
2. Sidebar (`DashboardLayout.tsx`) : les 4 routes ont exactement les mêmes rôles que le menu, à l'identique pour ADMIN, DIRECTION, COMPTABLE, GERANT, FACTURIER, LIVREUR. `/admin/backups` (BUG-405) est aussi aligné.
3. `ProtectedRoute` : les enfants ne sont montés qu'après `checked` puis `isAllowed`, donc aucun flash de contenu et aucune requête de la page avant le refus. Le refus affiche `AccessDenied` dans `DashboardLayout` (pas de redirection, lien vers le tableau de bord). Seules les requêtes du layout partent. Cas limite théorique : `isAllowed && user &&` laisse passer si `user` est null alors que `isAuthenticated` est vrai. `fetchCurrentUser` est attendu avant `checked`, et sur échec il remet `isAuthenticated` à faux, donc non exploitable.
4. Routes sans garde : voir BUG-411 (ouvert, Mineur) : `/dashboard`, `/clients`, `/sales/*`, `/production`. L'API protège, donc pas de fuite. Pas déjà couvert par BUG-102, BUG-242 ou BUG-405. Les routes `/commissions`, `/treasury`, `/cloture-journaliere`, `/finance`, `/blockchain` et `/admin/backups` sont gardées.

## Exécuté
- `backend/core/tests/test_verif_bug407_testeur_permissions.py` : 5 tests OK (`DJANGO_DEBUG=True python manage.py test core.tests.test_verif_bug407_testeur_permissions`). Il extrait par regex la table route->rôles d'`App.tsx` et celle du menu, les compare, vérifie la grille rôle x route (6 rôles x 5 routes) et l'ordre attente / refus / rendu des enfants dans `ProtectedRoute`.
- `cd frontend && npx tsc --noEmit` : OK, 0 erreur.

## Non exécuté
- Aucun test en navigateur (Chromium/Playwright non installés, disque quasi plein). Spec écrit, non lancé : `e2e/tests/31-verif-bug407-dev-b.spec.ts`. Les identifiants `zz_demo_comptable` et `zz_demo_direction` sont supposés et sont à confirmer dans le seed e2e.
- Le test Python est statique (regex sur le source) : il ne prouve pas le rendu réel.

## Registre
BUG-407 passé à VÉRIFIÉ. BUG-411 ouvert (Mineur). Registre modifié ; rien de commité.
