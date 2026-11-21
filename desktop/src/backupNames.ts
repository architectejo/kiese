/**
 * Validation pure (sans dépendance Electron) des noms de sauvegarde (BUG-404).
 * Même règle que `backend/desktop_server.py::validate_backup_file_name`.
 */
import * as path from 'path';

const BACKUP_NAME_RE = /^kiese-[A-Za-z0-9_.-]+\.sqlite3\.gz$/;

export function isValidBackupName(fileName: unknown): fileName is string {
  if (typeof fileName !== 'string' || fileName.length === 0) return false;
  // path.basename (posix ET win32) doit laisser le nom intact : aucun séparateur.
  if (path.posix.basename(fileName) !== fileName || path.win32.basename(fileName) !== fileName) return false;
  if (fileName.includes('..')) return false;
  return BACKUP_NAME_RE.test(fileName);
}

/** Interprète la dernière ligne JSON écrite par `kiese-server backup|restore`. */
export interface BackendModeResult {
  ok: boolean;
  path?: string;
  safetyCopy?: string;
  error?: string;
}

export function parseBackendResult(stdout: string): BackendModeResult | null {
  const lines = stdout.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!lines[i].startsWith('{')) continue;
    try {
      const parsed = JSON.parse(lines[i]);
      if (parsed && typeof parsed.ok === 'boolean') return parsed;
    } catch {
      // ligne de log non JSON : on continue
    }
  }
  return null;
}
