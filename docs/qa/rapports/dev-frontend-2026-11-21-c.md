# dev-frontend (Dev C) — 2026-11-21
BUG-175 (défaut résiduel) : CORRIGÉ. Fichier : frontend/src/pages/dashboard/Treasury.tsx.
- `reports` = liste serveur filtrée `date === today` ; nouveau `pastReports` (extraReports, date != today, filtre boulangerie).
- Nouveaux handlers `handleValidatePastReport`, `handlePrintPastReport` ; tableau « Rapports rétroactifs » sous le tableau du jour.
- tsc --noEmit : 0 erreur ; npm run build : OK (avertissement de taille de chunk préexistant).
- E2E 06 et 22 non impactés (aucune référence aux rapports rétroactifs). Vérification manuelle : voir fiche BUG-175.
