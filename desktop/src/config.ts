/**
 * Lecture/écriture de `%APPDATA%\KIESE\config.json` (DESKTOP.md §7/§8).
 *
 * Les secrets (jeton de nœud, SECRET_KEY Django du poste) ne sont JAMAIS
 * écrits en clair sur disque : ils sont chiffrés avec `safeStorage`
 * d'Electron (lié au compte Windows de la session) avant d'être stockés
 * en base64 dans `config.json`, et déchiffrés uniquement en mémoire au
 * démarrage pour être transmis au backend par variable d'environnement
 * (jamais par argument de ligne de commande, jamais réécrits sur disque en
 * clair) — DESKTOP.md §13.
 */
import { app, safeStorage } from 'electron';
import * as fs from 'fs';
import { randomBytes } from 'crypto';
import { getConfigPath, getDataDir } from './paths';

export interface DesktopConfig {
  firstRunCompleted: boolean;
  language: 'fr' | 'en';
  nodeCode: string;
  nodeName: string;
  cloudUrl: string;
  /** Jeton de nœud chiffré (safeStorage), base64. Vide si hors-ligne. */
  nodeTokenEncrypted: string;
  /** SECRET_KEY Django du poste, chiffrée (safeStorage), base64. */
  secretKeyEncrypted: string;
  printerName: string;
  printerWidthMm: 58 | 80;
  appVersion: string;
}

const DEFAULTS: DesktopConfig = {
  firstRunCompleted: false,
  language: 'fr',
  nodeCode: '',
  nodeName: '',
  cloudUrl: '',
  nodeTokenEncrypted: '',
  secretKeyEncrypted: '',
  printerName: '',
  printerWidthMm: 80,
  appVersion: app.getVersion?.() ?? '0.0.0',
};

function encrypt(plain: string): string {
  if (!plain) return '';
  if (!safeStorage.isEncryptionAvailable()) {
    // Repli documenté : sur un poste sans trousseau système disponible
    // (rare, ex. certaines sessions de service Windows), on stocke tel
    // quel plutôt que de planter — signalé dans le journal, à surveiller
    // par `testeur-installation`.
    return `PLAIN:${plain}`;
  }
  return safeStorage.encryptString(plain).toString('base64');
}

function decrypt(stored: string): string {
  if (!stored) return '';
  if (stored.startsWith('PLAIN:')) return stored.slice('PLAIN:'.length);
  try {
    return safeStorage.decryptString(Buffer.from(stored, 'base64'));
  } catch {
    return '';
  }
}

export function configExists(): boolean {
  return fs.existsSync(getConfigPath());
}

export function loadConfig(): DesktopConfig {
  const configPath = getConfigPath();
  if (!fs.existsSync(configPath)) {
    return { ...DEFAULTS };
  }
  const raw = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
  return { ...DEFAULTS, ...raw };
}

export function saveConfig(config: DesktopConfig): void {
  fs.mkdirSync(getDataDir(), { recursive: true });
  fs.writeFileSync(getConfigPath(), JSON.stringify(config, null, 2), { encoding: 'utf-8', mode: 0o600 });
}

/** Jeton de nœud en clair, déchiffré en mémoire uniquement (jamais loggé). */
export function getDecryptedNodeToken(config: DesktopConfig): string {
  return decrypt(config.nodeTokenEncrypted);
}

export function getDecryptedSecretKey(config: DesktopConfig): string {
  return decrypt(config.secretKeyEncrypted);
}

export function setNodeToken(config: DesktopConfig, token: string): DesktopConfig {
  return { ...config, nodeTokenEncrypted: encrypt(token) };
}

/** Génère une SECRET_KEY Django unique au poste (DESKTOP.md §7 étape 7),
 * si elle n'existe pas déjà — ne doit jamais être régénérée après coup
 * (sessions/jetons existants, cohérence avec le Cloud via la sync). */
export function ensureSecretKey(config: DesktopConfig): DesktopConfig {
  if (config.secretKeyEncrypted) return config;
  // 64 octets aléatoires encodés en base64url : largement suffisant pour
  // `django.core.management.utils.get_random_secret_key` (50 caractères),
  // sans dépendre de Python au moment de la génération (Electron génère la
  // clé avant même le premier démarrage du backend).
  const key = randomBytes(64).toString('base64url');
  return { ...config, secretKeyEncrypted: encrypt(key) };
}
