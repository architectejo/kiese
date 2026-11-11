
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
