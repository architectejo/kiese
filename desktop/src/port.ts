/**
 * Choix d'un port libre sur 127.0.0.1 (DESKTOP.md §5, plage 18000-18999).
 * Pas de dépendance externe (`get-port` récent est ESM-only, incompatible
 * avec ce projet CommonJS) : un simple essai d'écoute suffit.
 */
import * as net from 'net';

const RANGE_START = 18000;
const RANGE_END = 18999;

function isPortFree(port: number, host: string): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.listen(port, host, () => {
      server.close(() => resolve(true));
    });
  });
}

export async function findFreePort(host = '127.0.0.1'): Promise<number> {
  // Ordre aléatoire dans la plage pour éviter qu'un ancien processus
  // fantôme occupant toujours le premier port habituel (18000) ne force
  // systématiquement un comportement différent à chaque redémarrage.
  const ports: number[] = [];
  for (let p = RANGE_START; p <= RANGE_END; p++) ports.push(p);
  for (let i = ports.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [ports[i], ports[j]] = [ports[j], ports[i]];
  }
  for (const port of ports) {
    if (await isPortFree(port, host)) return port;
  }
  throw new Error('Aucun port libre trouvé entre 18000 et 18999.');
}
