import { test, expect } from '@playwright/test';
import { COMPTES, PASSWORD } from '../fixtures/comptes';
import { seConnecter } from '../fixtures/helpers';

/**
 * Parcours 7 & 8 — Clôture et Livre de Caisse (CLAUDE.md §2 points 7-8 / §5.5).
 */

test('la direction consulte le Livre de Caisse, filtre par dates et vérifie l\'intégrité (verte)', async ({ page }) => {
  await seConnecter(page, COMPTES.direction.username, PASSWORD);
  await page.goto('/treasury');

  await expect(page.getByRole('heading', { name: /livre de caisse direction/i })).toBeVisible();

  const dateInputs = page.locator('input[type="date"]');
  await expect(dateInputs.first()).toBeVisible();
  const aujourdhui = new Date().toISOString().slice(0, 10);
  const ilYaUneSemaine = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString().slice(0, 10);
  await dateInputs.nth(0).fill(ilYaUneSemaine);
  await dateInputs.nth(1).fill(aujourdhui);

  const boutonIntegrite = page.getByRole('button', { name: /vérifier intégrité sha-256/i });
  await expect(boutonIntegrite).toBeVisible();
  await boutonIntegrite.click();

  await expect(
    page.getByText(/chaîne intègre|altérations détectées/i)
  ).toBeVisible({ timeout: 15_000 });
});

test('un rôle non-HQ (gérant) ne voit pas le Livre de Caisse Direction (BUG-026/BUG-044, déjà corrigé)', async ({ page }) => {
  // Note (testeur-e2e, 2026-11-03) : scope restreint au titre de section §5.1.3
  // (Treasury.tsx l.1941-1943, gardé par `user?.can_access_all_nodes`), pas à
  // n'importe quelle occurrence du texte — le sous-titre générique du module
  // ("Clôture & Caisse — 3 Niveaux" / "§5.1 ... · §5.3 Livre de Caisse
  // Direction", Treasury.tsx l.1305-1307) mentionne les 3 niveaux à TOUS les
  // rôles à titre descriptif, sans donner accès au Niveau 3 — un `getByText`
  // non scopé matchait aussi ce sous-titre et faisait échouer ce test sur un
  // faux positif (aucune régression réelle : confirmé par relecture de
  // Treasury.tsx, la section §5.1.3 elle-même — avec ses boutons "Vérifier
  // intégrité SHA-256"/filtres de dates/historique — reste bien absente du DOM
  // pour un GERANT).
  await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  await page.goto('/treasury');
  await expect(page.getByRole('heading', { name: /§5\.1\.3.*Livre de Caisse Direction/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /vérifier intégrité sha-256/i })).toHaveCount(0);
});

test.fixme(
  'clôture gérant : rapport facturier Niveau 1 (équipes A et B), dépenses, ventilation des billets, écart affiché',
  async () => {
    // Nécessite un historique de facturation/livraison réel sur la journée en
    // cours pour les deux équipes A et B afin que le rapport Niveau 1 ne soit
    // pas vide, puis la saisie complète des 8 dénominations de billets
    // (20000..50 FC) dans le formulaire de clôture Niveau 2 — chaîne de
    // dépendances longue (facturation → livraison → rapport → clôture) non
    // bouclée dans le temps disponible de cette session. Couverture
    // backend déjà solide (voir BUG-033 à BUG-037 dans le registre, tous
    // VÉRIFIÉS par testeur-tresorerie) ; priorité suivante pour renforcer
    // la couverture E2E de ce module.
  }
);

test.fixme(
  'versement de la clôture confirmée au Livre de Caisse par la Direction',
  async () => {
    // Dépend du scénario de clôture ci-dessus (bouton "Inscrire au Livre de
    // Caisse" visible uniquement sur une FacturierReport/CashClosure déjà
    // confirmée par le Comptable) — reporté pour la même raison.
  }
);
