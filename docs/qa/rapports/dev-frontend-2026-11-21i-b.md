# Rapport dev-frontend (B), 2026-11-21 (i) : BUG-415

- Diagnostic : défaut antérieur au découpage de `Clients.tsx` (wrapper du tableau identique avant 2d46389).
- Correctif : colonne Actions `sticky` à droite sous 640 px (`ClientsTable.tsx` + règle `.col-actions-sticky` dans `styles/index.css`). Bureau inchangé.
- Test : `32-clients-pos-dev-b.spec.ts`, `test.fixme` retiré ; helper de défilement vertical corrigé (le défilement est porté par un conteneur, pas par `window`). Rejeu 360 px : rouge sans correctif, 2/2 verts avec.
- Environnement : base jetable (migrate, seed_kiese, setup1/2) hors dépôt, Chrome ms-playwright via config temporaire ; serveurs arrêtés, config/test-results/dist/base supprimés.
- `npx tsc --noEmit` : 0 erreur ; `npm run build` : OK.
- BUG-415 : CORRIGÉ (non vérifié). Aucun fichier backend touché.
