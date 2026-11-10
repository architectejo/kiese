# Rapport dev-frontend — 2026-11-10 — BUG-151

## Ticket traité

**BUG-151** — [frontend] Confirmer manuellement le reste d'hier d'une AUTRE équipe, depuis
« Production & Stocks » (remarque.md, après l.406). Détail complet, correctifs, fichiers et
procédure de vérification manuelle : voir la fiche dans `docs/qa/REGISTRE_BUGS.md`.

Numérotation : au moment de commencer, `BUG-150` était déjà pris (réservé par `dev-backend` pour un
écran Configuration sans rapport, dans la fiche BUG-149). Aucune collision avec `BUG-151` constatée
— pris directement, pas de renumérotation nécessaire.

## Contexte technique (rappel)

Depuis BUG-139/140/141, une seule confirmation (équipe du créneau d'ouverture) suffit à faire
disparaître la boîte modale automatique « Stock de départ du jour »
(`OpeningStockConfirmationModal.tsx`, montée une seule fois par `DashboardLayout.tsx`). C'est le
comportement voulu pour l'affichage automatique, mais il ne restait plus aucun moyen manuel de
confirmer le reste d'hier de l'AUTRE équipe plus tard dans la journée, alors que le modèle backend
(`DailyOpeningConfirmation`, clé `[node, team, date]`) et l'endpoint existant le permettent déjà
parfaitement. Rien à modifier côté backend pour ce ticket.

## Ce qui a été fait

- `frontend/src/components/production/OpeningStockConfirmationModal.tsx` : ajout de deux props
  optionnels, `forceOpenForTeam` et `onManualClose`, qui ouvrent la boîte modale pour une équipe
  précise en mode manuel, sans toucher au comportement automatique existant quand ces props sont
  omis (non-régression totale de BUG-133 à 141).
- `frontend/src/store/openingConfirmationStore.ts` (nouveau) : petit store Zustand qui porte la
  demande manuelle entre la page `Production.tsx` (déclencheur) et `DashboardLayout.tsx` (où le
  composant modal unique est monté), sans dupliquer sa logique métier.
- `frontend/src/components/production/OpeningConfirmationManualSection.tsx` (nouveau, extrait car
  `Production.tsx` dépasse ~1000 lignes, CLAUDE.md §4) : zone affichant un bouton par équipe pas
  encore confirmée aujourd'hui (ou un message si les deux le sont déjà), avec chargement/erreur
  gérés.
- `frontend/src/components/layout/DashboardLayout.tsx` et `frontend/src/pages/dashboard/Production.tsx` :
  câblage (store ↔ modal ; montage de la nouvelle zone dans l'onglet Fournées, sous la même garde de
  rôle `GERANT`/`FACTURIER` non-HQ ; rafraîchissement via `loadData()` après confirmation réussie).

## Vérifications effectuées

- `npx tsc --noEmit` (frontend/) : propre, aucune erreur.
- `npm run build` (frontend/) : build réussi (`exit code 0`), avertissements préexistants inchangés
  (taille de chunk, minifier legacy) — aucun nouvel avertissement.
- Aucun test E2E dédié trouvé dans `e2e/` pour ce parcours précis. Étapes de vérification manuelle
  détaillées pour le testeur : voir la fiche BUG-151 dans `docs/qa/REGISTRE_BUGS.md` (7 étapes,
  couvrant 360 px / 768 px / 1440 px et la non-régression des gardes de rôle).
- Aucun fichier backend ouvert ni modifié.

## Registre

Ticket `BUG-151` créé et renseigné, statut `CORRIGÉ` (pas `VÉRIFIÉ` — seul le testeur d'origine ou
le coordinateur valide, CLAUDE.md §7 règle 3).

## Fichiers modifiés/créés

- `frontend/src/components/production/OpeningStockConfirmationModal.tsx` (modifié)
- `frontend/src/store/openingConfirmationStore.ts` (nouveau)
- `frontend/src/components/production/OpeningConfirmationManualSection.tsx` (nouveau)
- `frontend/src/components/layout/DashboardLayout.tsx` (modifié)
- `frontend/src/pages/dashboard/Production.tsx` (modifié)
- `docs/qa/REGISTRE_BUGS.md` (fiche BUG-151 ajoutée)
