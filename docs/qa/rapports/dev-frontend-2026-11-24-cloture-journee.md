# dev-frontend (dev-b) - clôture de journée, 2026-11-24 (message #45-A, BUG-1119)

## Déjà conforme
1. `shiftEndStatus` : `DashboardLayout.tsx` l'appelle au montage puis toutes les 10 s (GERANT/FACTURIER/LIVREUR non-Siège). Il déclenche `auto_close_due_days` côté serveur (BUG-1074).
2. Reste de la journée : `reste_du_jour_jour` (un par catégorie, sans équipe) dans le rapport ; clôture forcée/volontaire = une quantité par catégorie.
3. NV / déclassés / sorties gratuites : colonnes déjà affichées dans `ClotureJournaliere.tsx`, saisies dans `ClosureModal.tsx`.
4. Responsive : tableau dans un conteneur `overflowX: auto` ; modales avec champs 44 px.

## Modifié
- `api/services.ts` : `soldes_declares?` sur `DailyClosureCategory`.
- `pages/dashboard/ClotureJournaliere.tsx` : colonne « Soldés déclarés » ; bandeau.
- `components/production/AutoClosedDayBanner.tsx` (nouveau) : message de clôture automatique (notification non lue du nœud/jour consulté), bandeau info ou avertissement (réconciliation vide).
- `CloseSessionModal.tsx`, `ClosureModal.tsx` : libellés « un seul reste par catégorie, pas par équipe ».

## Limites
- Le bandeau dépend de la notification (disparaît une fois lue) : BUG-1120 ouvert pour dev-backend.
- Exports Excel/impression : colonne soldés non ajoutée.
- Pas de test E2E existant pour ce parcours ; vérif à 360 px non faite au navigateur.

## Vérification manuelle
Boulangerie avec `block_sales_after_closure`, fournée ouverte, livraison du jour, heure de clôture + 30 min dépassée : ouvrir l'appli en gérant, puis Clôture Journalière : bandeau « Fournée clôturée automatiquement » et colonne « Soldés déclarés ». `npx tsc --noEmit` et `npm run build` : OK.
