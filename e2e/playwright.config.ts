import { defineConfig, devices } from '@playwright/test';

/**
 * Configuration Playwright — ETS. KIESE
 *
 * Tourne contre le serveur de dev réel (frontend Vite :5173 / backend Django :8000),
 * déjà lancés par l'opérateur ou un autre agent avant l'exécution de la suite
 * (voir e2e/README pour les commandes de démarrage). On ne pilote pas ici le
 * cycle de vie des serveurs car `db.sqlite3` est partagé avec d'autres agents
 * en session (règle CLAUDE.md / PLAN_2026-10-22.md §0.1) : ne jamais relancer
 * `migrate`/`seed_kiese` depuis ce fichier, ni détruire la base en cours.
 *
 * Chromium est déjà installé dans l'environnement (ne jamais lancer
 * `npx playwright install`).
 */
export default defineConfig({
  testDir: './tests',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  outputDir: '../docs/qa/captures/e2e-results',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },
  projects: [
    {
      name: 'pos',
      use: { ...devices['Desktop Chrome'], viewport: { width: 360, height: 740 } },
    },
    {
      name: 'tablette',
      use: { ...devices['Desktop Chrome'], viewport: { width: 768, height: 1024 } },
    },
    {
      name: 'bureau',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'tv',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } },
    },
  ],
});
