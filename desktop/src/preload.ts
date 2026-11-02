/**
 * Pont sécurisé exposé au frontend (`window.kiese`), DESKTOP.md §3.4/§5.7.
 * `contextIsolation: true` + `nodeIntegration: false` (voir main.ts) :
 * aucune API Node/Electron brute n'est accessible depuis le code React —
 * seules les fonctions explicitement listées ici le sont, via
 * `contextBridge`.
 */
import { contextBridge, ipcRenderer } from 'electron';

export interface KieseBridge {
  /** URL de base de l'API, construite avec le port dynamique choisi au
   * démarrage (DESKTOP.md §5 étape 7) — remplace `VITE_API_URL` figé au
   * build pour toute exécution en mode desktop. */
  apiUrl: string;
  appVersion: string;
  /** Largeur de l'imprimante thermique configurée (assistant de première
   * installation ou paramètres), `DesktopConfig.printerWidthMm` — BUG-077
   * (volet desktop). Valeur par défaut 80mm si jamais configurée (voir
   * `desktop/src/config.ts::DEFAULTS`). À utiliser comme valeur par
   * défaut pour la prop `printerWidthMm` de `ThermalReceipt` ; hors mode
   * desktop, `window.kiese` est `undefined` et l'appelant doit retomber
   * sur 80mm. */
  printerWidthMm: 58 | 80;
  printReceipt: (html: string, options: { widthMm: 58 | 80 }) => Promise<{ ok: boolean; error?: string }>;
  listPrinters: () => Promise<Array<{ name: string; displayName: string }>>;
  openLogsFolder: () => Promise<void>;
  getSyncStatus: () => Promise<unknown>;
  // Premier lancement uniquement (assistant) :
  firstRun: {
    testCloudConnection: (cloudUrl: string, nodeToken: string) => Promise<{ ok: boolean; detail?: string }>;
    submit: (payload: FirstRunPayload) => Promise<{ ok: boolean; error?: string }>;
  };
  backup: {
    createNow: () => Promise<{ ok: boolean; path?: string; error?: string }>;
    list: () => Promise<Array<{ name: string; sizeBytes: number; createdAt: string }>>;
    restore: (fileName: string) => Promise<{ ok: boolean; error?: string }>;
  };
}

export interface FirstRunPayload {
  language: 'fr' | 'en';
  nodeCode: string;
  nodeName: string;
  cloudUrl: string;
  nodeToken: string;
  workOffline: boolean;
  adminUsername: string;
  adminPassword: string;
  printerName: string;
  printerWidthMm: 58 | 80;
}

const bridge: KieseBridge = {
  apiUrl: '', // injecté synchroniquement ci-dessous avant `exposeInMainWorld`
  appVersion: '',
  printerWidthMm: 80, // valeur par défaut avant injection synchronique ci-dessous
  printReceipt: (html, options) => ipcRenderer.invoke('kiese:print-receipt', html, options),
  listPrinters: () => ipcRenderer.invoke('kiese:list-printers'),
  openLogsFolder: () => ipcRenderer.invoke('kiese:open-logs-folder'),
  getSyncStatus: () => ipcRenderer.invoke('kiese:get-sync-status'),
  firstRun: {
    testCloudConnection: (cloudUrl, nodeToken) =>
      ipcRenderer.invoke('kiese:first-run:test-connection', cloudUrl, nodeToken),
    submit: (payload) => ipcRenderer.invoke('kiese:first-run:submit', payload),
  },
  backup: {
    createNow: () => ipcRenderer.invoke('kiese:backup:create-now'),
    list: () => ipcRenderer.invoke('kiese:backup:list'),
    restore: (fileName) => ipcRenderer.invoke('kiese:backup:restore', fileName),
  },
};

// `apiUrl`/`appVersion` sont lus synchroniquement via `ipcRenderer.sendSync`
// pour être disponibles AVANT l'évaluation des modules de la page (en
// particulier `frontend/src/api/client.ts`, qui lit `window.kiese.apiUrl`
// à l'évaluation du module) — un `invoke` (asynchrone) arriverait trop
// tard pour ce cas précis.
const boot = ipcRenderer.sendSync('kiese:get-boot-info') as {
  apiUrl: string;
  appVersion: string;
  printerWidthMm: 58 | 80;
};
bridge.apiUrl = boot.apiUrl;
bridge.appVersion = boot.appVersion;
bridge.printerWidthMm = boot.printerWidthMm;

contextBridge.exposeInMainWorld('kiese', bridge);
