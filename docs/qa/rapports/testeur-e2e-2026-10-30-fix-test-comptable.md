# Rapport testeur-e2e — 2026-10-30 — Correction d'assertion (COMPTABLE / Registre Blockchain)

## Contexte

Une passe E2E précédente (`docs/qa/rapports/testeur-e2e-2026-10-30-passe-complete.md`) avait relevé
un échec dans `e2e/tests/02-connexion-roles.spec.ts` sans trancher : le test attendait que le rôle
COMPTABLE **ne voie pas** le lien « Registre Blockchain », alors que le backend l'autorise
explicitement pour ce rôle.

## Décision du coordinateur (reçue, non re-discutée ici)

Pas une contradiction entre documents de référence, pas un défaut applicatif. `backend/core/models.py`
(propriétés `is_headquarters` / `can_access_all_nodes`, ~l.242-248) place intentionnellement
COMPTABLE au niveau Siège (« HQ-level access »), au même titre qu'ADMIN/DIRECTION/superuser —
cohérent avec `core/permissions.py::IsHeadquarters` et avec le rôle métier d'un comptable qui doit
pouvoir auditer l'intégrité du Livre de Caisse (blockchain = chaîne de hash du Livre de Caisse,
CLAUDE.md §5.5). C'est donc le test qui portait une hypothèse obsolète/incorrecte.

## Relecture complète du test pour le rôle `comptable`

Fichier : `e2e/tests/02-connexion-roles.spec.ts`, lignes 25-30 (cas `comptable`).

Avant correction :
```ts
{
  compte: 'comptable',
  libelleAttendu: 'Comptable',
  itemsAttendus: [/tableau de bord/i, /commissions cm/i, /clôture & caisse/i, /états financiers/i],
  itemsInterdits: [/succursales/i, /personnel/i, /registre blockchain/i, /configuration/i],
},
```

Seule l'entrée `/registre blockchain/i` dans `itemsInterdits` était erronée pour ce rôle. Les autres
assertions du cas `comptable` (libellé attendu, succursales/personnel/configuration interdits,
tableau de bord / commissions CM / clôture & caisse / états financiers attendus) sont conformes au
RBAC backend et n'ont pas été modifiées. Les 5 autres cas du fichier (`admin`, `direction`, `gerantK1`,
`facturierK1`, `livreurK1`) ont également été relus intégralement : aucune autre assertion erronée
trouvée — en particulier `admin` et `direction` attendent déjà `/registre blockchain/i` dans leurs
`itemsAttendus`, et `gerantK1`/`facturierK1`/`livreurK1` l'ont bien dans leurs `itemsInterdits`, ce
qui est cohérent avec la décision ci-dessus (seuls GERANT/FACTURIER/LIVREUR doivent être exclus).

## Correctif appliqué (test uniquement, aucun code applicatif touché)

```ts
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
```

Aucun autre fichier touché (ni `backend/treasury/views.py`, ni aucun autre fichier applicatif).

## Vérification

Serveurs de dev relancés localement pour la vérification (backend Django `:8000` sans
`migrate`/`seed_kiese` — base partagée inchangée ; frontend Vite `:5173`), conformément au
commentaire d'en-tête de `e2e/playwright.config.ts`.

```
cd e2e && npx playwright test tests/02-connexion-roles.spec.ts --project=bureau
```

Résultat : **7 passed** (tous les rôles, y compris `comptable`), sur le projet `bureau` (1440×900).

```
ok 1 [bureau] connexion admin → tableau de bord adapté au rôle, puis déconnexion
ok 2 [bureau] connexion direction → tableau de bord adapté au rôle, puis déconnexion
ok 3 [bureau] connexion comptable → tableau de bord adapté au rôle, puis déconnexion
ok 4 [bureau] connexion gerantK1 → tableau de bord adapté au rôle, puis déconnexion
ok 5 [bureau] connexion facturierK1 → tableau de bord adapté au rôle, puis déconnexion
ok 6 [bureau] connexion livreurK1 → tableau de bord adapté au rôle, puis déconnexion
ok 7 un identifiant/mot de passe invalide affiche une erreur et ne connecte pas
```

## Registre

Note de résolution ajoutée dans `docs/qa/REGISTRE_BUGS.md` (à la suite du signalement initial de la
passe du 2026-10-30), précisant que le test a été corrigé suite à la décision du coordinateur et
qu'il ne s'agit pas d'un défaut applicatif. Aucun nouveau ticket `BUG-NNN` ouvert (pas d'anomalie
applicative).

## Fichiers modifiés

- `D:\Projects\kiesse\e2e\tests\02-connexion-roles.spec.ts`
- `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md`
- `D:\Projects\kiesse\docs\qa\rapports\testeur-e2e-2026-10-30-fix-test-comptable.md` (ce rapport)
