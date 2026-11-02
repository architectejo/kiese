/**
 * Typage du pont Electron exposé en `window.kiese` par
 * `desktop/src/preload.ts` (contextBridge). Ce fichier ne doit décrire
 * QUE ce que `preload.ts` expose réellement — toute extension doit être
 * faite côté `desktop/` d'abord, puis reportée ici.
 *
 * Hors du mode desktop (navigateur classique, POS Android), `window.kiese`
 * est `undefined` : tout code appelant doit vérifier sa présence avant
 * utilisation (voir `src/components/admin/BackupManager.tsx`).
 */

export interface KieseBackupEntry {
  /** Nom de fichier dans le dossier de sauvegardes (ex: kiese-2026-10-23T08-00-00-000Z.sqlite3.gz). */
  name: string;
  sizeBytes: number;
  /** ISO 8601, date de dernière modification du fichier sur disque. */
  createdAt: string;
}

export interface KieseBackupResult {
  ok: boolean;
  error?: string;
}

export interface KieseCreateBackupResult extends KieseBackupResult {
  path?: string;
}

export interface KieseBridge {
  apiUrl?: string;
  appVersion?: string;
  /** Largeur de l'imprimante thermique configurée côté desktop
   * (`DesktopConfig.printerWidthMm`, 58 ou 80mm), injectée au démarrage
   * de la fenêtre. BUG-077 : à utiliser comme valeur par défaut pour la
   * prop `printerWidthMm` de `ThermalReceipt` dans les pages qui
   * affichent le reçu (ex. `window.kiese?.printerWidthMm ?? 80`). Absent
   * (`undefined`) hors mode desktop : retomber sur 80mm. */
  printerWidthMm?: 58 | 80;
  printReceipt?: (html: string, options: { widthMm: 58 | 80 }) => Promise<{ ok: boolean; error?: string }>;
  listPrinters?: () => Promise<Array<{ name: string; displayName: string }>>;
  openLogsFolder?: () => Promise<void>;
  getSyncStatus?: () => Promise<unknown>;
  backup?: {
    createNow: () => Promise<KieseCreateBackupResult>;
    list: () => Promise<KieseBackupEntry[]>;
    restore: (fileName: string) => Promise<KieseBackupResult>;
  };
}

declare global {
  interface Window {
    kiese?: KieseBridge;
  }
}

export {};
