# Rapport — dev-frontend, 2026-11-09 — BUG-134 : boîte modale « stock de départ »

## Mission

Sous-ticket frontend de BUG-133 (backend déjà livré et vérifié par ses propres tests : 22/22 sur
`test_daily_opening_confirmation.py`, 158/158 sur `production sales`). Demande client (remarque.md
l.396, reformulée) : à sa première connexion de la journée, le gérant doit voir une boîte modale
qui propose, par catégorie de pain, le stock de départ (`BreadStock.qty_available`). Il peut
modifier ou valider directement. Précision ajoutée en cours de route : la boîte modale doit
continuer d'apparaître à CHAQUE ouverture de page, tant que le gérant n'a pas confirmé — ce n'est
pas un prompt ponctuel au login.

## Ticket traité

- **BUG-134** : `OUVERT` → `CORRIGÉ` (le passage à `VÉRIFIÉ` revient au testeur-production ou au
  coordinateur, jamais à dev-frontend — CLAUDE.md §7 règle 3).

## Lecture préalable

- Fiche BUG-134 complète du registre (contrat d'API exact, exemples de réponse, contraintes
  ergonomiques).
- `docs/qa/rapports/dev-backend-2026-11-09-confirmation-reste-hier.md` (points de conception
  tranchés par dev-backend, notamment : équipe choisie explicitement, jamais déduite ; signe des
  quantités confirmées volontairement positif, différent de `DailyBreadStockSnapshot.
  reste_du_hier()` qui reste négatif).
- Code backend exact de `DailyOpeningConfirmationView` (`backend/production/views.py`) pour
  vérifier le contrat `GET`/`POST` au mot près avant d'écrire les types TypeScript.
- `frontend/src/components/layout/DashboardLayout.tsx`, `frontend/src/api/services.ts`,
  `frontend/src/components/shared/Modal.tsx`, `frontend/src/store/authStore.ts` (forme exacte de
  `UserProfile.role`/`can_access_all_nodes`), `frontend/src/api/errors.ts` (`getErrorDetail`,
  BUG-127).

## Analyse des rôles concernés (CLAUDE.md §5.1/§5.2)

Seul le rôle `GERANT` non-HQ (`!user.can_access_all_nodes`) a un stock de départ personnel à
confirmer — un rôle Siège (`ADMIN`/`DIRECTION`/`COMPTABLE`) supervise plusieurs boulangeries et
n'est jamais concerné par cette confirmation opérationnelle quotidienne d'UNE boulangerie
spécifique. Un `GERANT` avec `can_access_all_nodes=true` (HQ) n'a pas non plus de nœud personnel
unique à confirmer. Hypothèse confirmée par la mission et par le rapport backend (« Un rôle Siège
(HQ) n'a pas de stock de départ personnel à confirmer dans ce flux ») — pas d'ambiguïté réelle
trouvée, pas de doute à signaler sur ce point précis.

## Correctif

### Fichiers modifiés/ajoutés

1. `frontend/src/api/services.ts` :
   - Types `OpeningConfirmationTeam`, `OpeningConfirmationCategory`, `OpeningConfirmationTeamLine`,
     `OpeningConfirmationTeamState`, `OpeningConfirmationReport`, `OpeningConfirmationSubmitPayload`,
     `OpeningConfirmationSubmitResponse` — typage strict de la réponse exacte documentée dans
     BUG-134 (aucun `any`).
   - `productionApi.openingConfirmation.get()` / `.submit()` : seul point d'appel HTTP vers
     `GET`/`POST /api/production/opening-confirmation/` (CLAUDE.md §4 — jamais d'axios direct dans
     une page/un composant de layout).

2. `frontend/src/components/production/OpeningStockConfirmationModal.tsx` (nouveau) :
   - Reçoit une prop `routeKey` (alimentée par `location.pathname` du `DashboardLayout`) ; un
     `useEffect([routeKey])` réinterroge le `GET` au montage ET à chaque changement de route —
     répond directement à la précision client « réaffiché à chaque changement de page », pas
     seulement au login.
   - Affiche la boîte modale (réutilise `src/components/shared/Modal.tsx`, qui porte déjà le rendu
     en portail + la contrainte « visible sans défilement de page » signalée par le client ailleurs
     dans le registre) si `teams.A.confirmed` ou `teams.B.confirmed` est `false`.
   - Équipe choisie EXPLICITEMENT par deux boutons A/B (jamais déduite de l'heure — conforme au
     point de conception 1 de BUG-133/backend) ; présélection ergonomique de l'équipe restante si
     une seule n'est pas confirmée, reste modifiable ; bouton désactivé pour une équipe déjà
     confirmée aujourd'hui (affiche qui l'a confirmée).
   - Catégories affichées avec `qty_proposed` pré-rempli dans un champ `<input type="number">`
     modifiable (entier ≥ 0, repli silencieux à 0 sur saisie invalide/vide plutôt que de planter).
   - Bouton « Valider » → `POST`, puis relance immédiatement le `GET` : si l'équipe restante n'est
     toujours pas confirmée, la modale reste ouverte et se repositionne automatiquement sur cette
     équipe (répond à l'exigence « proposer immédiatement la confirmation pour cette équipe »).
   - Bouton « Plus tard » : fermeture mémorisée uniquement pour la route courante
     (`dismissedForRoute === routeKey`) — dès que `routeKey` change (nouvelle page), la modale
     réapparaît, jamais ignorée pour le reste de la session (CLAUDE.md §7 règle 6 — choix
     ergonomique assumé, pas un vrai dilemme métier à reposer au coordinateur).
   - Liste de catégories vide (nœud sans `BreadStock` récent) : message clair « Aucune catégorie de
     pain active... », pas d'erreur ni d'écran blanc.
   - États de chargement et d'erreur (`getErrorDetail`, BUG-127) gérés explicitement.
   - Affiche les quantités TELLES QUE SAISIES (positives, « nombre de pains restants ») — ne
     reproduit jamais la convention de signe négative de `DailyBreadStockSnapshot.reste_du_hier()`
     (BUG-118) : ce sont deux écrans différents à des fins différentes, comme demandé explicitement.
   - Responsive : liste de catégories dans un conteneur `maxHeight: 45vh; overflowY: auto`, champs
     numériques compacts — testé visuellement à 360 px (voir vérification manuelle ci-dessous).

3. `frontend/src/components/layout/DashboardLayout.tsx` :
   - Import + montage unique de `OpeningStockConfirmationModal`, gardé par
     `user.role === 'GERANT' && !user.can_access_all_nodes` (même idiome que `navItems`/`is_superuser`
     ailleurs dans ce fichier). Montée une seule fois dans le layout — pas page par page, consigne
     explicite du coordinateur/de la mission.

### Points de vigilance documentés (non tranchés, signalés dans la fiche BUG-134)

- `reste_du_hier` de `GET /api/production/daily-closure/` (BUG-120, écran « Clôture Journalière »)
  peut désormais afficher une valeur positive pour un jour/équipe confirmé via ce mécanisme, par
  construction différente en signe des jours non confirmés — comportement voulu, documenté côté
  backend et répété ici, pas un bug. Aucune correction de signe appliquée dans cette modale (le
  signe de BUG-118 appartient à un autre écran, à des fins différentes) — sujet laissé ouvert pour
  confirmation finale avec le client au moment de la recette, comme indiqué par dev-backend.

### Vérification technique

- `npx tsc --noEmit` : aucune erreur, aucun nouvel avertissement.
- `npm run build` : succès (`tsc && vite build`), seuls avertissements préexistants et sans rapport
  (taille des chunks legacy, minifier `oxc`).
- Aucun test E2E Playwright existant pour ce parcours (fonctionnalité neuve) — étapes de
  vérification manuelle détaillées dans la fiche BUG-134 du registre (10 étapes : apparition au
  login, correspondance avec `BreadStock.qty_available`, flux de validation séquentiel A puis B,
  fermeture après les deux équipes confirmées, réaffichage après navigation si non confirmé,
  réapparition après « Plus tard » sur une autre page, garde de rôle HQ, nœud sans catégorie,
  responsive 360 px, signe positif cohérent côté Clôture Journalière).

## Fichiers livrés

- `frontend/src/api/services.ts`
- `frontend/src/components/production/OpeningStockConfirmationModal.tsx`
- `frontend/src/components/layout/DashboardLayout.tsx`
- `docs/qa/REGISTRE_BUGS.md` (BUG-134 : tableau de suivi + fiche détaillée, section Correction)

## Suite

BUG-134 passé à `CORRIGÉ`. Reste à faire valider par un testeur (ou le coordinateur) avec le
backend réellement démarré (reproduction end-to-end), et à confirmer définitivement avec le client
le choix de signe documenté au point de vigilance ci-dessus — aucune ambiguïté bloquante trouvée
par ailleurs dans le périmètre de ce ticket.
