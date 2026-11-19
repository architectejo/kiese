# testeur-permissions — Messagerie BUG-307 (backend) — 2026-11-19

Verdict : **BUG-307 backend NON VÉRIFIÉ — reste CORRIGÉ avec réserve.** Un ticket bloquant ouvert : BUG-308.
Tests : `backend/chat/tests/test_chat_permissions.py` (29 tests : 27 OK, 2 `@expectedFailure` BUG-308). Base isolée via `DB_NAME` (scratchpad), jamais `db.sqlite3`. Code applicatif et `backend/production` non touchés.

## Résultats par exigence
| Exigence | Résultat |
|---|---|
| 401 sans jeton / jeton invalide, 9 endpoints | OK |
| 6 rôles x endpoints (liste, non-lus, annuaire, fil node, fil direction) | OK (node 403 si pas de boulangerie ; direction 403 hors siège) |
| Conversation d'autrui (GET/POST/read) : 404, absente de la liste | OK (privée, direction pour gérant/facturier/livreur, node K1 vu de K2 et du siège) |
| IDs forgés / mal formés (abc, SQLi, %00, uuid inconnu, nul) | OK : 404 partout ; `direct` : 404 (400 si soi-même) |
| Injection sender/node/conversation/participants/id/created_at/node_origin dans le corps | OK : ignorés (sender = utilisateur, `kind`/`node` du direct inchangés, 2 participants) |
| Fil direction réservé ADMIN/DIRECTION/COMPTABLE | OK ; une conversation privée avec l'admin ne donne pas accès |
| Fil boulangerie d'une autre boulangerie | OK |
| Annuaire sans donnée sensible | OK : clés exactes id, name, role, role_label, node, node_code ; recherche par email/téléphone ne renvoie rien ; inactifs exclus ; soi exclu |
| Messages non modifiables | OK : PUT/PATCH/DELETE 404/405 sur toutes les routes ; `save()` refusé |
| XSS stocké | NOTE : `<script>` renvoyé tel quel en JSON (`application/json`). Pas d'échappement serveur ; le frontend ne doit jamais utiliser `dangerouslySetInnerHTML` (à vérifier au ticket frontend). |
| Anti-flood 429 | OK, par utilisateur, non contournable en changeant de conversation |
| Longueur 2000 / vide / liste / absent | OK : 2000 accepté, 2001 et vides 400 avec `detail` |
| Pagination abusive | OK : `page_size` plafonné à 100 (valeurs négatives/non numériques ramenées au défaut) ; `page` invalide ou hors plage 404 ; ordre récent d'abord |
| Non-lus cohérents | OK : par utilisateur, liste = badge, `read` remet à 0, simple lecture ne marque pas lu, tiers ne peut pas marquer lu |
| Utilisateur désactivé | OK : JWT refusé (401) ; envoi vers un destinataire désactivé 403 |
| ActivityLog sans contenu | OK : aucune entrée chat. Remarque hors périmètre : la création paresseuse de `Config` journalise « Modification Configuration » lors du premier appel API (non liée au chat). |

## BUG-308 — Bloquant (ouvert, `docs/qa/REGISTRE_BUGS.md`)
`_my_conversation_or_404` ne vérifie que la ligne `Participant`. Les `Participant` des fils de groupe ne sont jamais retirés :
- utilisateur muté de K1 à K2 : lit toujours le fil K1 (fuite inter-nœuds) ;
- COMPTABLE rétrogradé : lit toujours le fil Direction.
Le POST est protégé (`_eligible_group_users`), pas GET messages ni `read` ni la liste. Preuve : `StaleMembership` (2 tests `@expectedFailure`, à retirer le décorateur après correction).
Correctif suggéré : exiger l'éligibilité courante pour NODE/DIRECTION dans `_my_conversation_or_404` et la liste, ou purger les `Participant` au changement de `node`/`role`.

## Autres observations (non bloquantes)
- Annuaire ouvert à tous les actifs, 500 résultats max, avec rôle et boulangerie (voulu par le ticket ; à confirmer par le client). N'importe quel utilisateur peut ouvrir une conversation privée avec n'importe quel autre.
- `_ensure_group_threads` écrit en base lors d'un GET (liste) : effet de bord acceptable.
- Les non-lus de groupe incluent les messages antérieurs à la première ouverture (documenté par dev).
- Non testé : jeton expiré spécifique au chat (même `IsAuthenticated` que le reste de l'API, couvert par la matrice permissions générale).
- Exécution : ~190 s pour 29 tests (hachage des mots de passe).

## Mise à jour : revérification de BUG-308 (même jour)
Correctif dev-backend (`_can_access`, `_accessible_participations`) revérifié sur base isolée (DB_NAME scratchpad). Les 2 `@expectedFailure` sont retirés ; classe `StaleMembershipExtra` ajoutée (5 tests) :
- muté K1 vers K2 : GET messages 404, read 404, POST 403, absent de la liste, badge 0 ; voit le fil K2 ; retour en K1 : accès rétabli ;
- COMPTABLE rétrogradé : mêmes résultats sur le fil Direction, `conversations/direction/` 403 ;
- conversations privées non affectées par un changement de rôle ou de nœud ;
- membre désactivé : 401 sur tout, les autres membres continuent d'écrire ;
- le fil d'une autre boulangerie ne réapparaît jamais après mutations.
Résultat : `manage.py test chat` = 55 tests OK (21 dev + 34 testeur).

**Verdict : BUG-308 VÉRIFIÉ ; BUG-307 (backend) VÉRIFIÉ.** Frontend non couvert (point XSS à contrôler : pas de `dangerouslySetInnerHTML`).
