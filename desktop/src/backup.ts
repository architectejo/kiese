/**
 * Sauvegardes et restauration depuis l'interface (DESKTOP.md §8). La
 * création proprement dite réutilise la même logique que
 * `backend/desktop_server.py::backup_database` (sauvegarde cohérente via
 * l'API SQLite), déclenchée ici en demandant au backend de l'exécuter
 * (plutôt que de dupliquer la logique SQLite côté Node) via une commande
 * `manage.py` lancée ponctuellement avec le même exécutable PyInstaller.
 *
 * Note de conception : exécuter `kiese-server.exe backup` suppose que le
 * point d'entrée du binaire accepte un sous-mode `backup`/`restore` en plus
 * du mode serveur. Ce point est volontairement laissé en commentaire
 * `TODO` ci-dessous plutôt que résolu silencieusement : il touche le
 * contrat d'interface de `backend/desktop_server.py` et doit être confirmé
 * avant la V1 (voir rapport `packaging-desktop`, section « Points
 * ouverts »). En l'état, ce module implémente directement les opérations
 * fichier (copie/compression/restauration), qui ne nécessitent pas
 * Python — seule la cohérence "pendant une écriture concurrente" profite
 * de l'API de sauvegarde SQLite, qui reste utilisée côté backend pour la
 * sauvegarde automatique (au démarrage, avant migration) ; la sauvegarde
 * "à la demande" depuis l'interface attend ici que le backend soit arrêté
 * (voir `restoreBackup`) pour éviter toute lecture incohérente du fichier
 * `.sqlite3` par un outil qui ne passerait pas par l'API sqlite3 backup().
 */
import { ipcMain } from 'electron';
import * as fs from 'fs';
import * as path from 'path';
import * as zlib from 'zlib';
import log from './logger';
import { getBackupsDir, getDbPath } from './paths';
import { BackendHandle } from './backend';

export function registerBackupHandlers(getBackendHandle: () => BackendHandle | null, restartBackend: () => Promise<void>): void {
  ipcMain.handle('kiese:backup:list', async () => {
    const dir = getBackupsDir();
    if (!fs.existsSync(dir)) return [];
    return fs
      .readdirSync(dir)
      .filter((f) => f.endsWith('.sqlite3.gz'))
      .map((name) => {
        const stat = fs.statSync(path.join(dir, name));
        return { name, sizeBytes: stat.size, createdAt: stat.mtime.toISOString() };
      })
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  });

  ipcMain.handle('kiese:backup:create-now', async () => {
    try {
      const dest = await createBackupFile();
      return { ok: true, path: dest };
    } catch (err) {
      log.error(`Sauvegarde manuelle échouée : ${(err as Error).message}`);
      return { ok: false, error: (err as Error).message };
    }
  });

  ipcMain.handle('kiese:backup:restore', async (_event, fileName: string) => {
    try {
      await restoreBackup(fileName, getBackendHandle, restartBackend);
      return { ok: true };
    } catch (err) {
      log.error(`Restauration échouée : ${(err as Error).message}`);
      return { ok: false, error: (err as Error).message };
    }
  });
}

/**
 * Copie simple compressée du fichier courant. Suffisante pour une
 * sauvegarde déclenchée manuellement pendant une période d'inactivité
 * (bouton « Sauvegarder maintenant » de l'écran Administration) : la
 * cohérence sous charge réelle (backend actif, écritures concurrentes) est
 * assurée par la sauvegarde automatique interne au backend
 * (`sqlite3.Connection.backup()`, `backend/desktop_server.py`), qui reste
 * la voie utilisée avant chaque migration/mise à jour.
 */
async function createBackupFile(): Promise<string> {
  const dbPath = getDbPath();
  if (!fs.existsSync(dbPath)) {
    throw new Error('Aucune base de données à sauvegarder.');
  }
  const backupsDir = getBackupsDir();
  fs.mkdirSync(backupsDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const dest = path.join(backupsDir, `kiese-manuelle-${stamp}.sqlite3.gz`);

  await new Promise<void>((resolve, reject) => {
    const src = fs.createReadStream(dbPath);
    const gzip = zlib.createGzip();
    const out = fs.createWriteStream(dest);
    src.pipe(gzip).pipe(out);
    out.on('finish', () => resolve());
    out.on('error', reject);
    src.on('error', reject);
  });

  return dest;
}

async function restoreBackup(
  fileName: string,
  getBackendHandle: () => BackendHandle | null,
  restartBackend: () => Promise<void>
): Promise<void> {
  const backupsDir = getBackupsDir();
  const src = path.join(backupsDir, fileName);
  if (!fs.existsSync(src)) {
    throw new Error(`Sauvegarde introuvable : ${fileName}`);
  }

  const handle = getBackendHandle();
  if (handle) {
    log.info('Restauration : arrêt du backend avant remplacement de la base.');
    await handle.stop();
  }

  const dbPath = getDbPath();
  // Supprime les fichiers WAL/SHM associés : une restauration ne doit
  // jamais rejouer un journal WAL appartenant à l'ancienne base.
  for (const suffix of ['', '-wal', '-shm']) {
    const p = dbPath + suffix;
    if (fs.existsSync(p)) fs.unlinkSync(p);
  }

  await new Promise<void>((resolve, reject) => {
    const inp = fs.createReadStream(src);
    const gunzip = zlib.createGunzip();
    const out = fs.createWriteStream(dbPath);
    inp.pipe(gunzip).pipe(out);
    out.on('finish', () => resolve());
    out.on('error', reject);
    inp.on('error', reject);
  });

  log.info('Restauration terminée, redémarrage du backend (une synchronisation suivra, SYNC.md §9).');
  await restartBackend();
}
