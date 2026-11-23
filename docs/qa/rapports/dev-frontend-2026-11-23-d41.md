# dev-frontend d41 (2026-11-23) : BUG-973 frontend (blocage des ventes après clôture)

## Livré
- `api/services.ts` : type `ClosureStatus`, `treasuryApi.closureStatus.get()`, champ `block_sales_after_closure` sur `BakeryNode`. `api/errors.ts` : `isSalesBlockedError` (403 « Ventes bloquées… »).
- `store/closureStatusStore.ts` : statut, report de la boîte, signal de relecture, hook `useSalesBlocked`.
- `DashboardLayout.tsx` : relecture de `closure-status` au plus toutes les 30 s dans le sondage existant (rôles GERANT/FACTURIER non-HQ) + relecture immédiate sur 403.
- `components/sales/ClosureBlockBanner.tsx` : bannière rouge avec `reason`, affichée dans `Sales.tsx` (Facturation) et `components/clients/SaleModal.tsx` (Enregistrer commande). Boutons « Facturer… » (`InvoiceForm`) et « Confirmer la transaction » (`SaleModal`) désactivés. 403 géré dans `Sales.tsx` et `Clients.tsx` (message du serveur + relecture du statut). Remboursements non touchés (non bloqués côté serveur).
- `components/production/ClosureModal.tsx` : boîte du gérant à l'heure de clôture (enabled, blocked, non validée, gérant non-HQ), sur toute page, cède la place au reste du jour / annonce / désignation d'équipe. Grille catégorie de pain x {Non vendus NV, Déclassés, Sorties gratuites} envoyée via `productionApi.disposals.create` (mêmes types que §3.4, rattachée à la dernière fournée du jour de clôture) ; choix A/B via `productionApi.teamAssignment` (section visible seulement en rotation 24 h). « Plus tard » reporte la boîte pour le jour (la bannière reste).
- `pages/dashboard/Nodes.tsx` : libellé « Heure de clôture », case « Bloquer les ventes après la clôture jusqu'à validation par la direction » envoyée dans le payload.
- `npx tsc --noEmit` et `npm run build` : OK (seul l'avertissement de taille de chunk, préexistant).

## Non vérifié visuellement (aucun navigateur lancé)
- Rendu à 360 / 768 / 1440 px de la bannière, de la grille de `ClosureModal` (défilement horizontal prévu) et de la case de Nodes.
- Parcours réel : activer l'interrupteur, passer l'heure de clôture, voir la boîte, valider, constater que le blocage reste jusqu'à validation direction.
- Pas de test E2E écrit pour ce parcours.

## Points à noter
- Le gérant ne « valide » pas la clôture elle-même : la boîte enregistre les sorties/équipe ; la levée du blocage reste la validation `CashClosure` par la direction (backend).
- Si aucune fournée n'existe ce jour-là, les sorties ne peuvent pas être rattachées (le serveur exige une session) : message affiché, équipe seule possible.
- Si l'équipe est changée alors que le reste du jour précédent est ouvert, l'erreur serveur (`PREVIOUS_WORKDAY_OPEN`) s'affiche dans la boîte.
