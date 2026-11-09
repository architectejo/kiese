# Rapport dev-frontend — 2026-11-09 — BUG-137

## Ticket
BUG-137 : afficher le champ `stock_adjustments` (ajouté côté backend par BUG-136) dans la boîte
modale « stock de départ du jour » (`OpeningStockConfirmationModal.tsx`), pour donner au gérant
une confirmation visuelle que sa correction a bien ajusté `BreadStock.qty_available`.

## Cause
`productionApi.openingConfirmation.submit()` et son type de réponse `OpeningConfirmationSubmitResponse`
(`frontend/src/api/services.ts`) ne déclaraient pas le champ additif `stock_adjustments` renvoyé
par `DailyOpeningConfirmationView.post()` (`backend/production/views.py`, confirmé fait sous
BUG-136). La boîte modale ignorait donc totalement le corps de la réponse au-delà de reposer le
GET.

## Correction
- `frontend/src/api/services.ts` :
  - nouveau type `OpeningConfirmationStockAdjustment { bread_price_id, before, after, delta }`
    (quantités entières de pains, toujours ≥ 0, pas de logique de signe inversée).
  - `OpeningConfirmationSubmitResponse` déclare désormais `stock_adjustments: OpeningConfirmationStockAdjustment[]`.
  - Aucun nouvel appel HTTP direct, aucun nouveau `any`.
- `frontend/src/components/production/OpeningStockConfirmationModal.tsx` :
  - après un `submit()` réussi, si `stock_adjustments` n'est pas vide, résolution du libellé de
    chaque catégorie via `report.categories` (capturé avant que `fetchReport()` ne remplace
    `report`) et affichage d'un bandeau vert temporaire (style succès, cohérent avec le bandeau
    d'erreur existant) : « Stock [<catégorie>] ajusté de <avant> à <après>. ». Disparition
    automatique après 7 s (nettoyée au démontage et à chaque nouvelle soumission), ou à la
    fermeture manuelle de la boîte modale.
  - si `stock_adjustments` est vide/absent (validation telle que proposée, cas normal — no-op),
    aucun message : comportement inchangé.
  - cas limite traité : si la soumission confirme la dernière équipe manquante de la journée, la
    boîte modale restait auparavant ouverte uniquement tant qu'une confirmation restait à faire
    (`needsConfirmation`) et se serait démontée avant que le bandeau soit lisible. La condition
    d'ouverture et le pied de modale ont été ajustés pour laisser la boîte ouverte (bouton
    « Fermer » au lieu du formulaire de saisie devenu obsolète) le temps d'afficher le bandeau.

## Fichiers modifiés
- `frontend/src/api/services.ts`
- `frontend/src/components/production/OpeningStockConfirmationModal.tsx`

Aucun fichier backend touché (conforme à la consigne — `stock_adjustments` existe déjà côté
serveur depuis BUG-136, vérifié en lisant `backend/production/views.py` avant de typer la
réponse, pas de forme JSON devinée).

## Vérifications effectuées
- `npx tsc --noEmit` : aucune erreur.
- `npm run build` (tsc + vite build) : succès, exit code 0. Seul avertissement présent :
  taille du chunk legacy > 500 kB — préexistant, sans rapport avec ce ticket.
- Aucun test E2E dédié trouvé pour ce parcours (boîte modale « stock de départ »). Étapes de
  vérification manuelle détaillées consignées dans la fiche BUG-137 du registre, pour
  `testeur-production` :
  1. Gérant d'une boulangerie non-HQ, jour sans confirmation faite pour une équipe.
  2. Modifier la quantité proposée d'au moins une catégorie et valider.
  3. Vérifier le bandeau vert listant chaque ajustement réel, et l'absence de bandeau pour les
     catégories inchangées.
  4. Revalider sans rien changer : aucun bandeau (no-op).
  5. Si c'était la dernière équipe du jour : la boîte reste visible quelques secondes avec le
     bandeau et un bouton « Fermer » (pas de formulaire résiduel), puis se ferme normalement.
  6. Vérifier à 360 px (POS) et 768 px (tablette) : bandeau lisible, boîte modale entièrement
     visible sans défilement de page.

## Registre
Ticket **BUG-137** ouvert et passé directement à **CORRIGÉ** dans
`docs/qa/REGISTRE_BUGS.md` (section détaillée en fin de fichier + ligne dans le tableau de
suivi). Non passé à `VÉRIFIÉ` (CLAUDE.md §7 règle 3 — réservé au testeur d'origine ou au
coordinateur).

## Remarque sur le périmètre
Conformément à la consigne, aucune modification n'a été apportée en dehors de l'affichage de
`stock_adjustments` : ni `DashboardLayout.tsx`, ni le reste de la logique de
`OpeningStockConfirmationModal.tsx` (sélection d'équipe, dismiss, etc.) liée à BUG-133/134/135/136
n'a été touché, pour limiter le risque de collision avec la vérification en parallèle par
`testeur-production`.
