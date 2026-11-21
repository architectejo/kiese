# Rapport dev-frontend B, 2026-11-21d

## BUG-407 : CORRIGÉ
- Fichier : `frontend/src/App.tsx`. Ajout de `isAllowed` sur 4 routes, alignées sur `DashboardLayout.tsx` (menu) et le backend :
  - `/admin/nodes`, `/admin/users`, `/settings` : ADMIN, DIRECTION (écritures `IsDirection`, matrice : COMPTABLE en 403 sur écriture ; GET users 403 hors HQ).
  - `/activities` : ADMIN, DIRECTION, COMPTABLE (`ActivityLogViewSet` = `IsHeadquarters`).
- Aucun lien de menu à changer (déjà conformes). Écran « Accès refusé » : composant `AccessDenied` de `ProtectedRoute` réutilisé (superuser exempté comme avant).
- BUG-102 : ne couvrait que `/finance` et `/blockchain`, pas de doublon.
- Pas de nouveau `any`. `npx tsc --noEmit` OK, `npm run build` OK.
- E2E : non fait (pas de test statique réalisable sans navigateur). Vérification manuelle : FACTURIER/GERANT, URL directe de chaque route donne « Accès refusé » ; COMPTABLE : `/activities` OK, autres refusées ; ADMIN/DIRECTION : tout OK.
- Statut laissé à CORRIGÉ (pas VÉRIFIÉ). Rien commité.
