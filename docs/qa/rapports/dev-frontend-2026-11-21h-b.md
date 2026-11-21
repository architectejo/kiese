# Rapport dev-frontend B — 2026-11-21h

Demandes du Dev C (message #13).

1. `frontend/src/pages/dashboard/Commissions.tsx` : suppression de la lecture préalable des périodes et du filtrage côté client. `commissionsApi.commissions.page` reçoit directement `period__node`, `period__month`, `period__year` (BUG-511). Comportement visible inchangé (sélecteurs avec « Tous », titre, bandeau, totaux, impression, CSV, fenêtre Générer). Erreur de chargement : bandeau unique avec « Réessayer » (`commissionsQ.error`). Aucun nouveau `any`.
2. `frontend/src/pages/dashboard/Users.tsx` : message de secours neutre dans `getErrorDetail`.
3. Registre : lignes « Complément (dev-frontend, 2026-11-21) » ajoutées à BUG-412 et BUG-413 (CRLF conservé), CORRIGÉ, à vérifier par C.

Vérifs : `npx tsc --noEmit` 0 ; `npm run build` OK (avertissement de taille de chunk préexistant) ; `frontend/dist` supprimé (ignoré par git). Non rejoué en navigateur.
Vérification manuelle : Commissions, changer mois/année/boulangerie, vérifier que la requête réseau porte `period__month`/`period__year` et que la liste correspond.
