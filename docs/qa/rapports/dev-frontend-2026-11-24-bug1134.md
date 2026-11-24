# Rapport dev-frontend (B) : date de travail serveur, journée de midi à midi (BUG-1134)

Date : 2026-11-24. Lié : BUG-1130 (backend). Aucun commit, aucun push, backend non modifié.

## Cause
`store/workDateStore.ts` considérait l'annonce serveur comme périmée dès que le jour CALENDAIRE du navigateur changeait, et retombait sur la date locale. Avec la journée de midi à midi, entre 00:00 et 12:00 la journée de travail est celle de la veille. Plusieurs écrans calculaient aussi mois/jour par défaut avec `new Date()`.

## Correctif
`workDateStore.ts` (source unique, aucun nouvel endpoint ni minuteur) :
- annonce serveur conservée et avancée à la prochaine heure de clôture (D se termine à D+1 à l'heure de clôture) ;
- heure de clôture mémorisée (`handover`, 12:00 par défaut), alimentée par `team-assignment.handover_time` via `feedWorkDate` (`api/services.ts`) ;
- repli avant toute réponse : horloge locale décalée à l'heure de clôture (`businessDayOf`) ;
- helpers : `businessDayOf`, `shiftIsoDate`, `workDateMonthYear` ; `useWorkDate`, `getWorkDate`, `useSelectedWorkDay` conservés.

Champs serveur utilisés (déjà exposés) : `shift-end-status.current_work_date`, `team-assignment.work_date` + `handover_time`, `opening-confirmation.work_date`, `bread-stocks/by-date` et `daily-closure` (`work_date`).

## Fichiers modifiés (frontend/src)
- `store/workDateStore.ts`, `store/shiftEndStore.ts`, `api/services.ts`
- `components/production/IntrantsStatsTab.tsx`, `FlourMonthStats.tsx`, `productionHelpers.ts` (`isOnDay` rattache l'horodatage à sa journée comptable)
- `components/treasury/JournalSection.tsx`, `SavingsSection.tsx`, `ExpenseHistoryModal.tsx`
- `components/clients/ClientInvoiceHistoryTab.tsx`, `components/shared/CalendarPicker.tsx`
- `pages/dashboard/Clients.tsx`, `Commissions.tsx`, `Finance.tsx`, `Dashboard.tsx`

`clotureRecap.ts` : la date imprimée vient du paramètre `today` (déjà `useWorkDate()`) ; `new Date().toLocaleString` n'y sert que d'horodatage d'impression. Inchangé.

## Résultats
- `npx tsc --noEmit` : aucune erreur.
- `npm run build` : OK (seul avertissement existant : chunk > 500 kB).
- Pas de nouveau `any`. Pas de test E2E pour ce parcours ; pas de test unitaire frontend dans le dépôt.

## Vérification manuelle (testeur)
1. Réglage de l'horloge du poste (ou serveur) à 09:00 : Trésorerie, Production (stock du jour, Stats intrants), Ventes : la date affichée par défaut est celle de la VEILLE ; à 12:01 elle passe au jour courant (au prochain sondage de 10 s, ou au plus tard au rechargement).
2. Le 1er du mois à 09:00 : Journal, Épargne, Historique des dépenses, Commissions, Stats farine ouvrent sur le mois précédent.
3. Largeur 360 px : aucun changement de mise en page.

## Ce qui reste / à signaler
- Le rendu ne se rafraîchit pas seul à midi pile sans nouvelle réponse serveur (le sondage de 10 s de `shift-end-status` suffit en pratique ; sans session connectée au layout, rechargement).
- Le calcul d'extrapolation et le repli utilisent le fuseau du navigateur (supposé identique à celui du serveur, Kinshasa).
- Heure de clôture : seule `team-assignment` (rotation) la fournit ; hors rotation on garde 12:00 (par défaut serveur). Un champ `handover_time` dans `shift-end-status` hors rotation serait plus propre (demande éventuelle à dev-backend, non bloquant).
- Non touchés volontairement : `Finance.tsx` création de l'exercice (année calendaire), dates d'impression (« Imprimé le »), `ThermalReceipt` (date réelle de transaction), `chatUtils`, `CalendarPicker` interne. Commissions/mois suivent `invoice_date` : question client BUG-1132.
