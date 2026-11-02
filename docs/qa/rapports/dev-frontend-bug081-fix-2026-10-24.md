# Rapport dev-frontend — BUG-081 (page blanche desktop) — 2026-10-24

## Résumé
BUG-081 (Bloquant) corrigé : la fenêtre Electron affichait une page blanche au premier lancement et
à chaque réouverture. Deux causes distinctes, toutes deux dans `frontend/`, corrigées :

1. `frontend/vite.config.ts` n'avait pas de `base` → Vite générait des chemins d'assets absolus
   (`/assets/...`), qui se résolvent à la racine du disque sous `file://` et non au dossier contenant
   `index.html`.
2. Même une fois les chemins corrigés, le bundle Vite par défaut utilise des
   `<script type="module">`, que Chromium (donc Electron) **refuse toujours de charger depuis une
   page `file://`** : l'origine d'un document `file://` est opaque (« null »), et les requêtes de
   modules sont toujours soumises à une vérification CORS qu'une origine opaque ne peut jamais
   satisfaire — indépendamment des chemins ou de l'attribut `crossorigin`. C'est la cause de la page
   blanche qui persistait encore après le premier correctif ; je ne l'ai découverte qu'en reproduisant
   le chargement en `file://` dans un Chromium headless (preuve indirecte, documentée ci-dessous).

J'ai aussi profité de la correction pour traiter un problème de navigation lié : `BrowserRouter`
utilise `history.pushState`, qui lève une `SecurityError` sous `file://` dès la première navigation
React Router vers un autre écran — corrigé en basculant dynamiquement sur `HashRouter` uniquement
quand l'app tourne sous `file://` (le site web cloud garde `BrowserRouter`/URLs propres).

**Découverte annexe, hors périmètre frontend, ticket ouvert séparément (BUG-082, Bloquant,
`dev-backend`)** : `CORS_ALLOWED_ORIGINS` (backend) ne couvre ni l'origine `null` (`file://`) ni
`http://127.0.0.1:<port-dynamique>` (port choisi par `desktop/src/port.ts::findFreePort()`). Une fois
BUG-081 corrigé, les appels `axios` du frontend desktop vers son propre backend local risquent
d'échouer par CORS. Je n'ai pas touché au backend (interdit) ; voir la fiche BUG-082 pour les pistes
suggérées à dev-backend.

## Fichiers modifiés
- `D:\Projects\kiesse\frontend\vite.config.ts`
  - `base: './'` (chemins relatifs).
  - Plugin `@vitejs/plugin-legacy({ renderModernChunks: false, modernPolyfills: false, targets: [...] })`
    pour forcer un bundle unique en script classique (pas de `type="module"`), seul format exécutable
    sous `file://`. Cibles volontairement récentes (Chrome/Edge/Firefox ≥ 109, Safari ≥ 15) pour limiter
    le poids des polyfills (le besoin n'est pas de supporter de vieux navigateurs, seulement d'éviter la
    balise `type="module"`).
  - Petit plugin local `stripCrossoriginForElectron` (`transformIndexHtml`, `enforce: 'post'`) qui
    retire l'attribut `crossorigin` des balises générées, inutile en local et source d'un échec CORS
    supplémentaire (feuille de style) observé pendant la reproduction.
- `D:\Projects\kiesse\frontend\package.json` : ajout de `@vitejs/plugin-legacy` et `terser`
  (devDependencies).
- `D:\Projects\kiesse\frontend\src\App.tsx` : `Router` choisi dynamiquement
  (`window.location.protocol === 'file:' ? HashRouter : BrowserRouter`), import de `HashRouter` ajouté.
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` : BUG-081 passé à `CORRIGÉ` avec fiche détaillée
  (cause, preuves, fichiers modifiés, étapes de vérification manuelle) ; ouverture de BUG-082
  (`OUVERT`, backend, lié) pour le problème CORS connexe découvert pendant la correction.

## Preuves (reproduction indirecte — pas de session Windows interactive disponible)
1. Build avec la config d'origine : `dist/index.html` contenait
   `<script type="module" crossorigin src="/assets/index-XXXX.js">` (chemin absolu) — confirme
   l'hypothèse initiale du coordinateur.
2. Script Node + Playwright (Chromium headless, même famille de moteur qu'Electron) ouvrant
   `dist/index.html` directement en `file:///D:/Projects/kiesse/frontend/dist/index.html` :
   - Avant toute correction : `document.getElementById('root').innerHTML.length === 0`.
   - Après `base: './'` seul (chemin relatif correct, toujours `type="module"`) : toujours `0`, avec
     une erreur console explicite :
     `Access to script at 'file:///.../assets/index-XXXX.js' from origin 'null' has been blocked by
     CORS policy: Cross origin requests are only supported for protocol schemes: chrome,
     chrome-untrusted, data, http, https.`
   - Après ajout de `@vitejs/plugin-legacy` (`renderModernChunks: false`) : `innerHTML.length === 13537`,
     avec le texte réel de la Vitrine (« ETS. KIESE », « BOULANGERIES CONNECTÉES », « Grille de Prix »…)
     — la page s'affiche correctement, plus de page blanche.
   - Les seules erreurs console restantes à ce stade concernent des appels `axios` vers
     `https://api.etskiese.com/...` (URL de production codée dans ce build de test, sans backend local
     démarré) — attendu, sans rapport avec BUG-081, et c'est précisément le symptôme documenté dans
     BUG-082 pour le cas réel (backend local desktop).

## Vérifications
- `cd frontend && npx tsc --noEmit` : passe sans erreur.
- `cd frontend && npm run build` : passe sans erreur (avertissement préexistant « chunk > 500 Ko »,
  sans rapport avec ce ticket).
- `cd frontend && npm run dev` : démarré en arrière-plan, répond `200` sur `http://localhost:5174/`
  (port 5173 déjà occupé par une autre instance de ce poste) — le mode développement web n'est pas
  affecté (`base`/plugin legacy n'agissent qu'au `build`).
- Déploiement cloud : `backend/kiese/urls.py` ne sert aucune route pour `frontend/dist/` (uniquement
  l'API REST et `MEDIA_URL`) — le frontend est donc servi par un serveur statique séparé, hors de ce
  dépôt. `base: './'` reste compatible avec un hébergement à la racine du domaine, et serait même plus
  robuste qu'un `base: '/'` figé si ce frontend était un jour servi depuis un sous-chemin.
- Pas de test E2E Playwright existant pour ce parcours. Étapes de vérification manuelle laissées dans
  la fiche BUG-081 pour testeur-installation/testeur-materiel (reconstruire le paquet desktop complet
  sur une machine Windows réelle, lancer/fermer/relancer plusieurs fois, naviguer dans le tableau de
  bord).

## Ce que je n'ai pas fait (hors permission / hors preuve possible)
- Je n'ai pas touché à `backend/` (interdit) : le problème CORS connexe (BUG-082) est documenté et
  assigné à `dev-backend`, pas corrigé par moi.
- Je n'ai pas pu lancer une vraie fenêtre Electron (pas de session Windows interactive dans cet
  environnement) ni reconstruire l'installeur complet (`electron-builder`) pour une vérification
  visuelle finale — la preuve apportée est indirecte (Chromium headless chargeant le même
  `dist/index.html` en `file://`), explicitement signalée comme telle dans la fiche. Le ticket n'est
  pas passé à `VÉRIFIÉ` (je n'ai pas cette autorité) : il attend confirmation par
  coordinateur/testeur-installation, et in fine par une réinstallation réelle côté client.

## Statut final des tickets
- BUG-081 : `CORRIGÉ` (dev-frontend). En attente de `VÉRIFIÉ` par coordinateur/testeur-installation.
- BUG-082 (nouveau) : `OUVERT`, assigné à `dev-backend`, lié à BUG-081.
