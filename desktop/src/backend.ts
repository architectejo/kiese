/**
 * Lancement, surveillance et arrêt du backend Django empaqueté
 * (DESKTOP.md §5). Le binaire est `kiese-server.exe` (PyInstaller --onedir,
 * voir `desktop/scripts/build-backend.ps1`), équivalent à
 * `backend/desktop_server.py`.
 */
import { ChildProcess, spawn } from 'child_process';
import * as fs from 'fs';
import * as http from 'http';
import log from './logger';
import { getBackendExecutablePath, getDataDir, getLogsDir } from './paths';
import { DesktopConfig, getDecryptedNodeToken, getDecryptedSecretKey } from './config';

const MAX_RESTARTS = 3;
const HEALTH_CHECK_INTERVAL_MS = 500;
const HEALTH_CHECK_TIMEOUT_MS = 60_000;

/**
 * Code de sortie dédié, renvoyé par `backend/desktop_server.py::main()`
 * quand `_apply_migrations` échoue (BUG-073). Permet à Electron de
 * reconnaître ce cas précis sans parser les logs, pour afficher un
 * message actionnable au lieu de redémarrer le process en boucle.
 */
export const MIGRATION_FAILED_EXIT_CODE = 2;

/** Levée par `startBackend` quand le backend s'est arrêté avant d'avoir
 * répondu au contrôle de santé, avec le code de sortie « échec de
 * migration » (BUG-073). `main.ts` l'intercepte pour afficher le message
 * de restauration manuelle au lieu du message d'erreur générique. */
export class MigrationFailedError extends Error {
  constructor() {
    super('Échec de migration lors du démarrage du backend.');
    this.name = 'MigrationFailedError';
  }
}

export interface BackendHandle {
  port: number;
  process: ChildProcess;
  stop: () => Promise<void>;
}

/**
 * Démarre le backend et attend `GET /api/core/config/` (DESKTOP.md §5
 * étape 6). `onCrash` est appelé si le processus se termine de façon
 * inattendue pendant qu'il tournait normalement (pas pendant un arrêt
 * demandé) — `main.ts` s'en sert pour déclencher les 3 tentatives de
 * redémarrage automatique.
 */
export async function startBackend(
  port: number,
  config: DesktopConfig,
  onCrash: (code: number | null) => void
): Promise<BackendHandle> {
  const dataDir = getDataDir();
  fs.mkdirSync(dataDir, { recursive: true });

  const secretKey = getDecryptedSecretKey(config);
  const nodeToken = getDecryptedNodeToken(config);

  // Secrets transmis UNIQUEMENT par variable d'environnement du process
  // enfant (jamais en argument de ligne de commande, qui serait visible
  // dans le gestionnaire des tâches Windows) — DESKTOP.md §13.
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    KIESE_SECRET_KEY: secretKey,
    KIESE_NODE_CODE: config.nodeCode,
    KIESE_CLOUD_URL: config.cloudUrl,
    KIESE_NODE_TOKEN: nodeToken,
    KIESE_APP_VERSION: config.appVersion,
  };

  const exePath = getBackendExecutablePath();
  const args = ['--port', String(port), '--data-dir', dataDir, '--host', '127.0.0.1'];
  log.info(`Démarrage du backend : ${exePath} ${args.join(' ')}`);

  const child = spawn(exePath, args, { env, windowsHide: true });

  let expectingExit = false;
  let readyResolved = false;

  child.stdout?.on('data', (chunk: Buffer) => {
    log.info(`[backend] ${chunk.toString('utf-8').trim()}`);
  });
  child.stderr?.on('data', (chunk: Buffer) => {
    log.warn(`[backend:stderr] ${chunk.toString('utf-8').trim()}`);
  });
  child.on('exit', (code) => {
    log.info(`Backend terminé (code=${code}, attendu=${expectingExit}).`);
    if (!expectingExit && readyResolved) {
      onCrash(code);
    }
  });
  child.on('error', (err) => {
    log.error(`Erreur de lancement du backend : ${err.message}`);
  });

  // Si le backend s'arrête AVANT d'avoir répondu au contrôle de santé (cas
  // d'un échec de migration au démarrage, BUG-073), inutile d'attendre les
  // 60 s du délai du health-check : on échoue immédiatement, en distinguant
  // le code de sortie « migration échouée » des autres arrêts précoces
  // (port déjà utilisé, erreur de configuration, etc.).
  const exitedBeforeReady = new Promise<never>((_resolve, reject) => {
    child.once('exit', (code) => {
      if (readyResolved) return;
      if (code === MIGRATION_FAILED_EXIT_CODE) {
        reject(new MigrationFailedError());
      } else {
        reject(new Error(`Le backend s'est arrêté avant d'être prêt (code=${code}).`));
      }
    });
  });

  await Promise.race([waitForHealthCheck(port), exitedBeforeReady]);
  readyResolved = true;

  const stop = async (): Promise<void> => {
    expectingExit = true;
    if (child.exitCode !== null || child.killed) return;
    log.info('Arrêt propre du backend demandé.');
    child.kill(); // SIGTERM — Waitress/Python gère l'arrêt propre par défaut.
    const stopped = await waitForExit(child, 5000);
    if (!stopped) {
      log.warn('Le backend ne répond pas à SIGTERM après 5 s — arrêt forcé.');
      child.kill('SIGKILL');
    }
  };

  return { port, process: child, stop };
}

function waitForExit(child: ChildProcess, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    if (child.exitCode !== null) {
      resolve(true);
      return;
    }
    const timer = setTimeout(() => resolve(false), timeoutMs);
    child.once('exit', () => {
      clearTimeout(timer);
      resolve(true);
    });
  });
}

function waitForHealthCheck(port: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + HEALTH_CHECK_TIMEOUT_MS;

    const tryOnce = () => {
      const req = http.get(
        { host: '127.0.0.1', port, path: '/api/core/config/', timeout: 2000 },
        (res) => {
          res.resume();
          if (res.statusCode && res.statusCode < 500) {
            resolve();
          } else {
            retryOrFail();
          }
        }
      );
      req.on('error', retryOrFail);
      req.on('timeout', () => {
        req.destroy();
        retryOrFail();
      });
    };

    const retryOrFail = () => {
      if (Date.now() > deadline) {
        reject(new Error("Le backend n'a pas répondu à /api/core/config/ dans le délai imparti (60 s)."));
        return;
      }
      setTimeout(tryOnce, HEALTH_CHECK_INTERVAL_MS);
    };

    tryOnce();
  });
}

export { MAX_RESTARTS };

export function backendLogPath(): string {
  return `${getLogsDir()}/backend.log`;
}
