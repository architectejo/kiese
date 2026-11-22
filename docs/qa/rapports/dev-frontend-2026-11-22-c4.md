# Rapport dev-frontend 2026-11-22 (c4) : BUG-823 volet frontend

- `frontend/src/api/services.ts` : `Doc1Row.qty_other?: number` (optionnel, tolère l'ancien backend).
- `frontend/src/pages/dashboard/Finance.tsx` : colonne « Autres » (en-tête, cellules, totaux), `?? 0`. Pas d'extraction : modification mineure. Tableau déjà dans `overflowX: auto`.
- `npx tsc --noEmit` OK ; `npm run build` OK (seul l'avertissement de taille de chunk, préexistant).
- Aucun nouveau `any`. Pas de commit.
- Registre : note ajoutée à la fiche BUG-823, statut inchangé (CORRIGÉ).
- Vérification manuelle : facturer à un prix hors tarif standard, Finance > DOC 1, colonne « Autres » et total.
