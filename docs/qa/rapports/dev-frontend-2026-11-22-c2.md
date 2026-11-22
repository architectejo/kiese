# dev-frontend 2026-11-22 (c2) — BUG-388

Ticket BUG-388 : approvisionnement du stock direction (CORRIGÉ frontend).

Contrat vérifié (backend/production/views.py, ConsumableMovementViewSet) : permission `IsGerant` (ADMIN, DIRECTION, COMPTABLE, GERANT, superuser). ADMIN et DIRECTION ont `can_access_all_nodes` : `node` explicite accepté, le stock doit appartenir à ce nœud (sinon 400). Champs : `node`, `stock` (id du ConsumableStock), `movement_type=ENTRY`, `quantity` (3 décimales), `unit_price` (2 décimales, défaut 0, alimente le CUMP), `description` (255). Le serveur ne refuse donc pas ADMIN/DIRECTION. Point à noter : COMPTABLE passe la permission serveur (IsGerant) ; seul le masquage côté interface l'en empêche (le serveur n'est pas modifié, à signaler à dev-backend si on veut un 403).

Fichiers : `frontend/src/components/production/DirectionSupplyForm.tsx` (nouveau), `GlobalConsumablesSection.tsx` (rendu du formulaire pour ADMIN/DIRECTION uniquement). Aucun changement dans `services.ts` : `productionApi.stocks.list` et `movements.create` existent déjà ; l'id du stock SIEGE est retrouvé via `stocks.list({node, consumable_type})` (le serveur crée les comptes manquants à la lecture).

Comportement : quantité > 0 (virgule ou point, 3 décimales), prix vide = 0 FC, note facultative (défaut « Approvisionnement stock direction »), erreurs via `getErrorDetail`, succès + rechargement du tableau, quantités via `consumableFormat.ts`, grille `auto-fit` + champs 100 % pour 360 px.

Vérifié : `npx tsc --noEmit` 0 erreur ; `npm run build` OK (seul avertissement de taille de chunk préexistant). Non vérifié : aucun rendu navigateur, ni 360 px réel, ni e2e (non lancés ni édités).
Vérification manuelle : connecté en DIRECTION, Production > Intrants, saisir 0,25 paquet de levure + prix, valider : la ligne « Stock direction » augmente ; en COMPTABLE le formulaire est absent.
