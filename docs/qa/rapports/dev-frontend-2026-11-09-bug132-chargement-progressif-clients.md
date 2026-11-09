# Rapport dev-frontend — 2026-11-09 — BUG-132 (chargement progressif de la liste Clients)

## Ticket traité

**BUG-132** — « Gestion de la Clientèle » (`frontend/src/pages/dashboard/Clients.tsx`) se chargeait
très lentement pour un rôle Siège (ADMIN/DIRECTION/COMPTABLE, `can_access_all_nodes=true`, 685+
clients des 8 boulangeries), car `Clients.tsx::loadClients()` attendait que
`frontend/src/api/services.ts::getList()` ait suivi `next` jusqu'au bout (toutes les pages DRF)
avant de résoudre. Un GERANT (une seule boulangerie) ne voyait pas le problème.

Demande remontée directement par le coordinateur (pas encore dans `remarque.md`). Ticket ouvert et
enregistré dans `docs/qa/REGISTRE_BUGS.md` sous l'identifiant **BUG-132**, statut final `CORRIGÉ`
(non `VÉRIFIÉ` — CLAUDE.md §7 règle 3, dev-frontend ne valide pas sa propre correction).

## Scope respecté

- Aucune modification de `services.ts::getList()` elle-même (utilitaire partagé par tout le reste
  de `services.ts` — Treasury/Production/Sales/etc.). J'ai ajouté une fonction interne séparée
  `getPage<T>()` + `clientsApi.listPage(params)` qui renvoie UNE page DRF brute
  (`{count, next, previous, results}`, type exporté `PaginatedResponse<T>`), sans toucher à `getList`
  ni à son comportement pour les autres appelants.
- Tous les appels HTTP restent dans `src/api/services.ts` (aucun axios direct dans la page), comme
  l'exige CLAUDE.md §4.

## Cause confirmée

`backend/kiese/settings.py` : pagination par défaut DRF du projet —
`DEFAULT_PAGINATION_CLASS = PageNumberPagination`, `PAGE_SIZE = 25`,
`PAGE_SIZE_QUERY_PARAM = 'page_size'`, `MAX_PAGE_SIZE = 500`. `ClientViewSet`
(`backend/clients/views.py`) n'a pas de pagination_class personnalisée, donc hérite de ce contrat
standard. `getList()` (commentaire déjà présent dans le fichier, lié à BUG-061) suit systématiquement
`next` jusqu'à épuisement — un choix volontaire à l'époque pour éviter de perdre silencieusement les
clients au-delà de la page 1, mais qui bloque tout premier rendu tant que l'intégralité des pages
n'est pas revenue.

## Correction

### `frontend/src/api/services.ts`
- Ajout de `interface PaginatedResponse<T>` et de la fonction interne `getPage<T>(url, params)`
  (GET direct, aucune agrégation de pages).
- Ajout de `clientsApi.listPage(params)` qui l'utilise sur `/api/clients/clients/`.
- `getList` et `clientsApi.list` restent identiques — aucun autre appelant de `services.ts` n'est
  affecté.

### `frontend/src/pages/dashboard/Clients.tsx`
- `loadClients()` réécrit :
  1. Appelle `clientsApi.listPage({ page: '1', page_size: '50', ...node/search })` en parallèle de
     `coreApi.breadPrices.list()` / `coreApi.config.get()`.
  2. Dès que la page 1 revient : `setClients(firstResults)` puis `setIsLoading(false)` — la table
     s'affiche immédiatement (≈50 fiches), sans attendre le reste.
  3. Une boucle `while (next)` démarre ensuite (après le premier rendu, sans bloquer l'UI) et
     accumule chaque page suivante dans `clients` (`setClients(prev => [...prev, ...mapped])`).
  4. La garde de fraîcheur existante (`loadClientsRequestIdRef`, déjà en place pour BUG-103) est
     vérifiée à chaque itération de la boucle : un changement de filtre/recherche pendant le
     chargement arrière-plan interrompt proprement la boucle en cours au lieu de continuer à
     alimenter un état obsolète.
- Nouveaux états : `clientsTotalCount` (total serveur), `clientsLoadedCount`, `clientsBackgroundLoading`.
- Indicateur discret ajouté au-dessus du tableau : spinner + « Chargement du reste de la liste… X / Y
  clients chargés. », avec un avertissement supplémentaire si un filtre Type/Risque (appliqué en
  mémoire, non côté API) est actif pendant ce chargement — ces filtres peuvent être incomplets tant
  que toutes les pages ne sont pas arrivées. Message « Liste complète chargée (Y client(s)). » une
  fois le chargement terminé.
- Message « Aucun client ne correspond » complété d'un avertissement « peut être incomplet » quand
  un filtre Type/Risque est actif et que le chargement arrière-plan est toujours en cours — pour
  éviter le faux-négatif « ce client n'existe pas » signalé comme un risque par le coordinateur.
- Bouton « Voir plus » existant (révélation 20 par 20, déjà présent avant ce ticket) conservé et
  étendu :
  - reste affiché tant qu'il reste des clients déjà chargés à révéler **ou** que le chargement
    arrière-plan n'est pas terminé ;
  - dans ce second cas (rien de neuf à révéler immédiatement), il est désactivé et affiche
    « En attente de la page suivante… » plutôt que de disparaître silencieusement.

### Choix de conception — bouton « Voir plus » vs affichage 100 % automatique

Le chargement arrière-plan est **entièrement automatique** (il tourne sans jamais attendre de clic).
J'ai choisi de garder le bouton « Voir plus » déjà existant dans le fichier (révélation de la liste
déjà en mémoire par paliers de 20) plutôt que d'ajouter un second mécanisme ou de tout révéler d'un
coup : la page affichait déjà ce pattern avant ce ticket (pour la pagination en mémoire), et il reste
cohérent/prévisible pour l'utilisateur à l'échelle de 685+ fiches (éviter un tableau de 685 lignes qui
grossit tout seul sans contrôle). Le clic ne déclenche jamais de requête HTTP : il augmente juste
`clientsVisibleCount`, donc si une page vient juste d'arriver en arrière-plan, la révélation est
immédiate ; sinon, le bouton se désactive avec le libellé « En attente de la page suivante… », le
chargement arrière-plan continuant de son côté — le bouton redevient actif dès qu'il y a quelque chose
de nouveau à montrer.

### Recherche / filtres — impact vérifié

- La recherche par nom/code (`debouncedSearchTerm` → paramètre `search`) est envoyée au serveur
  (déjà en place avant ce ticket, BUG-061/BUG-103) : chaque page interrogée, y compris la page 1,
  correspond déjà au terme recherché côté serveur. Un résultat de recherche à 0 ligne reste donc
  fiable même pendant le chargement arrière-plan — aucun faux-négatif possible pour ce cas.
- Les filtres Type et Risque restent appliqués en mémoire (non filtrables côté API aujourd'hui,
  comme avant ce ticket) : ils ne portent donc que sur ce qui est déjà chargé. L'avertissement décrit
  plus haut couvre ce cas plutôt que d'ouvrir un chantier backend (ajout de `client_type`/catégorie de
  risque aux `filterset_fields` de `ClientViewSet`) non demandé par ce ticket — à ouvrir séparément
  pour `dev-backend` si le client le souhaite.

## Vérifications effectuées

- `npx tsc --noEmit` : aucune erreur, aucun nouveau `any`.
- `npm run build` : succès. Avertissements préexistants uniquement (taille du chunk
  `index-legacy` > 500 kB, minificateur `oxc` non supporté pour les chunks legacy) — aucun nouvel
  avertissement introduit par cette correction.
- `cd e2e && npx playwright test tests/03-clients.spec.ts` : **12/12 tests passés** (4 largeurs —
  pos/tablette/bureau/tv — × 3 scénarios), en 4.3 min, backend+frontend de développement déjà en
  cours d'exécution. Le 3ᵉ scénario (« un facturier de K2 retrouve un client rattaché à K1 »)
  attend déjà `/\d+ fiches/` ≠ `0 fiches` avant de chercher ; ce texte (`{clients.length} fiches`)
  apparaît maintenant dès la page 1 au lieu d'attendre l'intégralité du chargement : le test reste
  vert et devient simplement plus représentatif du nouveau comportement (son `test.slow()`/timeout
  60 s, commenté BUG-061, reste une marge de sécurité sans être nécessaire).

## Vérification manuelle suggérée pour le testeur (en complément du test E2E ci-dessus)

1. Se connecter avec un compte Siège (ADMIN/DIRECTION/COMPTABLE) ayant 685+ clients visibles, ouvrir
   `/clients` : la table affiche les 50 premières fiches quasi immédiatement.
2. Observer le bandeau « Chargement du reste de la liste… X / Y clients chargés. » pendant quelques
   secondes, puis le message final « Liste complète chargée (Y client(s)). ».
3. Cliquer « Voir plus » plusieurs fois : la liste visible grossit par paliers de 20 ; si on clique
   plus vite que l'arrivée des pages, le bouton affiche « En attente de la page suivante… » (désactivé)
   puis redevient cliquable sans action supplémentaire.
4. Taper une recherche par nom/code pendant le chargement arrière-plan : résultat fiable (recherche
   serveur).
5. Filtrer par Type ou Risque pendant le chargement arrière-plan, avec 0 résultat : vérifier que
   l'avertissement « peut être incomplet » s'affiche.
6. Se connecter avec un GERANT (une boulangerie) : comportement inchangé, pas de bandeau arrière-plan
   visible (une seule page suffit généralement).

## Fichiers modifiés

- `frontend/src/api/services.ts`
- `frontend/src/pages/dashboard/Clients.tsx`
- `docs/qa/REGISTRE_BUGS.md` (ouverture + correction de BUG-132)

## Statut du ticket

BUG-132 passé à **CORRIGÉ** dans `docs/qa/REGISTRE_BUGS.md`. Non passé à `VÉRIFIÉ` (réservé au
testeur d'origine ou au coordinateur, CLAUDE.md §7 règle 3).

## Suggestion pour la suite (hors périmètre de ce ticket)

Si le client souhaite un jour filtrer Type/Risque de façon fiable à l'échelle du groupe sans dépendre
du chargement arrière-plan, il faudrait ajouter `client_type` et un filtre de catégorie de risque
côté serveur (`ClientViewSet.filterset_fields`) — à ouvrir comme ticket séparé pour `dev-backend` si
souhaité ; je ne l'ai pas fait ici car hors périmètre explicite de BUG-132 (« ne touche pas au
backend »).
