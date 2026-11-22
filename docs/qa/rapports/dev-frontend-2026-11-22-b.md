# Rapport dev-frontend (Dev B) - 2026-11-22-b

## Ticket traite : BUG-417 volet frontend (CORRIGE frontend)

Cotisation sociale et carte (frais d'imprime) en FC, propres a chaque boulangerie.

### Fichiers
- `frontend/src/api/services.ts` : `BakeryNode.card_fee_fc`, `ClientCommission.cotisation_sociale_fc/carte_fc`, `CmHistoryRow.total_cotisation/total_carte`, type `CommissionSummary`, `commissionsApi.commissions.summary()`.
- `frontend/src/components/commissions/CommissionsTotalsRow.tsx` (nouveau) : `formatFc` (« 2 000 FC ») et ligne de totaux.
- `frontend/src/pages/dashboard/Commissions.tsx` : colonnes « Cotisation sociale (FC) » et « Carte / Frais d'imprime (FC) », totaux, impression, export CSV, fiche de paie.
- `frontend/src/pages/dashboard/Nodes.tsx` (fiche boulangerie) : champ « Carte / frais d'imprime (FC) », cotisation affichee en FC, validation >= 0, defauts 2 000 / 1 000 a la creation.

### Comportement
- Totaux : `GET /api/commissions/commissions/summary/` avec les memes filtres que la liste (boulangerie, mois, annee). Si une recherche ou un filtre de statut est actif, ou si l'appel echoue, la ligne de totaux est la somme des lignes affichees (libelle « TOTAL filtre », message d'avertissement en cas d'erreur API).
- Chargement : « ... » dans la ligne de totaux ; erreur : `detail` affiche. Liste vide : message existant.
- Responsive : le tableau reste dans un conteneur `overflow-x: auto` (pas de debordement de page a 360 px), montants `nowrap`.
- Aucun nouveau `any`. Aucun appel axios ajoute dans une page (Nodes.tsx utilisait deja `apiClient` : non migre, hors perimetre).
- Page Commissions.tsx (< 1 000 lignes) : sous-composant extrait dans `components/commissions/`.

### Verifications
- `npx tsc --noEmit` : 0 erreur. `npm run build` : OK (seul l'avertissement de taille de chunk preexistant).
- E2E non ajoute : necessite une base jetable avec boulangeries et commissions generees.

### Verification manuelle (testeur)
1. Connecte en ADMIN/DIRECTION, ouvrir Boulangeries, modifier K1 : mettre cotisation 2 000 et carte 1 000, enregistrer ; mettre -5 : message d'erreur, rien envoye. Mettre B2 carte 1 500.
2. Commissions CM, mois courant, « Generer Commissions » pour K1 puis B2.
3. Verifier par client : Cotisation = valeur de la boulangerie, Carte = 1 000 (K1) / 1 500 (B2), format « 2 000 FC ».
4. Ligne de totaux en bas = somme des colonnes (comparer au total serveur) ; saisir un nom dans la recherche : libelle « TOTAL filtre » et somme des lignes visibles.
5. Imprimer et Excel : colonnes Cotisation et Carte presentes, totaux coherents.
6. A 360 px : defilement horizontal du tableau, pas de debordement de la page.
Note : les boulangeries existantes gardent leur cotisation (B2 = 2 000, autres 0) : decision client a confirmer.
