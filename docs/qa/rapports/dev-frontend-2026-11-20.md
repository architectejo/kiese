# Rapport dev-frontend 2026-11-20

## BUG-316 (frontend) : CORRIGÉ
- Fichier : `frontend/src/components/clients/SocialDistributionPanel.tsx`.
- Cause : l'input TARIF et le bouton OK étaient proposés à tous les rôles alors que l'API refuse désormais (403) les non ADMIN/DIRECTION/superuser.
- Correction : `canSetTarif` (rôle via `useAuthStore`) ; sinon le tarif est affiché en lecture seule avec infobulle. L'erreur 403 reste affichée avec le `detail` de l'API (`getErrorDetail`). Aucun nouveau `any`.
- Vérification manuelle : gérant = tarif en texte seul ; direction/admin = input + OK, enregistrement OK.
- `tsc --noEmit` et `npm run build` : voir résultat dans le message de retour.
- Ticket laissé à CORRIGÉ (pas de VÉRIFIÉ).
