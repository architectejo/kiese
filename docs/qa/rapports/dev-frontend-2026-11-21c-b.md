# Rapport dev-frontend B, 2026-11-21 (c)

- BUG-405 CORRIGÉ : `frontend/src/App.tsx` (`isAllowed` ADMIN/DIRECTION sur `/admin/backups`), `frontend/src/pages/dashboard/Administration.tsx` (écran « Accès refusé » si rôle insuffisant).
- BUG-406 CORRIGÉ : `frontend/src/components/shared/ThermalReceipt.tsx` lit `window.kiese?.printerWidthMm ?? 80` par défaut ; commentaire périmé supprimé.
- `npx tsc --noEmit` et `npm run build` : OK. Pas de test de composant (Vitest : seul `api/errors.test.ts`) ; procédure manuelle dans les fiches.
- Même défaut signalé, non corrigé : dans `App.tsx`, `/admin/nodes`, `/admin/users`, `/settings` (menu ADMIN/DIRECTION) et `/activities`, `/blockchain` (menu ADMIN/DIRECTION/COMPTABLE, à vérifier : BUG-102 a pu en traiter) n'ont pas d'`isAllowed` ; à confirmer par ticket.
