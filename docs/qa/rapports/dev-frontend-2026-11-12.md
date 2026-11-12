# Rapport dev-frontend, 2026-11-12

## BUG-161 : F2 (suite) et F3, volet frontend de B3/B4/B5 (statut : CORRIGÉ partiel, la ligne BUG-161 reste ouverte pour B6)

Détail complet et étapes de vérification manuelle : `docs/qa/REGISTRE_BUGS.md`, sous-section « F2/F3 — CORRIGÉ (dev-frontend, 2026-11-12) » de la fiche BUG-161.

### Fichiers modifiés ou créés (frontend uniquement)
- Nouveau : `frontend/src/store/workDateStore.ts` (date de travail fournie par le serveur, repli sur la date locale, jamais UTC).
- `frontend/src/api/services.ts` : types (`work_date`, `server_now`, `rotation`, `team`, `current_work_date`, `team` facultatif du POST d'ouverture) ; alimentation du store par les réponses existantes.
- `frontend/src/components/production/OpeningStockConfirmationModal.tsx`, `CloseSessionModal.tsx`, `AutoClosedNoticeModal.tsx`, `StockDuJourSection.tsx`, `ReconciliationPanel.tsx`.
- `frontend/src/store/shiftEndStore.ts`, `teamAssignmentStore.ts`.
- `frontend/src/components/layout/DashboardLayout.tsx`, `frontend/src/components/shared/CalendarPicker.tsx`.
- `frontend/src/pages/dashboard/Production.tsx`, `Sales.tsx`, `Treasury.tsx`, `ClotureJournaliere.tsx`, `Clients.tsx`, `Dashboard.tsx`, `Commissions.tsx`.

### Points d'attention
- Détection de la relève : le sondage existant de 10 s du layout fait maintenant relire `opening-confirmation` à la boîte « Stock de départ » (compteur `pollKey`, rotation seulement). Avant, elle ne se relisait qu'au montage et au changement de route. Pas de second `setInterval`.
- Ordre à la relève, en rotation : reste du jour (boîte forcée ou annonce) -> désignation d'équipe -> stock de départ. Il change la priorité de F2 (désignation d'abord), conformément à la consigne ; la saisie de la boîte forcée n'est plus jamais démontée ni masquée par la désignation (BUG-166/188 préservés).
- Décision à noter : `shift-end-status` alimente le store avec `current_work_date` et non `work_date` (qui peut être la journée à clôturer).
- Limites : KPI « sorties du jour » approximatif en rotation entre minuit et la relève (l'API des sorties n'a pas de `work_date`, amélioration possible côté dev-backend) ; store global pour un utilisateur Direction qui consulte des boulangeries de relèves différentes.
- Aucun nouveau `any`.

### Contrôles
- `npx tsc --noEmit` : aucune erreur.
- `npm run build` : réussi (seul l'avertissement de taille de chunk préexistant).
- Pas de Playwright (base réelle interdite) ; pas d'outillage de test composant dans le projet. Étapes manuelles dans le registre (rotation active : relève, reste du jour, désignation, stock de départ pré-rempli ; entre 00:00 et 01:00 : date correcte ; sans rotation : inchangé ; 360 px).
- Aucun fichier backend, aucune commande git de modification, aucune donnée de `db.sqlite3` touchée.

## BUG-195 (fournée en rotation) et volet frontend BUG-196
- `Production.tsx` : en rotation, sélecteur d'équipe remplacé par « Équipe de service : X » (verrouillé) ; création de fournée sans `team` ni `date` ; équipe non désignée ou 403 `TEAM_NOT_ASSIGNED` -> message + ouverture de la boîte de désignation. Hors rotation inchangé. Aucun autre envoi d'équipe trouvé dans les composants production.
- `TeamAssignmentModal.tsx` + `api/errors.ts` : gestion du 400 `PREVIOUS_WORKDAY_OPEN` (message clair, « Réessayer », relance automatique toutes les 5 s, boîte non bloquée).
- `npx tsc --noEmit` : aucune erreur ; `npm run build` non lancé (consigne du coordinateur). Aucun nouveau `any`. Étapes manuelles dans les fiches BUG-195 et BUG-196.

