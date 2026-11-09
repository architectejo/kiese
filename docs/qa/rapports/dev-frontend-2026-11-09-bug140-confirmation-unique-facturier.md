# Rapport dev-frontend — 2026-11-09 — BUG-140

## Contexte

`dev-backend` a corrigé BUG-138 (accès FACTURIER à `DailyOpeningConfirmationView`) et BUG-139 (une
seule confirmation par jour suffit, pas une par équipe) côté API, et ouvert **BUG-140** pour le
volet frontend correspondant (voir
`docs/qa/rapports/dev-backend-2026-11-09-bug138-139-facturier-confirmation-unique.md` pour le
contrat complet). Mission : adapter le frontend au nouveau contrat API additif de
`GET /api/production/opening-confirmation/` (`opening_team`, `needs_confirmation`), sans toucher
au backend.

## Changements

### 1. `frontend/src/api/services.ts`

`OpeningConfirmationReport` étendu (champs additifs, aucun nouveau `any`) :

```ts
export interface OpeningConfirmationReport {
  node: string;
  date: string;
  categories: OpeningConfirmationCategory[];
  teams: Record<OpeningConfirmationTeam, OpeningConfirmationTeamState>;
  opening_team: OpeningConfirmationTeam | null;
  needs_confirmation: boolean;
}
```

### 2. `frontend/src/components/production/OpeningStockConfirmationModal.tsx`

- `needsConfirmation` ne recalcule plus rien côté client : lecture directe de
  `report.needs_confirmation` (fallback `false` si `report === null`, comportement inchangé dans
  ce cas précis — demandé explicitement par la consigne).
- Nouvelle fonction `resolveDefaultTeam(report, userTeam)` qui remplace l'appel direct à
  `pickDefaultTeam` dans `fetchReport` :
  1. Si `report.opening_team` est connu (`'A'` ou `'B'`), le propose directement — c'est la
     demande du client (remarque.md l.398 : « juste une fois au créneau d'ouverture »).
  2. Sinon (`opening_team === null`, nœud sans créneaux configurés, BUG-130/131), si l'utilisateur
     connecté a une équipe propre non confirmée (`user.team` dans `UserProfile`,
     `src/store/authStore.ts`, déjà typé `'A' | 'B' | ''`, exposé par `UserSerializer` côté
     backend — vérifié avant utilisation, pas de champ deviné), elle est proposée.
  3. Sinon, filet de sécurité **inchangé** : `pickDefaultTeam` (logique BUG-134 conservée telle
     quelle, non supprimée — reste utile pour un gérant qui doit confirmer une équipe différente,
     ex. retard/absence).
  `useAuthStore` importé pour lire `user.team`. Le sélecteur manuel A/B existant est conservé tel
  quel (toujours visible, toujours modifiable) — seule la présélection change, conformément à la
  consigne de ne pas le retirer.
- Aucune autre partie du composant n'a été modifiée : le bandeau d'ajustement de stock (BUG-137)
  et le flux de soumission (`handleSubmit`, `fetchReport`, gestion d'erreur/chargement) sont
  intacts. `fetchReport` (useCallback) dépend maintenant aussi de `userTeam` (nécessaire pour que
  `resolveDefaultTeam` utilise la valeur à jour), sans changer son déclenchement (toujours au
  montage et à chaque changement de route via `routeKey`, comme avant).

### 3. `frontend/src/components/layout/DashboardLayout.tsx`

Garde de montage de `OpeningStockConfirmationModal` étendue :

```ts
{user && (user.role === 'GERANT' || user.role === 'FACTURIER') && !user.can_access_all_nodes && (
  <OpeningStockConfirmationModal routeKey={location.pathname} />
)}
```

Un FACTURIER a toujours `can_access_all_nodes === false` dans le modèle (`core/models.py`,
confirmé par lecture du modèle `User`/`Role` et par le comportement d'`IsFacturier` déjà en place
côté backend) — condition conservée par cohérence avec le motif existant plutôt que retirée.

## Vérifications effectuées

- `npx tsc --noEmit` (frontend/) : aucune erreur.
- `npm run build` (frontend/) : build réussi (avertissements de taille de chunk préexistants, sans
  rapport avec cette correction).
- Lecture complète du composant avant modification pour ne pas régresser BUG-134 (modale) ni
  BUG-137 (bandeau d'ajustement) : confirmé que ni l'un ni l'autre n'a été touché en dehors des
  trois points ci-dessus.

Aucun test E2E dédié n'a été étendu : `e2e/tests/11-stock-depart-confirmation.spec.ts` couvre
BUG-133/134 (scénario gérant, nœud sans créneaux a priori) mais pas le scénario FACTURIER +
`opening_team` déterminé. Étapes de vérification manuelle laissées au testeur dans la fiche
BUG-140 du registre (`docs/qa/REGISTRE_BUGS.md`) :
1. Nœud avec créneaux A/B configurés, connecté FACTURIER pendant le créneau A → modale ouverte,
   équipe A présélectionnée ; après confirmation, modale fermée même sans confirmation B, et ne
   réapparaît pas en changeant de page/en se reconnectant dans la journée.
2. Même nœud, connecté GERANT pendant le créneau B → équipe B présélectionnée par défaut.
3. Nœud sans créneaux configurés, FACTURIER avec `user.team = 'B'` → B présélectionné (fallback) ;
   une seule confirmation (A ou B) suffit pour fermer la modale pour la journée.
4. Modale toujours entièrement visible sans défilement de page à 360 px (POS) — composant non
   modifié sur ce point, `maxWidth="560px"` inchangé.

## Fichiers modifiés

- `frontend/src/api/services.ts`
- `frontend/src/components/production/OpeningStockConfirmationModal.tsx`
- `frontend/src/components/layout/DashboardLayout.tsx`
- `docs/qa/REGISTRE_BUGS.md` (BUG-140 : `OUVERT` → `CORRIGÉ`, fiche détaillée complétée)

## Registre

- BUG-140 : `OUVERT` → `CORRIGÉ`. **Non** passé à `VÉRIFIÉ` (CLAUDE.md §7 règle 3 — réservé au
  testeur d'origine, `testeur-production`, ou au coordinateur).

## Points d'attention pour la suite

- BUG-133/134/135/136/138/139 restent au statut `CORRIGÉ` (non `VÉRIFIÉ`) — leur vérification
  complète dépendait de BUG-140, désormais corrigé côté frontend également.
- Aucun fichier backend n'a été ouvert ni modifié dans le cadre de cette tâche.
