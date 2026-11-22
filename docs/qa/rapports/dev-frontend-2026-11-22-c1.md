# dev-frontend 2026-11-22 (c1) — BUG-387

Ticket BUG-387 : CORRIGÉ (remarque.md l.472 non cochée, à la demande).

Fichiers : `frontend/src/api/consumablesDirection.ts` (types), `frontend/src/api/services.ts` (`consumablesGlobal`, `inventories`),
`frontend/src/components/production/{GlobalConsumablesSection,NodeInventoryModal,PhysicalInventoryForm}.tsx`, `consumableFormat.ts`,
`IntrantsTab.tsx` (branchement par rôle ; ancien comptage masqué pour le gérant).

Vérifié : `npx tsc --noEmit` 0 erreur ; `npm run build` OK (seul l'avertissement de taille de chunk, préexistant).
Non vérifié : aucun rendu navigateur ni 360 px réel (pas de serveur lancé) ; le responsive repose sur tableaux en `overflow-x:auto`, grilles `auto-fill`, champs `width:100%`.
Test e2e `e2e/tests/35-consommables-direction-dev-b.spec.ts` écrit, NON lancé (ports 8000/5173 possiblement utilisés).
Hypothèses : le gérant compte tous les consommables listés par `stocks` (quantité vide refusée côté client, 0 accepté) ; le lien d'inventaire est ouvert par id de nœud.
Point d'attention : l'alimentation du stock direction (SIEGE) reste via les mouvements existants, sans écran dédié.
