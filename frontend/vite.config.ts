import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import legacy from '@vitejs/plugin-legacy';
import path from 'path';

/**
 * Vite ajoute systématiquement `crossorigin` sur les balises
 * <script type="module"> et <link rel="stylesheet"/modulepreload"> du
 * index.html généré. Sous le protocole file:// (application Electron),
 * le navigateur traite alors ces requêtes comme des requêtes CORS avec
 * une origine "null", qui échouent toujours (ERR_FAILED), laissant la
 * page blanche même avec des chemins relatifs corrects. On retire cet
 * attribut après la génération du HTML : il n'a aucune utilité en
 * local (file:// ou chargement classique sans CDN tiers) et ne casse
 * rien pour le déploiement web (cloud) qui est servi en http/https.
 */
function stripCrossoriginForElectron(): Plugin {
  return {
    name: 'strip-crossorigin-for-electron',
    enforce: 'post',
    transformIndexHtml(html) {
      return html.replace(/\s+crossorigin(="[^"]*")?/g, '');
    },
  };
}

// https://vite.dev/config/
export default defineConfig({
  // Chemins relatifs : indispensable pour que l'application Electron
  // (chargement via file://) et tout hébergement dans un sous-dossier
  // puissent résoudre les assets générés (/assets/... casse sous file://).
  base: './',
  plugins: [
    react(),
    // BUG-081 : les navigateurs Chromium (donc Electron) refusent de
    // charger un <script type="module"> via le protocole file:// — la
    // requête est traitée comme une requête CORS depuis une origine
    // opaque ("null"), systématiquement bloquée (ERR_FAILED), quel que
    // soit le chemin (absolu ou relatif) ou la présence de
    // `crossorigin`. `renderModernChunks: false` fait produire par
    // Vite un unique bundle "classique" (balise <script> sans
    // type="module"), seul format qui s'exécute correctement sous
    // file://. Sans impact sur le déploiement cloud (http/https), où
    // un script classique fonctionne aussi normalement.
    legacy({
      // Cible volontairement récente (Chromium embarqué par Electron,
      // navigateurs web à jour) : on ne cherche pas à supporter les
      // vieux navigateurs, seulement à éviter la balise
      // <script type="module">. On limite ainsi le poids de la
      // transpilation Babel et des polyfills ajoutés.
      targets: ['chrome >= 109', 'edge >= 109', 'firefox >= 109', 'safari >= 15'],
      renderModernChunks: false,
      modernPolyfills: false,
    }),
    stripCrossoriginForElectron(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
  },
});
