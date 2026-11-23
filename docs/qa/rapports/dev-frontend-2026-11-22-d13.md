# Rapport dev-frontend (Dev B) — 2026-11-22 d13

Tickets : BUG-655 et BUG-656 passés à CORRIGÉ (jamais VÉRIFIÉ). remarque.md non modifié.

- BUG-655 : `frontend/src/pages/dashboard/ClotureJournaliere.tsx` : suppression de la liste d'aides Régularisation / Non Servi et du paragraphe « Excédent et manquant pains… » sous « Décomposition par Catégorie de Pain ». La ligne « Total Non servi » reste (explication en infobulle). Exports Excel/PDF inchangés.
- BUG-656 : `frontend/src/components/production/IntrantsTab.tsx` : ADMIN/DIRECTION/COMPTABLE ne reçoivent que `GlobalConsumablesSection` (vue globale, orientation, approvisionnement direction, inventaire physique par boulangerie). Gérant et autres rôles inchangés.

Vérifications : `npx tsc --noEmit` OK ; `npm run build` OK (seul avertissement existant : taille des chunks). Aucun nouveau `any`. Pas de E2E sur ces écrans ; vérification manuelle décrite dans les tickets.
