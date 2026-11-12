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



## BUG-229 — client à risque dans la facturation (CORRIGÉ)
- `Sales.tsx` : suppression de l'exclusion `category !== 'RISK'` ; badge « À risque » dans les suggestions, bandeau d'avertissement (BP / plafond) à la sélection ; blocage laissé au serveur (403).
- `npx tsc --noEmit` : OK ; build non lancé. Étapes manuelles : fiche BUG-229.

## BUG-230 — contrat API des ventes (CORRIGÉ)
- `commission_rate` n'est plus envoyé (`Sales.tsx`, `Clients.tsx`, type `InvoiceCreatePayload`) ; reçu de `Clients.tsx` : taux issu de la réponse.
- Vente sans client / « Client Occasionnel » : comptant forcé, versement = commande, champ désactivé, message en français.
- Erreurs de création via `getErrorDetail` ; `breadSummary` (Trésorerie) isolé : 403/400 sans crash. Aucun PATCH/PUT/DELETE sur `/api/sales/invoices/`.
- Validations : quantité entière 1 à 100 000, versement ≥ 0. `npx tsc --noEmit` : OK ; build non lancé. Étapes manuelles : fiche BUG-230.

## BUG-231 (Trésorerie : contrat API BUG-200 à 207) — dev-frontend

Statut : CORRIGÉ (à vérifier par testeur-tresorerie). Fichiers : `frontend/src/pages/dashboard/Treasury.tsx`, `frontend/src/api/services.ts`, `frontend/src/components/treasury/treasuryRules.ts` (nouveau). `npx tsc --noEmit` OK ; build non lancé (consigne).

Résumé : boutons Confirmer/Infirmer/Inscrire réservés au siège ; formulaires journal et épargne réservés gérant+, `node` envoyé seulement par le siège ; billetage 0..100 000 entier validé à l'écran (3 formulaires) et erreurs `bills_x` libellées ; dépense > 0 ; `period_summary` typé en chaînes décimales avec helpers de somme en centimes ; `reports.create` ne porte plus de totaux ; erreurs via `getErrorDetail`. Aucune édition/suppression de journal ni d'épargne n'existait dans l'écran. Étapes de vérification manuelle : voir la fiche BUG-231.

Point ouvert : le formulaire de billetage de clôture reste affiché à tout non-siège (FACTURIER/LIVREUR inclus) ; le serveur répond 403, affiché. À masquer si le client le souhaite.


## BUG-232 — Transferts en litige (Production §3.3)
- Nouveau `components/production/TransferDisputeCard.tsx` (badge litige, quantités envoyée/reçue/écart, recomptage récepteur, « Résoudre le litige » gérant émetteur + siège avec motif obligatoire, message de levée du blocage de clôture) ; `services.ts` : `transfers.resolveDispute` et types stricts ; `Production.tsx` : erreurs de transfert/fournée via `getErrorDetail`, import `axios` retiré.
- Aucune action de modification/suppression de transfert dans l'UI (point 4 sans objet). `npx tsc --noEmit` OK ; build non lancé. Étapes de vérification : fiche BUG-232.
