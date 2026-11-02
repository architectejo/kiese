/**
 * Impression silencieuse des reçus thermiques (DESKTOP.md §10).
 * Formats pris en charge : 58 mm et 80 mm. Hors desktop (navigateur, POS
 * Android), le frontend retombe sur `window.print()` existant — ce fichier
 * ne concerne que le cas Electron.
 */
import { BrowserWindow, ipcMain } from 'electron';
import log from './logger';

// 1 mm ≈ 3.7795275591 px à 96 DPI — Electron attend `pageSize` en microns.
const WIDTH_MICRONS: Record<58 | 80, number> = {
  58: 58000,
  80: 80000,
};
// Hauteur généreuse : le pilote thermique découpe/avance réellement selon
// le contenu, cette valeur n'est qu'un cadre d'impression suffisant pour un
// reçu typique (CLAUDE.md §5.2 : entête, lignes, totaux, BP).
const HEIGHT_MICRONS = 297000; // ~ A4 de secours, le pilote thermique ignore l'excédent

export function registerPrintingHandlers(getPrinterName: () => string): void {
  ipcMain.handle(
    'kiese:print-receipt',
    async (_event, html: string, options: { widthMm: 58 | 80 }) => {
      const printerName = getPrinterName();
      if (!printerName) {
        return { ok: false, error: "Aucune imprimante thermique configurée (voir Paramètres)." };
      }
      try {
        await printHtml(html, printerName, options.widthMm);
        return { ok: true };
      } catch (err) {
        log.error(`Impression échouée : ${(err as Error).message}`);
        return { ok: false, error: (err as Error).message };
      }
    }
  );

  ipcMain.handle('kiese:list-printers', async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (!win) return [];
    const printers = await win.webContents.getPrintersAsync();
    return printers.map((p) => ({ name: p.name, displayName: p.displayName }));
  });
}

function printHtml(html: string, deviceName: string, widthMm: 58 | 80): Promise<void> {
  return new Promise((resolve, reject) => {
    const printWindow = new BrowserWindow({
      show: false,
      webPreferences: {
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });

    printWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);

    printWindow.webContents.once('did-finish-load', () => {
      printWindow.webContents.print(
        {
          silent: true,
          deviceName,
          margins: { marginType: 'none' },
          pageSize: { width: WIDTH_MICRONS[widthMm], height: HEIGHT_MICRONS },
          printBackground: true,
        },
        (success, errorType) => {
          printWindow.close();
          if (success) {
            resolve();
          } else {
            reject(new Error(errorType || 'Échec impression inconnu.'));
          }
        }
      );
    });

    printWindow.webContents.once('did-fail-load', (_e, code, description) => {
      printWindow.close();
      reject(new Error(`Chargement du reçu impossible (${code}) : ${description}`));
    });
  });
}
