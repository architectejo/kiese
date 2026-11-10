# Rapport dev-frontend — 2026-11-10 — BUG-145 (sélecteur de date — Production & Stocks)

## Contexte

Demande client (remarque.md, ligne ajoutée après l.396) : pouvoir sélectionner un jour dans
« Production & Stocks » pour les sections « Stock Pains Actuel » (renommée « Stock Pains du
Jour ») et « Historique des Fournées ».

Le volet backend (**BUG-144**) a été traité par `dev-backend` — contrat API détaillé dans
`docs/qa/rapports/dev-backend-2026-11-10-bug144-stock-pains-par-jour.md`, relu intégralement
avant de commencer ce ticket. Ce rapport couvre uniquement le volet frontend (**BUG-145**).

## Analyse

- `Production.tsx` (1604 lignes avant modification) chargeait `breadStocks` (solde courant,
  `BreadStock[]`, détail complet produit/reçu/sorti/disposé) et `sessions` (15 dernières fournées
  toutes dates confondues) une seule fois par rafraîchissement/changement de boulangerie, sans
  aucune notion de date sélectionnable.
- `sessions` est aussi utilisé ailleurs, sans rapport avec « Historique des Fournées » :
  - les deux cartes KPI du haut (« Fournées enregistrées », valeur FC produite) ;
  - le menu déroulant « Session de Production » du formulaire « Sortie Non Standard » (onglet
    Réconciliation), filtré côté client à la date du jour réel (`s.date === aujourd'hui`),
    indépendamment de tout sélecteur.
  Mélanger un filtrage par date arbitraire dans ce `sessions` partagé aurait changé le sens de ces
  deux fonctionnalités sans que la demande client ne le couvre.
- `CalendarPicker.tsx` (`frontend/src/components/shared/CalendarPicker.tsx`, ajouté sous BUG-128
  pour « Clôture Journalière ») est déjà le composant standard pour ce besoin : calendrier mensuel
  léger, sans dépendance, jours futurs désactivés, utilisé dans une `Modal.tsx` — relu son usage
  dans `ClotureJournaliere.tsx` avant intégration ici, réemployé à l'identique (même convention
  visuelle, même `Modal`).

## Décision d'architecture

- Nouveau composant `frontend/src/components/production/StockDuJourSection.tsx` (CLAUDE.md §4 :
  extraction obligatoire des sous-composants ajoutés à une page de plus de ~1000 lignes), qui
  encapsule :
  - le titre renommé « Stock Pains du Jour » avec la date affichée en toutes lettres ;
  - le bouton + `Modal`/`CalendarPicker` de sélection de date ;
  - le rendu de la liste des pains, avec deux branches :
    - **date = aujourd'hui** (`isToday`) : réutilise directement `liveBreadStocks` (prop, la même
      liste `BreadStock[]` déjà chargée par `Production.tsx` via `productionApi.breadStocks.list()`
      — **aucun appel réseau supplémentaire**, et le clic « voir détail » existant (modale avec le
      détail produit/reçu/sorti/disposé) continue de fonctionner à l'identique) ;
    - **date passée** : appelle le nouvel endpoint `productionApi.breadStocks.byDate({node, date})`
      et affiche les catégories renvoyées (plus pauvres : seulement `qty_available`/`unit_price`,
      pas de détail par type de mouvement — le contrat API ne le permet pas pour un snapshot
      reconstitué, voir le rapport dev-backend), avec un badge discret « Historique (reconstitué) »
      quand `source === "snapshot"`, et des états de chargement/erreur (`detail` affiché)/liste vide
      dédiés.
- Dans `Production.tsx` :
  - un seul état `selectedDate` (défaut aujourd'hui) pilote À LA FOIS `StockDuJourSection` et
    « Historique des Fournées » (un seul sélecteur, pas deux, conformément à la demande explicite) ;
  - un état séparé `historySessions`/`historyLoading`/`historyError`, alimenté par un `useEffect`
    dédié appelant `productionApi.sessions.list({ node, date: selectedDate })` à chaque changement
    de boulangerie ou de date — **volontairement indépendant** du `sessions` d'origine (raison :
    voir Analyse ci-dessus) ;
  - « Historique des Fournées » (aperçu des 2 dernières fournées + bouton « Voir plus » + boîte
    modale complète + modale de détail d'une fournée avec commentaire/clôture) utilise désormais
    exclusivement `historySessions` (y compris les deux endroits qui écrivaient auparavant dans
    `sessions` après modification d'une note ou une clôture — remplacés par `setHistorySessions`).

## Fichiers modifiés/créés

- `frontend/src/api/services.ts` :
  - nouveaux types `BreadStockByDateCategory` et `BreadStockByDate` (forme de la réponse
    `GET /api/production/bread-stocks/by-date/`, documentée dans le rapport dev-backend) ;
  - `productionApi.breadStocks.byDate(params?: { node?: string; date?: string })` — même
    convention de nommage que `productionApi.breadStocks.list()` déjà existant. Aucun nouvel `any`,
    aucun appel axios hors `services.ts`.
- `frontend/src/components/production/StockDuJourSection.tsx` (nouveau) — voir Décision
  d'architecture.
- `frontend/src/pages/dashboard/Production.tsx` :
  - import de `StockDuJourSection` ; ajout de `todayIso()` (helper local, même convention que
    `ReconciliationPanel.tsx`/`ClotureJournaliere.tsx`) ;
  - nouveaux états `selectedDate`, `historySessions`, `historyLoading`, `historyError` ;
  - nouveau `useEffect` de chargement de `historySessions` (dépend de `viewNode`, `user?.node`,
    `selectedDate`) ;
  - remplacement du bloc JSX « Stock Pains Actuel » par `<StockDuJourSection ... />` ;
  - bloc « Historique des Fournées » (aperçu + bouton « Voir plus » + boîte modale complète)
    basculé de `sessions` vers `historySessions`, avec affichage du chargement/de l'erreur ;
  - les deux mises à jour locales après modification de note / clôture d'une fournée
    (`setSessions(prev => ...)`) remplacées par `setHistorySessions(prev => ...)`.
- `docs/qa/REGISTRE_BUGS.md` : ticket **BUG-145** ajouté (ligne de tableau + section détaillée),
  passé à **CORRIGÉ** (pas `VÉRIFIÉ`, conformément à CLAUDE.md §7 règle 3 — seul le testeur
  d'origine ou le coordinateur peut valider).

## Non-régression

- Quand `selectedDate` = aujourd'hui (valeur par défaut au premier rendu) : la section « Stock
  Pains du Jour » affiche exactement la même liste, avec le même clic « voir détail » (détail
  produit/reçu/sorti/disposé), qu'avant ce ticket — aucune requête réseau additionnelle n'est
  déclenchée dans ce cas, le composant réutilise la liste déjà chargée par `Production.tsx`.
- Les cartes KPI (« Fournées enregistrées », valeur FC) et le formulaire « Sortie Non Standard »
  (menu déroulant filtré à la date du jour réel) ne sont pas affectés par le sélecteur de date —
  ils continuent d'utiliser `sessions`, intact.

## Vérifications

- `cd frontend && npx tsc --noEmit` → aucune erreur.
- `cd frontend && npm run build` → build réussi (avertissements pré-existants sans rapport avec ce
  ticket : taille du bundle legacy, minifieur `oxc` non supporté pour les chunks legacy).
- `e2e/tests/05-production.spec.ts` relu : aucune chaîne (« Stock Pains Actuel »,
  « Historique des Fournées », sélecteurs DOM) affectée par ce ticket.
- **Tentative d'exécution de la suite E2E bloquée par un problème d'environnement, indépendant de
  ce ticket** : l'utilisateur de démonstration `demo_gerant_k1_e2e` attendu par
  `e2e/fixtures/helpers.ts` n'existe pas dans la base partagée de cette session
  (vérifié via `User.objects.filter(username__icontains='demo_gerant_k1_e2e').exists()` → `False`),
  et les identifiants `@gerant-k1` / `Kiese2026!` du script `seed_kiese.py` sont refusés par
  l'API (« Identifiants invalides »), probablement changés par une autre session en cours sur la
  même base partagée. **Signalé pour le coordinateur** — pas un problème de code frontend.

## Vérification manuelle recommandée pour le testeur (en l'absence d'E2E exécutable ici)

1. Se connecter en GÉRANT (ou DIRECTION), aller sur « Production & Stocks », onglet « Fournées ».
2. Vérifier le titre « Stock Pains du Jour — &lt;date du jour en toutes lettres&gt; » au-dessus de
   la liste des pains, avec un bouton « Choisir un jour » (icône calendrier).
3. Cliquer sur « Choisir un jour » → boîte modale avec calendrier mensuel ; jours futurs
   grisés/non cliquables ; modale visible sans défilement de page (même composant que la boîte
   modale de Clôture Journalière, BUG-128).
4. Sélectionner un jour passé ayant eu de la production → la liste change (quantités disponibles
   ce jour-là) ; badge « Historique (reconstitué) » si la source est un snapshot ; « Historique des
   Fournées » juste en dessous se met AUSSI à jour pour ne montrer que les fournées de ce jour-là
   (même date, un seul sélecteur pour les deux sections).
5. Sélectionner un jour sans aucune fournée → « Aucune fournée ce jour-là » et (si aucun stock
   snapshot) « Aucun stock de pains enregistré ce jour-là », sans erreur ni page blanche.
6. Revenir à aujourd'hui → le clic sur une ligne de pain rouvre le détail complet comme avant ce
   ticket (non-régression) ; les cartes KPI et le formulaire « Sortie Non Standard » restent
   inchangés.
7. Vérifier l'affichage à 360 px (POS) et 768 px (tablette) : bouton + titre restent lisibles sans
   chevauchement.

## Risques / points en attente

- Signalé par `dev-backend` (non bloquant) : si un jour donné n'a de ligne
  `DailyBreadStockSnapshot` que pour UNE des deux équipes, l'endpoint `by-date` renvoie quand même
  une valeur « complète » en apparence (0 pour l'équipe absente). Le badge « Historique
  (reconstitué) » prévient déjà l'utilisateur que ce n'est pas un solde en temps réel ; pas de
  distinction plus fine implémentée côté frontend, faute de champ dédié dans le contrat API
  actuel (non demandé explicitement par le client).
- Blocage E2E signalé au coordinateur (utilisateur de démonstration manquant / identifiants de
  seed refusés sur la base partagée) — à traiter séparément, hors scope de ce ticket.

## Statut du ticket

BUG-145 passé à **CORRIGÉ** dans `docs/qa/REGISTRE_BUGS.md` (pas `VÉRIFIÉ` — CLAUDE.md §7 règle 3,
seul le testeur d'origine ou le coordinateur peut valider).
