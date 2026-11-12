# Rapport testeur-production — 2026-11-11

## Vérification BUG-163 (lot 1) et BUG-170 — relecture de code + TypeScript

Méthode : relecture critique (hook, Activities, DashboardLayout, Users, Dashboard via `git diff`, Production), `npx tsc --noEmit` (propre à l'exécution), `npm run build`. Aucun backend modifié par ces tickets (`git status` : seuls des changements `core` antérieurs/étrangers). Pas de Playwright (base réelle).

Build : `tsc` du `npm run build` échoue uniquement sur `Treasury.tsx` (modification BUG-164 en cours par un autre agent : `setReports` inconnu, variables inutilisées). Aucune erreur dans le périmètre BUG-163/170 ; `vite build` non atteint, à relancer quand BUG-164 sera stabilisé.

### 1. Hook `useProgressiveList`
- Annulation : `requestIdRef` incrémenté au changement de `resetKey`/`enabled`/`mode`/`reload` et dans le cleanup (démontage) ; toutes les réponses testent `reqId`. OK.
- StrictMode : l'effet double-invoqué lance 2 requêtes page 1 en dev, la première est ignorée (cleanup) ; dédoublonnage par `id` en plus. Pas de duplication, pas de boucle de rendu (options lues via ref).
- Erreur d'une page intermédiaire : `error` renseigné, `hasMore` conservé, `loadMore`/`loadAll` permettent de reprendre ; `isComplete` faux tant qu'il y a une erreur. OK.
- `total` = `count` serveur dès la page 1 ; `isComplete` = plus de `next`, sans erreur. `loadAll` ne piétine pas une boucle active (force `forceAllRef`). OK.

### 2. Activities
Mode manuel 50/page, ajout à la suite (position conservée), bouton masqué quand `hasMore` faux, compteur `loaded / count`, ordre serveur (`-created_at`) conservé, « Actualiser » = page 1. Conforme à remarque.md l.422. OK.

### 3. Notifications (`DashboardLayout.tsx`)
Sondage = page 1 seule, pages suivantes dans `olderNotifications` non écrasé ; lu/tout lire/supprimer mettent à jour les deux ; compteur non lues = page 1 (comme avant) ; logique BUG-156/157/166 non touchée (diff). Défaut mineur : BUG-171 (trou possible après insertion d'une nouvelle notification, `next !== null`).

### 4. Users
`coreApi.users.list()` suit toutes les pages ; erreur affichée ; plus d'`apiClient` ni de `any`. OK.

### 5. Dashboard
- Plus d'appel complet à l'ouverture (compteur `page_size=1`, listes paginées).
- Graphique : masqué (« Calcul en cours… ») tant que < 7 jours distincts lus ; les 6 jours les plus récents sont alors complets (tri serveur `-invoice_date,-created_at`, `invoice_date` non nul par défaut), identique à l'ancien `.sort().slice(-6)`.
- KPI risques = `count` serveur ; ventilation par boulangerie et fiches clients n'apparaissent qu'à complétion (`isComplete`). Historique : bandeau d'avertissement pendant le chargement. Aucun total partiel présenté comme final.
- Écart de tri des alertes (nom au lieu de boulangerie/nom) : acceptable, documenté ; `activeClients` sans repli (`?? 0`) : sans conséquence.

### 6. BUG-170
Conforme (voir registre). Aucun minuteur, effacement correct, bouton désactivé + garde, erreurs inchangées.

### 7. Typage
Aucun `any` ajouté dans `git diff` (Activities, Dashboard, Users, DashboardLayout, services.ts, hook) ; appels HTTP via `services.ts`.

### Décisions
- BUG-163 : VÉRIFIÉ (contrôle manuel navigateur recommandé : scénarios du ticket).
- BUG-170 : VÉRIFIÉ (idem).
- BUG-171 : nouveau, Mineur, OUVERT.

## Vérification BUG-164 — volets Production et Sales (relecture de code + `tsc`)

Méthode : `git diff` de `Production.tsx`, `Sales.tsx`, `services.ts` ; relecture des viewsets (`BreadTransferViewSet`, `BreadDisposalViewSet`, `ProductionSessionViewSet`, `InvoiceViewSet`) ; `npx tsc --noEmit` : 0 erreur. Pas de test navigateur, pas de `npm run build`.

### Production
- Fournées : `sessions.page(page_size=15)`, tri serveur `-date` = ancien `slice(0,15)` ; historique avec sélecteur de jour et « Stock Pains du Jour » (BUG-144/145) viennent de `historySessions`/`selectedDate`, non touchés ; `flourHistory` inchangé.
- `todayDispoQty` : `ordering = ['-created_at']`, les sorties du jour sont un préfixe ; arrêt correct ; aucune sortie = 0 ; 20 exactement = une page ; > 20 = pages suivantes ; jour UTC identique à l'avant ; échec d'une page = échec de tout `loadData` (pas de KPI partiel). Réserve : insert concurrent pendant la lecture = ligne lue deux fois (pas de dédoublonnage par `id`), surévaluation négligeable.
- Transferts : actifs lus en entier (filtre `transfer_status` ; périmètre serveur boulangerie = from OU to, direction = tout) : compteurs « à traiter » identiques, aucun actif perdu, litiges intacts (§5.4 non dégradée) ; CONFIRMED limités à 3 (comme l'UI), fusion from/to dédoublonnée OK ; CANCELLED non affiché ailleurs. Défaut : BUG-174.
- BUG-151, 156/157/166, 170, désignation d'ouverture : code non touché. `loadSeqRef` : réponses obsolètes ignorées, `isLoading` géré par la dernière requête.

### Sales
- Page 1 de 100 aussitôt, suite séquentielle annulable (`queueLoadSeqRef`), dédoublonnage `_apiId`, facture locale ni perdue ni doublée ; cartes, sous-titre « livrées » et pied du modal « Total » gatés par `queueComplete` ; livraison/reçu utilisables dès la page 1. Défaut : BUG-173. Réserves : `queueComplete` sans contrôle `loaded === total` (cf. BUG-172) ; annulation locale pendant le chargement pouvant être ré-ajoutée par une page antérieure (très étroit).

### Typage
Aucun nouveau `any` ; HTTP via `services.ts`.

### Décisions
- BUG-164 (volets Production/Sales) : conforme sous réserve de BUG-173 et BUG-174 (Mineurs, OUVERT) ; statut de la ligne du tableau non modifié (multi-pages). Contrôle manuel navigateur recommandé (scénarios du ticket).

## Vérification BUG-177 (rapport de Clôture Journalière) et BUG-161 B1/B2 (rotation d'équipes, volet production)

Méthode : scénario riche reconstruit par le testeur et recalculé à la main, relecture de code, `npx tsc --noEmit` (0 erreur), tests ciblés un à un. Aucun fichier applicatif modifié ; aucune commande sur `backend/db.sqlite3` (migrations rejouées sur base de test via `MigrationExecutor`).

### A. BUG-177, rapport de Clôture Journalière
- Fichier : `backend/production/tests/test_verif_bug177_rapport_testeur_production.py`. Le scénario combine ventes normales, soldées, NS PENDING + NS annulée, RG, ajustement négatif, appro reçu/effectué, dispositions, restes, carryover BUG-142 et reste négatif BUG-158. Tous les totaux concordent avec la formule du classeur (L21 = somme signée des rubriques, NS retranchée ; L132 = FACTURE/JR + L21) : mvm interne 9 850 / 5 200 FC, total du jour 37 050 FC, écart/facture 3 900 FC, pains facturés 77, NS 1 800 / 1 000 FC (`fc_signe` négatif), régularisation -600 / +2 500 FC.
- Non-régression verte : `test_daily_closure_report` (5), `test_daily_stock_snapshot` (13), `test_daily_opening_confirmation` (35), `test_bug142_fournee_carryover_accumulation` (13), `test_bug177_closure_ns_rg` (6), `test_bug158_auto_closure_negative_stock` (11).
- Défauts : **BUG-185** (RG cochée « soldée » comptée deux fois : 4 500 FC au lieu de 3 000 FC), **BUG-186** (répartition % par quantité = 95,96 % avec un stock de départ confirmé : le dénominateur inclut le carryover). Tests `@expectedFailure`.
- Frontend : colonne Non Servi, légende, info-bulles, export Excel (colonne finale index 28, aucun décalage), impression cohérents ; aucun nouveau `any`. Réserve : `todayIso()` en UTC (relève au chantier F3). Contrôle navigateur non exécuté.

### B. BUG-161 B1/B2 et F1/F2 (volet production)
- Backend : `test_bug161_b2_team_assignment` (18), `core test_bug161_workday` (23), `core test_bug149_reset_superuser` (11) verts ; 13 tests ajoutés (`backend/production/tests/test_verif_bug161_testeur_production.py`) : bornes de relève (11:59:59 / 12:00:00, minuit, relève 00:00 = date calendaire, relève 23:30, fin d'année), suggestion après jours sautés, POST à minuit pile / à la relève, payloads invalides, journalisation, application des migrations core 0017/0018 + production 0023 sur lignes existantes (rien de perdu, défauts 12:00 / rotation désactivée).
- Permissions et isolation par nœud : couverts par les tests du développeur (LIVREUR 403, anonyme 401, non-HQ cantonné à son nœud, HQ avec `node`), relus et jugés suffisants.
- Défauts : **BUG-187** (corps JSON non objet -> 500, `@expectedFailure`), **BUG-188** (frontend : boîte forcée BUG-156 démontée à la relève, saisie perdue).
- Frontend (relecture) : modale non fermable sans équipe, un seul sondage, re-sondage après relève, indicateur « (changer) », priorité sur les autres boîtes, `Nodes.tsx` (heure de relève + case rotation, A/B conservés avec note) conformes. Écriture réservée à la Direction garantie côté API seulement (pas de garde React dédiée).
- Caractérisation : déplacer l'heure de relève en cours de journée change la journée de travail (retour à la veille) ; à documenter.

### Décisions
- BUG-177 (volet rapport) : conforme, ligne du registre inchangée (autres volets vérifiés par d'autres testeurs) ; BUG-185 et BUG-186 ouverts, Mineurs.
- BUG-161 : ligne laissée ouverte ; B1/B2/F1/F2 conformes sous réserve de BUG-187 et BUG-188.
- Pas de `VÉRIFIÉ` prononcé : la suite complète et les contrôles navigateur restent à la charge du coordinateur.
