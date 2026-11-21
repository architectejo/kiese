/**
 * Sauvegardes et restauration depuis l'interface (DESKTOP.md §8).
 *
 * BUG-403/404 : aucune opération fichier sur la base n'est faite côté Node.
 * Sauvegarde et restauration sont déléguées au binaire backend
 * (`kiese-server.exe backup|restore`, voir `backend/desktop_server.py`) :
 * sauvegarde via `sqlite3.backup()` (journal WAL inclus), restauration avec
 * décompression temporaire, `PRAGMA integrity_check` et copie de sécurité
 * `kiese-avant-restauration-*` AVANT tout remplacement. Ces modes n'ont pas
 * besoin de secret ni de Django.
 */
import { ipcMain } from 'electron';
import { execFile } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import log from './logger';
import { getBackendExecutablePath, getBackupsDir, getDataDir } from './paths';
import { BackendHandle } from './backend';
import { isValidBackupName, parseBackendResult, BackendModeResult } from './backupNames';

export function registerBackupHandlers(getBackendHandle: () => BackendHandle | null, restartBackend: () => Promise<void>): void {
  ipcMain.handle('kiese:backup:list', async () => {
    const dir = getBackupsDir();
    if (!fs.existsSync(dir)) return [];
    return fs
      .readdirSync(dir)
      .filter((f) => isValidBackupName(f))
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

  ipcMain.handle('kiese:backup:restore', async (_event, fileName: unknown) => {
    try {
      await restoreBackup(fileName, getBackendHandle, restartBackend);
      return { ok: true };
    } catch (err) {
      log.error(`Restauration échouée : ${(err as Error).message}`);
      return { ok: false, error: (err as Error).message };
    }
  });
}

/** Lance `kiese-server <mode> --data-dir ...` et renvoie le résultat JSON. */
function runBackendMode(mode: 'backup' | 'restore', extraArgs: string[]): Promise<BackendModeResult> {
  return new Promise((resolve, reject) => {
    const args = [mode, '--data-dir', getDataDir(), ...extraArgs];
    execFile(
      getBackendExecutablePath(),
      args,
      { windowsHide: true, timeout: 10 * 60 * 1000, maxBuffer: 1024 * 1024 },
      (err, stdout) => {
        const parsed = parseBackendResult(String(stdout ?? ''));
        if (parsed) {
          resolve(parsed);
          return;
        }
        reject(
          new Error(
            err
              ? `Le module de sauvegarde n'a pas répondu (${err.message}).`
              : 'Réponse illisible du module de sauvegarde.'
          )
        );
      }
    );
  });
}

/**
 * Sauvegarde à chaud : `sqlite3.backup()` côté backend (WAL inclus), sûre
 * même pendant que Waitress écrit (BUG-403).
 */
async function createBackupFile(): Promise<string> {
  const res = await runBackendMode('backup', []);
  if (!res.ok || !res.path) {
    throw new Error(res.error ?? 'La sauvegarde a échoué.');
  }
  return res.path;
}

async function restoreBackup(
  fileName: unknown,
  getBackendHandle: () => BackendHandle | null,
  restartBackend: () => Promise<void>
): Promise<void> {
  // Refus d'un nom hors liste blanche / hors dossier backups (BUG-404).
  if (!isValidBackupName(fileName)) {
    throw new Error('Nom de sauvegarde invalide.');
  }
  const safeName = path.basename(fileName);
  if (!fs.existsSync(path.join(getBackupsDir(), safeName))) {
    throw new Error(`Sauvegarde introuvable : ${safeName}`);
  }

  const handle = getBackendHandle();
  if (handle) {
    log.info('Restauration : arrêt du backend avant remplacement de la base.');
    await handle.stop();
  }

  let failure: Error | null = null;
  try {
    // Validation, copie de sécurité puis remplacement : tout est fait par le
    // backend ; en cas d'échec la base courante est intacte.
    const res = await runBackendMode('restore', ['--file', safeName]);
    if (!res.ok) {
      failure = new Error(res.error ?? 'La restauration a échoué.');
    } else {
      log.info(
        `Restauration terminée (copie de sécurité : ${res.safetyCopy ?? 'aucune'}), ` +
          'redémarrage du backend (une synchronisation suivra, SYNC.md §9).'
      );
    }
  } catch (err) {
    failure = err as Error;
  }

  // Le backend est toujours relancé (même après un échec : base inchangée).
  await restartBackend();
  if (failure) throw failure;
}
