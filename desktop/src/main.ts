/**
 * Processus principal Electron (DESKTOP.md §5). Orchestre : assistant de
 * première installation → démarrage du backend → fenêtre principale →
 * impression, sauvegardes, mises à jour.
 */
import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron';
import * as fs from 'fs';
import * as path from 'path';
import log, { configureLogger } from './logger';
import { getBackupsDir, getFrontendIndexPath, getLogsDir } from './paths';
import { DesktopConfig, configExists, ensureSecretKey, loadConfig, saveConfig } from './config';
import { BackendHandle, MAX_RESTARTS, MIGRATION_FAILED_EXIT_CODE, MigrationFailedError, startBackend } from './backend';
import { findFreePort } from './port';
import { registerPrintingHandlers } from './printing';
import { registerBackupHandlers } from './backup';
import { registerFirstRunHandlers, FirstRunSubmission } from './firstRun';
import { configureAutoUpdater, checkForUpdates } from './updater';

let splashWindow: BrowserWindow | null = null;
let firstRunWindow: BrowserWindow | null = null;
let mainWindow: BrowserWindow | null = null;
let backendHandle: BackendHandle | null = null;
let restartAttempts = 0;
let currentConfig: DesktopConfig = loadConfig();
// BUG-080 : protège contre les clics multiples sur « Réessayer » pendant
// qu'une tentative de démarrage du backend est déjà en cours.
let retryInProgress = false;

const PRELOAD_PATH = path.join(__dirname, 'preload.js');
const SPLASH_PRELOAD_PATH = path.join(__dirname, 'splashPreload.js');

function bootInfo() {
  return {
    apiUrl: backendHandle ? `http://127.0.0.1:${backendHandle.port}` : '',
    appVersion: app.getVersion(),
    // BUG-077 (volet desktop) : expose la largeur d'imprimante thermique
    // configurée (assistant de première installation / paramètres) pour
    // que le frontend l'utilise par défaut sans round-trip IPC
    // asynchrone — lu depuis `currentConfig`, donc à jour après le
    // premier lancement (voir `registerFirstRunHandlers` ci-dessous qui
    // réassigne `currentConfig`).
    printerWidthMm: currentConfig.printerWidthMm,
  };
}

// `sendSync` : doit être enregistré avant la création de toute fenêtre
// utilisant `preload.ts` (voir le commentaire de ce fichier sur l'ordre
// d'évaluation des modules de la page).
ipcMain.on('kiese:get-boot-info', (event) => {
  event.returnValue = bootInfo();
});

ipcMain.handle('kiese:open-logs-folder', async () => {
  await shell.openPath(getLogsDir());
});

/**
 * BUG-080 : le bouton « Réessayer » de l'écran de démarrage
 * (`resources/splash.html` → `splashPreload.ts::retry()`) envoyait le
 * message IPC `kiese:splash:retry` dans le vide, sans aucun gestionnaire
 * côté process principal. On relance ici exactement la même séquence que
 * le démarrage initial (nouveau port, nouvelle tentative de `startBackend`),
 * sans que l'utilisateur ait à fermer/rouvrir toute l'application.
 */
ipcMain.on('kiese:splash:retry', () => {
  if (retryInProgress || mainWindow) return;
  retryInProgress = true;
  setSplashStatus('Nouvelle tentative de démarrage du serveur local…');
  void stopBackendIfRunning()
    .then(() => launchBackendAndMainWindow())
    .catch((err) => {
      log.error(`Nouvelle tentative (Réessayer) échouée : ${(err as Error).message}`);
      setSplashError();
    })
    .finally(() => {
      retryInProgress = false;
    });
});

ipcMain.handle('kiese:get-sync-status', async () => {
  if (!backendHandle) return { mode: 'OFFLINE_NOT_STARTED' };
  try {
    const res = await fetchLocal(`http://127.0.0.1:${backendHandle.port}/api/sync/local-status/`);
    return res;
  } catch {
    return { mode: 'UNKNOWN' };
  }
});

function fetchLocal(url: string): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const http = require('http');
    http
      .get(url, (res: any) => {
        let body = '';
        res.on('data', (c: Buffer) => (body += c));
        res.on('end', () => {
          try {
            resolve(JSON.parse(body));
          } catch (e) {
            reject(e);
          }
        });
      })
      .on('error', reject);
  });
}

function createSplashWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 420,
    height: 280,
    frame: false,
    resizable: false,
    icon: path.join(__dirname, '..', 'resources', 'icon.ico'),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: SPLASH_PRELOAD_PATH,
    },
  });
  win.loadFile(path.join(__dirname, '..', 'resources', 'splash.html'));
  return win;
}

function setSplashStatus(text: string): void {
  splashWindow?.webContents.send('kiese:splash:status', text);
}

function setSplashError(): void {
  splashWindow?.webContents.send('kiese:splash:error');
}

/**
 * Nom de la sauvegarde créée juste avant la migration qui a échoué
 * (BUG-073 — voir `backend/desktop_server.py::_mark_pre_migration_backup`).
 * Marqueur best-effort : s'il est absent (ancienne version du backend,
 * premier démarrage sans base existante, etc.), le dialogue d'erreur
 * reste générique plutôt que d'afficher un nom de fichier incorrect.
 */
function readLastPreMigrationBackupName(): string | null {
  try {
    const marker = path.join(getBackupsDir(), '.last_pre_migration_backup');
    if (!fs.existsSync(marker)) return null;
    const name = fs.readFileSync(marker, 'utf-8').trim();
    return name || null;
  } catch (err) {
    log.warn(`Lecture du marqueur de sauvegarde pré-migration impossible : ${(err as Error).message}`);
    return null;
  }
}

/**
 * Message bloquant (BUG-073, décision client du 2026-10-23 : restauration
 * manuelle guidée, pas de rollback automatique). Pas de redémarrage
 * automatique après ce dialogue — l'appelant doit fermer l'application
 * plutôt que de retenter le démarrage du backend, pour éviter une boucle
 * d'échecs silencieuse.
 */
function showMigrationFailureDialog(): void {
  const backupName = readLastPreMigrationBackupName();
  const backupLine = backupName
    ? `La sauvegarde automatique créée juste avant la mise à jour s'appelle :\n\n    ${backupName}\n\n`
    : "Une sauvegarde automatique a été créée juste avant la mise à jour (dossier « backups », fichier le plus récent).\n\n";

  const message =
    'La mise à jour a échoué à cause d\'un problème de migration de la base de données.\n\n' +
    'Vos données sont intactes : elles n\'ont pas été modifiées, et une sauvegarde automatique ' +
    'a été prise juste avant la tentative de mise à jour.\n\n' +
    backupLine +
    'Marche à suivre :\n' +
    '1. Ouvrez le menu Administration de l\'application.\n' +
    '2. Choisissez « Restaurer une sauvegarde ».\n' +
    '3. Sélectionnez la sauvegarde la plus récente (celle indiquée ci-dessus si elle apparaît dans la liste).\n' +
    '4. Confirmez la restauration, puis contactez le support avant de retenter la mise à jour.\n\n' +
    'L\'application va maintenant se fermer. Le dossier des sauvegardes va s\'ouvrir pour vérification.';

  dialog.showMessageBoxSync({
    type: 'error',
    title: 'KIESE — Mise à jour impossible',
    message: 'Mise à jour impossible : problème de migration',
    detail: message,
    buttons: ['Fermer'],
    defaultId: 0,
    noLink: true,
  });

  void shell.openPath(getBackupsDir());
}

function createFirstRunWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 640,
    height: 640,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: PRELOAD_PATH,
    },
  });
  win.setMenuBarVisibility(false);
  win.loadFile(path.join(__dirname, '..', 'resources', 'firstRun.html'));
  return win;
}

function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    icon: path.join(__dirname, '..', 'resources', 'icon.ico'),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: PRELOAD_PATH,
    },
  });
  win.setMenuBarVisibility(false);

  // Navigation limitée à 127.0.0.1 + fichiers locaux du frontend empaqueté
  // (DESKTOP.md §3.4 : sécurité, pas de navigation libre).
  win.webContents.on('will-navigate', (event, url) => {
    const allowed = url.startsWith('file://') || url.startsWith('http://127.0.0.1:');
    if (!allowed) {
      event.preventDefault();
      log.warn(`Navigation bloquée vers une origine non autorisée : ${url}`);
    }
  });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));

  win.loadFile(getFrontendIndexPath());
  win.once('ready-to-show', () => win.show());
  return win;
}

async function launchBackendAndMainWindow(): Promise<void> {
  const port = await findFreePort();
  setSplashStatus('Démarrage du serveur local…');

  try {
    backendHandle = await startBackend(port, currentConfig, handleBackendCrash);
  } catch (err) {
    if (err instanceof MigrationFailedError) {
      await quitAfterMigrationFailure();
      return;
    }
    log.error(`Démarrage du backend impossible : ${(err as Error).message}`);
    setSplashError();
    return;
  }

  restartAttempts = 0;
  splashWindow?.close();
  splashWindow = null;
  mainWindow = createMainWindow();
}

/**
 * BUG-073 : échec de migration détecté (code de sortie dédié du backend).
 * Bloque avec un message clair plutôt que de retenter un démarrage — un
 * nouvel essai relancerait la même migration en échec indéfiniment.
 * Décision client (restauration manuelle guidée) : l'utilisateur doit
 * restaurer lui-même la sauvegarde automatique créée juste avant la
 * migration, depuis l'écran Administration, avant de relancer KIESE.
 */
async function quitAfterMigrationFailure(): Promise<void> {
  log.error(
    'Échec de migration au démarrage du backend (code de sortie=2) — arrêt sans nouvelle ' +
      "tentative automatique (BUG-073). Sauvegarde automatique disponible dans le dossier backups."
  );
  splashWindow?.close();
  splashWindow = null;
  await stopBackendIfRunning();
  showMigrationFailureDialog();
  app.quit();
}

async function handleBackendCrash(code: number | null): Promise<void> {
  log.error(`Le backend s'est arrêté de façon inattendue (code=${code}).`);
  if (code === MIGRATION_FAILED_EXIT_CODE) {
    // Ne jamais entrer dans la boucle de redémarrage automatique pour ce
    // cas précis (BUG-073) : la migration échouerait de nouveau à
    // l'identique à chaque tentative.
    await quitAfterMigrationFailure();
    return;
  }
  if (restartAttempts >= MAX_RESTARTS) {
    log.error('Nombre maximal de redémarrages atteint — abandon.');
    mainWindow?.webContents.send('kiese:backend-crashed');
    return;
  }
  restartAttempts += 1;
  log.info(`Nouvelle tentative de démarrage du backend (${restartAttempts}/${MAX_RESTARTS}).`);
  try {
    const port = await findFreePort();
    backendHandle = await startBackend(port, currentConfig, handleBackendCrash);
    mainWindow?.loadFile(getFrontendIndexPath());
  } catch (err) {
    if (err instanceof MigrationFailedError) {
      await quitAfterMigrationFailure();
      return;
    }
    log.error(`Redémarrage du backend échoué : ${(err as Error).message}`);
  }
}

async function stopBackendIfRunning(): Promise<void> {
  if (backendHandle) {
    await backendHandle.stop();
    backendHandle = null;
  }
}

async function restartBackendForRestore(): Promise<void> {
  const port = await findFreePort();
  try {
    backendHandle = await startBackend(port, currentConfig, handleBackendCrash);
  } catch (err) {
    if (err instanceof MigrationFailedError) {
      await quitAfterMigrationFailure();
      return;
    }
    throw err;
  }
  mainWindow?.loadFile(getFrontendIndexPath());
}

async function bootstrap(): Promise<void> {
  configureLogger();
  log.info('=== Démarrage de KIESE (Electron) ===');

  registerPrintingHandlers(() => currentConfig.printerName);
  registerBackupHandlers(() => backendHandle, restartBackendForRestore);
  registerFirstRunHandlers(async (config, submission: FirstRunSubmission) => {
    currentConfig = config;
    await launchBackendAfterFirstRun(submission);
  });

  if (!configExists() || !currentConfig.firstRunCompleted) {
    firstRunWindow = createFirstRunWindow();
    return;
  }

  splashWindow = createSplashWindow();
  await launchBackendAndMainWindow();

  configureAutoUpdater();
  checkForUpdates();
}

async function launchBackendAfterFirstRun(submission: FirstRunSubmission): Promise<void> {
  splashWindow = createSplashWindow();
  firstRunWindow?.close();
  firstRunWindow = null;

  const port = await findFreePort();
  setSplashStatus('Première configuration du serveur local…');

  try {
    backendHandle = await startBackend(port, currentConfig, handleBackendCrash);
  } catch (err) {
    if (err instanceof MigrationFailedError) {
      await quitAfterMigrationFailure();
      return;
    }
    log.error(`Démarrage initial du backend impossible : ${(err as Error).message}`);
    setSplashError();
    return;
  }

  // Création du compte administrateur local de secours (DESKTOP.md §7
  // étape 5) : le backend serveur tourne déjà sur ce port, donc on s'arrête
  // d'abord pour éviter que deux process Python n'ouvrent la même base
  // SQLite simultanément (la commande ponctuelle ouvre aussi la base), puis
  // on relance le serveur normalement.
  try {
    await backendHandle.stop();
    await runOneOffManagementCommand(['ensure_local_admin', '--username', submission.adminUsername], submission.adminPassword);
    backendHandle = await startBackend(port, currentConfig, handleBackendCrash);
  } catch (err) {
    log.error(`Création du compte administrateur local échouée : ${(err as Error).message}`);
    // Non bloquant pour autant : point à vérifier par `testeur-installation`
    // (voir rapport, section « points ouverts ») — un ADMIN local manquant
    // empêche la connexion hors-ligne mais pas le reste de l'application.
  }

  restartAttempts = 0;
  splashWindow?.close();
  splashWindow = null;
  mainWindow = createMainWindow();

  configureAutoUpdater();
  checkForUpdates();
}

/**
 * Exécute `kiese-server.exe manage --data-dir <dir> <args...>` (voir
 * `backend/desktop_server.py::_run_single_management_command`), sans
 * démarrer Waitress. Utilisé uniquement pendant l'assistant de première
 * installation, le backend serveur étant arrêté pendant cet appel pour
 * éviter deux process Python ouvrant la même base SQLite en même temps.
 */
function runOneOffManagementCommand(commandArgs: string[], adminPassword?: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const { spawn } = require('child_process');
    const { getBackendExecutablePath, getDataDir } = require('./paths');
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      KIESE_SECRET_KEY: require('./config').getDecryptedSecretKey(currentConfig),
    };
    if (adminPassword) env.KIESE_LOCAL_ADMIN_PASSWORD = adminPassword;

    const child = spawn(getBackendExecutablePath(), ['manage', '--data-dir', getDataDir(), ...commandArgs], {
      env,
      windowsHide: true,
    });
    let stderr = '';
    child.stderr?.on('data', (c: Buffer) => (stderr += c.toString('utf-8')));
    child.on('exit', (code: number | null) => {
      if (code === 0) resolve();
      else reject(new Error(`Commande de gestion échouée (code=${code}) : ${stderr.slice(0, 500)}`));
    });
    child.on('error', reject);
  });
}

app.on('ready', () => {
  void bootstrap();
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', async (event) => {
  if (backendHandle) {
    event.preventDefault();
    await stopBackendIfRunning();
    app.quit();
  }
});
