# dev-frontend : BUG-307 messagerie (2026-11-19)

Statut : volet frontend CORRIGÉ, non vérifié (jamais VÉRIFIÉ par le développeur). Backend non touché.

## Fichiers
- `frontend/src/api/services.ts` : types `ChatMessage`, `ChatUser`, `ChatConversation`, `chatApi`.
- `frontend/src/components/chat/` : `ChatButton.tsx` (icône + badge, sondage 8 s, pause si onglet masqué), `ChatPanel.tsx` (liste, raccourcis Ma boulangerie / Direction masqués si 403), `MessageThread.tsx`, `NewConversation.tsx`, `chatUtils.ts`.
- `frontend/src/components/layout/DashboardLayout.tsx` : `<ChatButton />` dans l'en-tête.
- `frontend/src/styles/index.css` : classes `.chat-*` (tiroir 420 px, plein écran <= 768 px, 520 px >= 1600 px).

## Comportement
- Fil : 30 messages par page, plus récents en bas, « Voir plus » charge les plus anciens sans saut de défilement ; sondage 8 s de la page 1 fusionnée par id ; marquage lu à l'ouverture et à l'arrivée d'un message reçu ; défilement automatique en bas si l'utilisateur y est.
- Envoi : Entrée envoie, Maj+Entrée saute une ligne ; compteur x / 2 000, envoi bloqué au-delà ; 429 : « Vous envoyez trop de messages à la suite… » ; autres erreurs : `detail` de l'API.
- États chargement, erreur (role=alert) et vide sur liste, fil et annuaire. Échap ferme ; focus rendu au bouton ; boutons >= 44 px.
- Aucun message en localStorage (état React uniquement).

## Vérification manuelle
1. Deux comptes (2 navigateurs) : A écrit à B via « Nouvelle » ; B voit le badge <= 8 s, ouvre : badge retombe.
2. Gérant : « Ma boulangerie » visible, « Direction » absent ; Direction : l'inverse selon rôle.
3. > 30 messages : « Voir plus ». 11 envois rapides : message 429 en français. 2001 caractères : bouton désactivé.
4. 360 px : panneau plein écran, aucun débordement ; 768 et 1440 px : tiroir.
5. Onglet masqué : plus d'appels `unread-count` (onglet Réseau).

## Limites
Non testé au navigateur par moi (pas d'E2E existant pour la messagerie) ; `npx tsc --noEmit` sans erreur (sortie vide dans la commande qui a précédé le build) ; `npm run build` OK (3 min 22 s, seul avertissement : taille des chunks > 500 kB, préexistant).
