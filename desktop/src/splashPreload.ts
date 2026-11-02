/**
 * Pont minimal pour l'écran de démarrage (`resources/splash.html`) — même
 * politique de sécurité que le pont principal (`preload.ts`) :
 * `contextIsolation: true`, `nodeIntegration: false`, aucune API Node
 * exposée directement.
 */
import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('kieseSplashBridge', {
  openLogsFolder: () => ipcRenderer.invoke('kiese:open-logs-folder'),
  retry: () => ipcRenderer.send('kiese:splash:retry'),
  onStatus: (callback: (text: string) => void) => {
    ipcRenderer.on('kiese:splash:status', (_event, text: string) => callback(text));
  },
  onError: (callback: () => void) => {
    ipcRenderer.on('kiese:splash:error', () => callback());
  },
});
