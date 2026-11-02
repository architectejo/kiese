/**
 * Comptes de démonstration pour les parcours E2E.
 *
 * Ces comptes ont été créés via un script `manage.py shell` ponctuel
 * (données fictives, préfixe `demo_*`, cf. règle CLAUDE.md / PLAN_2026-10-22
 * §0.1), en complément de `seed_kiese` qui ne couvre pas tous les rôles
 * (pas de COMPTABLE, pas de second nœud K2). Mot de passe commun choisi
 * volontairement différent de celui de `seed_kiese` pour ne pas être confondu
 * avec un compte réel.
 *
 * Si ces comptes n'existent plus dans la base de dev (ex. base réinitialisée),
 * les recréer avec le même script avant de lancer la suite — voir le rapport
 * `docs/qa/rapports/testeur-e2e-2026-10-22.md` pour le script complet.
 */

export const PASSWORD = 'DemoE2E2026!';

export const COMPTES = {
  admin: { username: 'demo_admin_e2e', password: PASSWORD, role: 'ADMIN' },
  direction: { username: 'demo_direction_e2e', password: PASSWORD, role: 'DIRECTION' },
  comptable: { username: 'demo_comptable_e2e', password: PASSWORD, role: 'COMPTABLE' },
  gerantK1: { username: 'demo_gerant_k1_e2e', password: PASSWORD, role: 'GERANT', node: 'K1' },
  gerantK2: { username: 'demo_gerant_k2_e2e', password: PASSWORD, role: 'GERANT', node: 'K2' },
  facturierK1: { username: 'demo_facturier_k1_e2e', password: PASSWORD, role: 'FACTURIER', node: 'K1' },
  facturierK2: { username: 'demo_facturier_k2_e2e', password: PASSWORD, role: 'FACTURIER', node: 'K2' },
  livreurK1: { username: 'demo_livreur_k1_e2e', password: PASSWORD, role: 'LIVREUR', node: 'K1' },
} as const;

/** Client fictif pré-seedé à K1 pour le test de recherche inter-boulangeries. */
export const CLIENT_CROSS_NODE = {
  code: 'K1-0078',
  nomComplet: 'CrossNodeE2E DEMO',
  nomPartiel: 'CrossNodeE2E',
};

/**
 * Client fictif pré-seedé à K1, dette = plafond (50 000 FC), pour le test de
 * blocage. Ne jamais le réutiliser pour un remboursement (voir
 * CLIENT_POUR_REMBOURSEMENT) : un remboursement réel réduirait durablement sa
 * dette en base entre deux exécutions de la suite et casserait ce test.
 */
export const CLIENT_AU_PLAFOND = {
  code: 'K1-0079',
  nomPartiel: 'PlafondE2E',
};

/** Client fictif distinct, dédié au test de remboursement (dette initiale 20 000 FC). */
export const CLIENT_POUR_REMBOURSEMENT = {
  code: 'K1-0083',
  nomPartiel: 'RemboursementE2E',
};
