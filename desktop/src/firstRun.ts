/**
 * Assistant de première installation (DESKTOP.md §7) : gestion IPC des
 * actions de l'écran `resources/firstRun.html`. L'écran lui-même est une
 * page HTML/JS autonome (pas le frontend React complet : au premier
 * lancement, aucune boulangerie/jeton n'est encore connu, donc aucune
 * donnée métier n'a de sens à charger).
 */
import { ipcMain } from 'electron';
import * as https from 'https';
import * as http from 'http';
import log from './logger';
import { DesktopConfig, ensureSecretKey, loadConfig, saveConfig, setNodeToken } from './config';

export interface FirstRunSubmission {
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

export function registerFirstRunHandlers(onCompleted: (config: DesktopConfig, submission: FirstRunSubmission) => Promise<void>): void {
  ipcMain.handle('kiese:first-run:test-connection', async (_event, cloudUrl: string, nodeToken: string) => {
    try {
      const detail = await handshake(cloudUrl, nodeToken);
      return { ok: true, detail };
    } catch (err) {
      return { ok: false, detail: (err as Error).message };
    }
  });

  ipcMain.handle('kiese:first-run:submit', async (_event, submission: FirstRunSubmission) => {
    try {
      if (!submission.workOffline) {
        await handshake(submission.cloudUrl, submission.nodeToken);
      }

      let config = loadConfig();
      config = ensureSecretKey(config);
      config = setNodeToken(config, submission.workOffline ? '' : submission.nodeToken);
      config = {
        ...config,
        language: submission.language,
        nodeCode: submission.nodeCode.toUpperCase(),
        nodeName: submission.nodeName,
        cloudUrl: submission.workOffline ? '' : submission.cloudUrl,
        printerName: submission.printerName,
        printerWidthMm: submission.printerWidthMm,
        firstRunCompleted: true,
      };
      saveConfig(config);

      await onCompleted(config, submission);
      return { ok: true };
    } catch (err) {
      log.error(`Assistant de première installation échoué : ${(err as Error).message}`);
      return { ok: false, error: (err as Error).message };
    }
  });
}

/** Test de connexion au Cloud (DESKTOP.md §7 étape 3) via
 * `POST /api/sync/handshake/` — jeton de nœud (SYNC.md §8), pas de JWT ici. */
function handshake(cloudUrl: string, nodeToken: string): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!cloudUrl) {
      reject(new Error('URL du cloud manquante.'));
      return;
    }
    let target: URL;
    try {
      target = new URL('/api/sync/handshake/', cloudUrl);
    } catch {
      reject(new Error('URL du cloud invalide.'));
      return;
    }
    const lib = target.protocol === 'https:' ? https : http;
    const req = lib.request(
      target,
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${nodeToken}`, 'Content-Type': 'application/json' },
        timeout: 10_000,
      },
      (res) => {
        let body = '';
        res.on('data', (chunk) => (body += chunk));
        res.on('end', () => {
          if (res.statusCode && res.statusCode < 400) {
            resolve(body);
          } else if (res.statusCode === 503) {
            // BUG-067 : échec transitoire — pas une erreur de
            // configuration, mais on ne peut pas non plus valider la
            // connexion à cet instant précis.
            reject(new Error('Cloud temporairement indisponible (503) — réessayez dans un instant.'));
          } else {
            reject(new Error(`Connexion refusée (${res.statusCode}) : ${body.slice(0, 300)}`));
          }
        });
      }
    );
    req.on('error', (err) => reject(err));
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Délai de connexion dépassé.'));
    });
    req.end();
  });
}
