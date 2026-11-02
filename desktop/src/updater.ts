/**
 * Mises à jour automatiques (DESKTOP.md §11). Canal stable, téléchargement
 * en arrière-plan, installation proposée (jamais forcée pendant une
 * vacation) à la fermeture de l'application.
 *
 * Au redémarrage après mise à jour, `backend.ts`/`desktop_server.py`
 * appliquent déjà : sauvegarde → migrations (DESKTOP.md §5/§6). En cas
 * d'échec de migration, `desktop_server.py::_apply_migrations` lève une
 * exception et le processus s'arrête avant de démarrer Waitress — la
 * restauration automatique de la sauvegarde ET le retour à la version
 * précédente ne sont PAS encore implémentés ici : point ouvert signalé
 * dans le rapport (`packaging-desktop`), car il suppose de pouvoir
 * réinstaller silencieusement un `.exe` antérieur, hors du périmètre
 * standard d'`electron-updater` (qui installe la version la plus récente,
 * pas un retour arrière). À trancher avec le coordinateur avant D7.
 */
import { app, dialog } from 'electron';
import { autoUpdater } from 'electron-updater';
import log from './logger';

let updateReadyToInstall = false;

export function configureAutoUpdater(): void {
  autoUpdater.logger = log;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = false; // on contrôle nous-mêmes via `before-quit`

  autoUpdater.on('update-available', (info) => {
    log.info(`Mise à jour disponible : ${info.version} — téléchargement en arrière-plan.`);
  });

  autoUpdater.on('update-downloaded', (info) => {
    updateReadyToInstall = true;
    log.info(`Mise à jour ${info.version} téléchargée — installation proposée à la fermeture.`);
  });

  autoUpdater.on('error', (err) => {
    log.warn(`Vérification de mise à jour échouée (sans impact sur le fonctionnement local) : ${err.message}`);
  });

  app.on('before-quit', (event) => {
    if (updateReadyToInstall) {
      event.preventDefault();
      void confirmAndInstall();
    }
  });
}

async function confirmAndInstall(): Promise<void> {
  const { response } = await dialog.showMessageBox({
    type: 'question',
    buttons: ['Installer maintenant', 'Plus tard'],
    defaultId: 0,
    cancelId: 1,
    title: 'Mise à jour KIESE disponible',
    message: 'Une mise à jour a été téléchargée. Installer maintenant ?',
    detail: "L'application va se fermer puis redémarrer automatiquement avec la nouvelle version.",
  });
  if (response === 0) {
    autoUpdater.quitAndInstall();
  } else {
    updateReadyToInstall = false;
    app.quit();
  }
}

export function checkForUpdates(): void {
  autoUpdater.checkForUpdates().catch((err) => {
    log.warn(`checkForUpdates : ${(err as Error).message}`);
  });
}
