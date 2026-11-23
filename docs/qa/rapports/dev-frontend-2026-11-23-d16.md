# Rapport dev-frontend (Dev B d16) - 2026-11-23
BUG-674..677 : volet frontend fait (statut CORRIGE inchange).
- 674 : `components/production/DisposalJournal.tsx` (nouveau, branché dans `ReconciliationTab.tsx`) : date -> `productionApi.disposals.list({date, node})`.
- 675 : `ClotureJournaliere.tsx` : Appro Reçu affiché en négatif (le backend renvoie des valeurs positives, soustraites du total).
- 676 : `totals.repartition_base` (type dans `services.ts`) affiché sous « Répartition par Catégorie ».
- 677 : `ExpenseCategory.scope` (types + `ExpenseCategoriesSection.tsx`, libellés français). Formulaire de dépense locale : déjà limité aux catégories de l'API.
Vérifs : `npx tsc --noEmit` et `npm run build` OK. Pas d'E2E ; contrôle manuel à faire à 360 px. Export Excel/impression de la clôture non modifiés (Appro Reçu y reste positif).
