import { test, expect } from '@playwright/test';
import { COMPTES, PASSWORD } from '../fixtures/comptes';
import { seConnecter, seDeconnecter } from '../fixtures/helpers';

/**
 * Parcours 2 — Connexion par rôle, menu adapté, déconnexion (CLAUDE.md §2.2).
 * Référence menu : frontend/src/components/layout/DashboardLayout.tsx (navItems).
 */

// Libellés exacts de core.models.User.Role (TextChoices) — frontend/src/.../DashboardLayout.tsx
// affiche `user.role_display` tel quel dans la carte utilisateur du menu latéral.
const CAS: { compte: keyof typeof COMPTES; libelleAttendu: string; itemsAttendus: RegExp[]; itemsInterdits: RegExp[] }[] = [
  {
    compte: 'admin',
    libelleAttendu: 'Administrateur Système',
    itemsAttendus: [/tableau de bord/i, /succursales/i, /personnel/i, /configuration/i, /registre blockchain/i],
    itemsInterdits: [],
  },
  {
    compte: 'direction',
    libelleAttendu: 'Direction Générale',
    itemsAttendus: [/tableau de bord/i, /états financiers/i, /registre blockchain/i, /clôture & caisse/i],
    itemsInterdits: [],
  },
  {
    compte: 'comptable',
    libelleAttendu: 'Comptable',
    // COMPTABLE fait partie du niveau Siège (HQ-level access) au même titre que
    // ADMIN/DIRECTION/superuser — backend/core/models.py, propriétés
    // is_headquarters/can_access_all_nodes (~l.242-248). Il doit donc pouvoir
    // consulter le Registre Blockchain pour auditer l'intégrité du Livre de
    // Caisse (CLAUDE.md §5.5). Décision du coordinateur (2026-10-30), voir
    // docs/qa/REGISTRE_BUGS.md.
    itemsAttendus: [/tableau de bord/i, /commissions cm/i, /clôture & caisse/i, /états financiers/i, /registre blockchain/i],
    itemsInterdits: [/succursales/i, /personnel/i, /configuration/i],
  },
  {
    compte: 'gerantK1',
    libelleAttendu: 'Gérant de Boulangerie',
    itemsAttendus: [/gestion clientèle/i, /production & stocks/i, /clôture & caisse/i, /facturation/i],
    itemsInterdits: [/commissions cm/i, /états financiers/i, /registre blockchain/i, /personnel/i],
  },
  {
    compte: 'facturierK1',
    libelleAttendu: 'Facturier',
    itemsAttendus: [/gestion clientèle/i, /facturation/i],
    itemsInterdits: [/production & stocks/i, /clôture & caisse/i, /registre blockchain/i, /personnel/i],
  },
  {
    compte: 'livreurK1',
    libelleAttendu: 'Livreur',
    itemsAttendus: [],
    itemsInterdits: [/production & stocks/i, /clôture & caisse/i, /registre blockchain/i, /personnel/i, /gestion clientèle/i],
  },
];

for (const cas of CAS) {
  test(`connexion ${cas.compte} → tableau de bord adapté au rôle, puis déconnexion`, async ({ page }) => {
    const compte = COMPTES[cas.compte];
    await seConnecter(page, compte.username, PASSWORD);

    await expect(page.getByText(cas.libelleAttendu, { exact: true })).toBeVisible();

    for (const item of cas.itemsAttendus) {
      await expect(page.getByRole('link', { name: item })).toBeVisible();
    }
    for (const item of cas.itemsInterdits) {
      await expect(page.getByRole('link', { name: item })).toHaveCount(0);
    }

    await seDeconnecter(page);
    await expect(page.getByPlaceholder('Ex: pierre')).toBeVisible();
  });
}

test('un identifiant/mot de passe invalide affiche une erreur et ne connecte pas', async ({ page }) => {
  await page.goto('/login');
  await page.getByPlaceholder('Ex: pierre').fill('demo_facturier_k1_e2e');
  await page.getByPlaceholder('••••••••').fill('mauvais-mot-de-passe');
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByText(/erreur|incorrect|invalide/i)).toBeVisible({ timeout: 10_000 });
});
