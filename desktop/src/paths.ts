/**
 * Chemins du poste (DESKTOP.md §8). Le dossier de données est fixé à
 * `%APPDATA%\KIESE\` explicitement (pas `app.getPath('userData')`, qui
 * dépendrait du `productName` retenu par electron-builder et pourrait
 * changer d'un build à l'autre) — c'est le dossier documenté au client et
 * aux testeurs d'installation.
 */
import { app } from 'electron';
import * as path from 'path';

export function getDataDir(): string {
  // `app.getPath('appData')` renvoie `%APPDATA%` sous Windows (et son
  // équivalent sur les autres plateformes, utile en développement sur un
  // poste non-Windows).
  return path.join(app.getPath('appData'), 'KIESE');
}

export function getConfigPath(): string {
  return path.join(getDataDir(), 'config.json');
}

export function getDbPath(): string {
  return path.join(getDataDir(), 'kiese.sqlite3');
}

export function getLogsDir(): string {
  return path.join(getDataDir(), 'logs');
}

export function getBackupsDir(): string {
  return path.join(getDataDir(), 'backups');
}

export function getMediaDir(): string {
  return path.join(getDataDir(), 'media');
}

/** Dossier des ressources packagées (backend PyInstaller, frontend Vite). */
export function getResourcesDir(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath);
  }
  return path.join(__dirname, '..', 'resources');
}

export function getBackendExecutablePath(): string {
  const exeName = process.platform === 'win32' ? 'kiese-server.exe' : 'kiese-server';
  return path.join(getResourcesDir(), 'backend', exeName);
}

export function getFrontendIndexPath(): string {
  return path.join(getResourcesDir(), 'frontend', 'index.html');
}
