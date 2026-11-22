# Rapport dev-frontend (Dev B), 2026-11-22 d9

## BUG-862 : CORRIGÉ
- Cause : la bordure du bandeau de vérification (`Blockchain.tsx` l.130) utilisait `allIntact ? success : danger`. `allIntact` vaut false dans les états neutres (JAMAIS VÉRIFIÉ, VÉRIFICATION PARTIELLE), d'où une bordure rouge sous un badge orange.
- Correctif : `borderLeft: 4px solid hsl(var(--${tone}))`, la même variable `tone` que le badge (warning / success / danger). Aucun `any` ajouté.
- Fichier : `frontend/src/pages/dashboard/Blockchain.tsx`.
- Vérifications : `npx tsc --noEmit` OK ; `npm run build` OK (seul l'avertissement de taille de chunk, déjà présent).
- Vérification manuelle (testeur) : ouvrir l'écran Blockchain sans vérification récente. La bordure doit être orange, comme le badge. Elle doit être verte quand tout est intègre et rouge en cas d'altération.
- Registre : BUG-862 à CORRIGÉ (non VÉRIFIÉ). Aucun commit.
