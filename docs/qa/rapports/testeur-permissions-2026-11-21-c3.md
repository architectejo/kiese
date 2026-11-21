# Rapport testeur-permissions (Dev C) - vérification BUG-414 - 2026-11-21 (c3)

## Verdict
BUG-414 : **VÉRIFIÉ** (testeur-permissions, Dev C), avec deux réserves ouvertes en tickets distincts (BUG-516 Majeur, BUG-517 Mineur).

## Relecture du diff (bdf2b2e, `NodeViewSet.destroy`)
- Permissions inchangées : `IsDirection` (ADMIN, DIRECTION, superuser) pour destroy.
- Comptes actifs rattachés : 400 `{"detail": ...}` en français avec le nombre de comptes ; rien n'est modifié.
- `ProtectedError` : 400 français. La collecte Django lève avant toute suppression : atomique.
- `log_activity(DELETE)` appelé seulement après suppression réussie.
- Point non couvert par le correctif : `CASCADE` sur TamperAlert, BlockchainSnapshot, chat.Conversation, sync.NodeAuthToken (BUG-516) ; aucune garde SIEGE (BUG-517).

## Comptes désactivés (SET_NULL) : évaluation
Un nœud supprimé laisse ses comptes inactifs avec `node=NULL`. Ce n'est PAS un défaut recréant BUG-506 :
inactifs, ils ne se connectent pas ; la tentative de réactivation d'un tel compte (`PATCH is_active=True`) est refusée en 400
(test `test_reactivating_orphan_gerant_is_refused`, passe sans marque) ; `check_users_sans_noeud` les liste ("inactif").
Choix du dev confirmé. Piste facultative : rien à corriger.

## Tests écrits : `backend/core/tests/test_verif_bug414_c.py` (22 tests)
- Rôles : ADMIN 204, DIRECTION 204, COMPTABLE/GERANT/FACTURIER/LIVREUR 403, anonyme 401/403 ; gérant ne supprime pas son propre nœud.
- Comptes actifs : 400, comptes inchangés, pas de journal ; 1 actif parmi inactifs bloque ; que des inactifs : 204, comptes orphelins inactifs, détectés par `check_users_sans_noeud` ; comptes siège non comptés.
- PROTECT : client, facture, session de production, stock de pains -> 400 français, nœud conservé, pas de journal ; atomicité (alerte conservée quand le client bloque).
- ID inexistant, `abc`, UUID forgé, -1, 0 : 404 ; double suppression : 204 puis 404, un seul journal ; journal avec utilisateur et code du nœud ; autre nœud intact ; commande de contrôle propre après suppression.
- `@expectedFailure` : alerte de falsification effacée (BUG-516), SIEGE supprimable (BUG-517).

## Résultats
- `core.tests.test_verif_bug414_c` : 22 tests, OK (expected failures=2).
- Suite `core` complète : 479 tests, OK (skipped=3, expected failures=8), 332 s.
- Non testé : échec de `log_activity` après suppression (hors transaction du test : la suppression serait déjà validée si `ATOMIC_REQUESTS` est désactivé) ; risque faible.

## Tickets ouverts
- BUG-516 [Majeur] : `DELETE` d'un nœud sans PROTECT efface en CASCADE les alertes de falsification (et snapshots, chats, jeton de sync).
- BUG-517 [Mineur] : le nœud technique SIEGE est supprimable.

Numérotation : le registre s'arrêtait à BUG-511 ; 516 et 517 utilisés conformément à la consigne (>= 516).
Aucun code applicatif modifié.
