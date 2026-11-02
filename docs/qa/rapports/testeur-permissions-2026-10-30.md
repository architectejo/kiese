# Rapport testeur-permissions — 2026-10-30

## Objet
Vérification indépendante du correctif BUG-102 (dev-frontend) : garde de route manquante sur
`/finance` et `/blockchain` dans `frontend/src/App.tsx`.

## Vérifications effectuées
1. **Relecture du diff `App.tsx`** : `ProtectedRoute` accepte `isAllowed?: (user: UserProfile) =>
   boolean` ; si non satisfait (et utilisateur non superuser), rend `<DashboardLayout><AccessDenied
   /></DashboardLayout>` au lieu des enfants. `AccessDenied` affiche un titre, un message et un lien
   `Link to="/dashboard"` — pas d'exception, layout dashboard conservé.
2. **Conformité avec la permission backend réelle** :
   - `/finance` → `isAllowed={(u) => u.is_headquarters}`. `backend/finance/views.py` :
     `FinancialYearViewSet.get_permissions()` retourne `[IsHeadquarters()]` pour **toutes** les actions
     (y compris `summary`/`doc1_report`/`doc1_export`, dont le `permission_classes=[IsAuthenticated]`
     déclaré sur l'`@action` est ignoré par DRF puisque le ViewSet surcharge `get_permissions`).
   - `/blockchain` → même garde. `backend/blockchain/views.py` : `TamperAlertViewSet` et
     `BlockchainSnapshotViewSet` imposent `IsHeadquarters` sur toutes leurs actions.
   - `IsHeadquarters` (`core/permissions.py`) ⇔ `User.is_headquarters` (`core/models.py`) :
     `is_superuser or role in (ADMIN, DIRECTION, COMPTABLE)`. Correspondance exacte avec le garde
     frontend. **Aucun écart.**
3. **Non-régression** : toutes les autres routes dashboard (`/production`, `/commissions`,
   `/treasury`, `/admin/nodes`, `/admin/users`, `/settings`, `/admin/backups`, `/clients`, `/sales/*`,
   `/activities`, `/dashboard`) gardent `<ProtectedRoute>` sans `isAllowed` — comportement par défaut
   inchangé. Seul `App.tsx` a été modifié.
4. **Compilation** : `npx tsc --noEmit` → aucune erreur. `npm run build` → succès (exit 0), `dist/`
   généré ; avertissements de taille de chunk (minifier legacy) sans rapport avec ce correctif.
5. **Reproduction interactive navigateur** : non exécutée (pas de backend + jeu de démo lancés dans
   cette session). Confiance fondée sur l'analyse de code (garde frontend ↔ permission backend
   identiques, logique `ProtectedRoute`/`AccessDenied` standard React Router, pas de branche pouvant
   lever une exception). Recommandation : si une preuve interactive complète est requise, créer un
   test Playwright dédié (aucune suite e2e n'existe encore pour ce scénario précis).

## Verdict
**BUG-102 → VÉRIFIÉ.**

## Point annexe : incohérence menu / `is_headquarters`
Le dev avait signalé une incohérence générique entre le filtre de menu par rôles
(`DashboardLayout.tsx`) et la permission backend réelle. Vérification détaillée :
- `/finance` : rôles de menu `['ADMIN','DIRECTION','COMPTABLE']` = exactement `is_headquarters`. Pas
  d'écart.
- `/blockchain` : rôles de menu `['ADMIN','DIRECTION']` (COMPTABLE absent), alors que
  `is_headquarters`/la route/l'API autorisent aussi COMPTABLE. Écart **réel** mais dans le sens
  restrictif (le menu cache un accès légitime, aucune fuite de permission). Ouvert comme **BUG-104**
  (mineur, frontend) dans `docs/qa/REGISTRE_BUGS.md`, avec suggestion de correction pour dev-frontend
  (ajouter `'COMPTABLE'` à la liste de rôles de l'entrée `/blockchain`, sous réserve de validation
  métier par le coordinateur).

## Fichiers concernés
- `D:\Projects\kiesse\frontend\src\App.tsx` (lu, non modifié)
- `D:\Projects\kiesse\backend\finance\views.py`
- `D:\Projects\kiesse\backend\blockchain\views.py`
- `D:\Projects\kiesse\backend\core\permissions.py`
- `D:\Projects\kiesse\backend\core\models.py`
- `D:\Projects\kiesse\frontend\src\components\layout\DashboardLayout.tsx`
- `D:\Projects\kiesse\frontend\src\store\authStore.ts`
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (BUG-102 → VÉRIFIÉ, BUG-104 ouvert)
