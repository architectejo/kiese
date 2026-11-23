# dev-frontend (Dev B) — lot I-3 : statistiques du mois, farine (2026-11-23)
Ticket BUG-1110 : frontend fait.

## Fichiers
- `frontend/src/api/services.ts` : types `FlourMonthStats`, `FlourMonthRow` ; `productionApi.flourMonthStats.get({month, node})`.
- `frontend/src/components/production/FlourMonthStats.tsx` (nouveau) : sélecteur de mois (défaut = mois courant), sélecteur de boulangerie (ADMIN/DIRECTION/COMPTABLE), tableau par jour + pied (total, moyenne jours actifs, moyenne calendaire en gris), soldes et achats, colonnes direction masquées si `direction_visible` est faux, chargement / erreur (`detail`) / vide. Tableau dans un conteneur `overflow-x: auto`.
- `frontend/src/components/production/IntrantsTab.tsx` : section `<details>` « Statistiques du mois — Farine » (ADMIN, DIRECTION, COMPTABLE, GERANT ; pas facturier/livreur car l'onglet n'est pas leur parcours et le serveur répond 403).

## Vérifications
- `npx tsc --noEmit` : sans erreur. `npm run build` : OK (seul l'avertissement de taille de chunk, préexistant).
- Aucun nouveau `any`.

## Non vérifié visuellement
- Rendu réel à 360 / 768 / 1440 px (pas de navigateur lancé, serveurs non touchés) : le débordement de page à 360 px est évité par construction (conteneur défilant), à confirmer.
- Appel réel contre le backend de démonstration, rôle gérant (colonnes direction absentes) et sélecteur de boulangerie.
- La requête part dès l'affichage de l'onglet, même si la section est repliée.
- Le sélecteur de boulangerie se remplit au premier chargement « Toutes » ; au changement de mois il garde la liste.
- Aucun test E2E écrit.
