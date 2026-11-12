
## BUG-170 — Confirmation d'envoi d'une demande de transfert (Production §3.3)
- Statut : CORRIGÉ (à vérifier par le testeur).
- Fichier : `frontend/src/pages/dashboard/Production.tsx` (états `tSending`/`tSuccess`, `handleCreateTransfer`, formulaire §3.3). Pas d'extraction (~25 lignes).
- Comportement : message vert persistant « Demande envoyée à <boulangerie> : N pains demandés — en attente de réponse. » (fermeture par « × », prochain envoi ou modification du formulaire ; pas de minuteur) ; bouton désactivé « Envoi en cours… » pendant la requête ; erreurs inchangées.
- Contrôles : `npx tsc --noEmit` sans erreur ; `npm run build` OK (seul l'avertissement de taille de chunk préexistant). Pas de test E2E existant pour ce parcours : étapes manuelles dans la fiche BUG-170 du registre.

## BUG-163 — Chargement progressif des listes (lot 1 : hook partagé, Activités, Notifications, Users, Dashboard)
- Statut : CORRIGÉ (à vérifier par le testeur). BUG-164 non traité.
- Nouveau hook `frontend/src/hooks/useProgressiveList.ts` (bâti sur `getPage()`, `getList()` intact) : page 1 immédiate, pages suivantes en arrière-plan (`auto`, avec `stopWhen`) ou à la demande (`manual`/`loadMore`), `loadAll`, annulation par identifiant de requête, états `isLoading`/`isLoadingMore`/`loaded`/`total`/`isComplete`/`error`.
- Activités : bouton « Voir plus » + « X affichée(s) / Y au total ». Notifications : « Voir plus » dans la boîte « Toutes les Notifications », pages supplémentaires séparées du sondage de 10 s, compteur de non lues inchangé, BUG-156/157 non touchés. Users : chargement complet (`coreApi.users.list`), erreurs affichées. Dashboard : plus de chargement intégral ; KPI risques = `count` serveur ; graphique « Calcul en cours… X / Y » jusqu'aux 7 derniers jours lus ; historique des factures et tableaux par boulangerie chargés à la demande avec indicateur de progression.
- Fichiers : `hooks/useProgressiveList.ts`, `api/services.ts`, `pages/dashboard/{Activities,Users,Dashboard}.tsx`, `components/layout/DashboardLayout.tsx`. `Production.tsx` non touché.
- `npx tsc --noEmit` : aucune erreur. `npm run build` : OK (seul l'avertissement de taille de chunk préexistant). Pas de Playwright (base réelle). Étapes manuelles : fiche BUG-163 du registre.
- Point à signaler : l'aperçu des 4 alertes risque est trié par nom (tri de la liste paginée) au lieu de boulangerie+nom. Aucun endpoint backend créé ; un endpoint agrégé CA par jour serait un plus (non bloquant).

## BUG-164 — Chargement progressif des listes (lot 2 : Trésorerie, Commissions, Blockchain, Production, Sales)
- Statut : CORRIGÉ (à vérifier par le testeur). Détail, règles appliquées et étapes manuelles par page : fiche « Correction BUG-164 » du registre.
- Fichiers : `frontend/src/api/services.ts` (fonctions `page()` ajoutées, `getList()` intact), `pages/dashboard/{Treasury,Commissions,Blockchain,Production,Sales}.tsx`. Aucun fichier backend.
- Règle : totaux/soldes/KPI/compteurs/impressions/exports calculés côté client = affichés seulement quand la liste est complète (« calcul en cours… X/Y » sinon) ; impressions/exports désactivés (avec progression) jusqu'à la complétude ; annulation au changement de filtre.
- `consolidatedBalance` (Trésorerie) : tiré de la page 1 triée par le serveur (`-date,-created_at`, valeur stockée `running_balance`) — justification dans la fiche ; ne jamais re-trier côté client.
- Production : 15 fournées / 20 sorties demandées au serveur ; KPI « Pains non valorisés » désormais exact même au-delà de 20 sorties du jour ; transferts : pas de filtre serveur « boulangerie impliquée » (backend non touché) -> filtre `transfer_status` existant (actifs en entier, 3 derniers confirmés).
- Contrôles : `npx tsc --noEmit` sans erreur ; `npm run build` OK (seul l'avertissement de taille de chunk préexistant). Pas de Playwright (base réelle).
- Reste hors périmètre : `Treasury.tsx` (≈2 700 lignes) et `Production.tsx` ne sont pas découpés (modifications de chargement/affichage ciblées, pas de nouveau composant extrait) ; sessions du jour, `breadSummary` et comptages physiques Direction de Trésorerie conservés en lecture complète (volume borné).

## BUG-171 / 172 (volet frontend) / 173 / 174 / 175 — Lot de revue du chargement progressif
- Statuts : BUG-171, 173, 174, 175 CORRIGÉ (à vérifier par les testeurs d'origine) ; BUG-172 : volet frontend corrigé, statut de la ligne inchangé (volet backend à part).
- BUG-172 : `useProgressiveList` : `isComplete` exige `loaded === total` ; un rechargement automatique puis `isInconsistent` + erreur « Données incomplètes, réessayez. » ; option `verifyConsistency` (défaut actif en `auto`, inactif en `manual` : Activités « Voir plus » non bloquant, choix documenté). `Sales.tsx` : même contrôle sur `queueComplete`.
- BUG-171 : `DashboardLayout.tsx` : réinitialisation des pages « Voir plus » quand le sondage détecte un id inconnu ou un total modifié hors action locale ; `next != null`.
- BUG-173 : `Sales.tsx` : sous-titres des modaux « Liste Complète » et « Total facturé » = « liste partielle » tant que la file n'est pas complète.
- BUG-174 : `Production.tsx` : `loadData()` retombe sur la boulangerie consultée (`viewNodeRef`).
- BUG-175 : `Treasury.tsx` : `extraReports` vidé au rechargement et au changement de boulangerie/jour, filtré par nœud.
- Fichiers : `frontend/src/hooks/useProgressiveList.ts`, `frontend/src/components/layout/DashboardLayout.tsx`, `frontend/src/pages/dashboard/{Sales,Production,Treasury}.tsx`. Aucun fichier backend. Étapes manuelles : fiches du registre.
- Contrôles : `npx tsc --noEmit` et `npm run build` verts (sorties lues en fin de session).

## BUG-161 (F1/F2 partiel) — rotation d'équipes de 24 h, volet frontend
- Statut : fiche BUG-161 inchangée ; sous-section « F1/F2 partiel — CORRIGÉ » ajoutée au registre (B3 à B6 et F3 restent à faire).
- Fichiers : `frontend/src/api/services.ts`, `frontend/src/api/errors.ts`, `frontend/src/pages/dashboard/Nodes.tsx`, `frontend/src/pages/dashboard/Sales.tsx`, `frontend/src/components/layout/DashboardLayout.tsx`, nouveaux `frontend/src/components/production/TeamAssignmentModal.tsx` et `frontend/src/store/teamAssignmentStore.ts`. Aucun fichier backend.
- Points clés : heure de relève + interrupteur de rotation dans Boulangeries ; boîte de désignation non fermable montée une fois dans le layout, sondée dans le cycle de 10 s existant ; indicateur « Équipe de service : X (changer) » dans la barre latérale ; 403 `TEAM_NOT_ASSIGNED` géré dans `Sales.tsx`. Priorité : désignation avant les autres boîtes forcées. Étapes manuelles : fiche du registre.
- Contrôles : `npx tsc --noEmit` et `npm run build` (résultats en fin de session, voir rapport de retour).

## BUG-177 (volet frontend) — colonnes Non Servi / Régularisation, facturation NS/RG
- Fichiers : `frontend/src/api/services.ts`, `frontend/src/pages/dashboard/ClotureJournaliere.tsx`, `frontend/src/utils/clotureReportExport.ts`, `frontend/src/pages/dashboard/Sales.tsx`, `frontend/src/pages/dashboard/Clients.tsx`. Aucun backend.
- Clôture : Non Servi en montant FC (qté en dessous, « retranché : −X FC »), info-bulles `title` + légende visible, export Excel (colonne finale `fc_signe`) et impression cohérents.
- Facturation : choix « garde la dette » / « payé comptant » pour NS, versement masqué pour NS/RG, NS non livrable dans la file (badge « NON SERVIE — ENREGISTRÉE »), fiche client « NS — Non servie ». Validation « au moins une catégorie » conservée (backend l'exige).
- Étapes manuelles : fiche BUG-177 du registre. Ticket passé à CORRIGÉ.

## BUG-184 — Reçu : équipe de la facture (CORRIGÉ)
- Cause : `ReceiptData.team` lu depuis `user.team` dans `Sales.tsx` (livraison, remboursement) et `Clients.tsx` (vente, remboursement).
- Correction : `inv.team` partout ; repli sur l'équipe de l'utilisateur uniquement pour une facture tout juste créée (remboursements, vente de la fiche client) ; aucun repli à la livraison (`inv.team || '—'`). `Dashboard.tsx` (ré-impression) utilisait déjà `inv.team`. Aucune page n'envoie `team` à la création : le serveur décide.
- Fichiers : `frontend/src/pages/dashboard/Sales.tsx`, `frontend/src/pages/dashboard/Clients.tsx`. `npx tsc --noEmit` verte ; `npm run build` laissé au coordinateur.
- Étapes manuelles : fiche BUG-184 du registre (rotation active, B désignée, facturier A : le reçu affiche B).

## BUG-188 — La désignation d'équipe ne démonte plus les boîtes forcées (CORRIGÉ)
- Cause : `!teamAssignmentRequired` dans `DashboardLayout.tsx` démontait `CloseSessionModal` (BUG-156), `OpeningStockConfirmationModal` et `AutoClosedNoticeModal` : saisie locale perdue.
- Correction (piste a) : prop `suspended` de `Modal.tsx` (reste monté, `display: none`, `aria-hidden`, hors `openModalCount`, focus et Échap) relayée par les trois composants ; le layout les garde montées avec `suspended={teamAssignmentRequired}`. Désignation prioritaire et non fermable inchangée, mode correction et BUG-154 intacts, un seul `setInterval`, annonces BUG-157 inchangées.
- Sondage tardif : numérotation des requêtes `fetchTeamAssignment` (`teamReqSeqRef` / `teamAssignedSeqRef`) ; réponse plus ancienne que la dernière désignation réussie ignorée.
- Fichiers : `Modal.tsx`, `DashboardLayout.tsx`, `CloseSessionModal.tsx`, `OpeningStockConfirmationModal.tsx`, `AutoClosedNoticeModal.tsx`. `npx tsc --noEmit` : voir résultat ci-dessous ; build laissé au coordinateur.
- Étapes manuelles : fiche BUG-188 du registre.
