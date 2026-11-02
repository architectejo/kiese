/**
 * Journal Electron (`electron.log`, DESKTOP.md §8 : rotation 10 × 5 Mo).
 * Distinct de `backend.log` (écrit par le processus Python lui-même) et de
 * `sync.log` (actuellement confondu avec `backend.log` : le service de
 * synchronisation tourne dans le même process Python, voir
 * `backend/sync/desktop_client.py` — un fichier séparé serait une
 * complexité sans bénéfice réel tant qu'il n'y a qu'un seul backend par
 * poste, noté ici pour `redacteur-documentation`).
 */
import log from 'electron-log';
import * as fs from 'fs';
import * as path from 'path';
import { getLogsDir } from './paths';

let configured = false;

/** Rotation à 10 fichiers de 5 Mo (DESKTOP.md §8), au lieu du
 * comportement par défaut d'electron-log (un seul fichier `.old.log`). */
function rotateUpTo10(oldLogPath: string): void {
  try {
    const dir = path.dirname(oldLogPath);
    const base = 'electron.log';
    for (let i = 9; i >= 1; i--) {
      const from = path.join(dir, i === 1 ? `${base}.old` : `${base}.old.${i - 1}`);
      const to = path.join(dir, `${base}.old.${i}`);
      if (fs.existsSync(from)) fs.renameSync(from, to);
    }
    fs.renameSync(oldLogPath, path.join(dir, `${base}.old`));
  } catch {
    // La rotation est une commodité, jamais bloquante.
  }
}

export function configureLogger(): void {
  if (configured) return;
  configured = true;
  log.transports.file.resolvePathFn = () => path.join(getLogsDir(), 'electron.log');
  log.transports.file.maxSize = 5 * 1024 * 1024;
  log.transports.file.archiveLogFn = (file) => rotateUpTo10(file.path);
  log.transports.file.level = 'info';
  log.transports.console.level = 'info';
}

export default log;
