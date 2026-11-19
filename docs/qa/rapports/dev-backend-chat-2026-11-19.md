# dev-backend — BUG-307 Messagerie (2026-11-19)

Statut : CORRIGÉ (backend). Non vérifié. Frontend à faire.

## Fichiers
- Nouveau : `backend/chat/` (models, serializers, views, urls, apps, `migrations/0001_initial.py`, `tests/test_chat_bug307.py`).
- Modifiés : `backend/kiese/settings.py` (INSTALLED_APPS), `backend/kiese/urls.py` (`api/chat/`).
- Aucun fichier de `production/` ni `sales/` touché.

## Modèles (tous SyncableModel : UUID, node_origin, is_synced)
- `Conversation` : `kind` (DIRECT / NODE / DIRECTION), `node`, `direct_key` unique (« uuidmin:uuidmax »), `last_message_at`. Contraintes d'unicité : un fil par boulangerie, un fil Direction.
- `Participant` : conversation, user, `last_read_at` (null = rien lu). Unique (conversation, user).
- `Message` : conversation, sender, `body` (max 2000). `save()` lève `ValueError` si le message existe déjà (non modifiable).
- Hors chaîne de hash.

## Contrat API (JWT obligatoire, 401 sinon). Erreurs : `{"detail": "..."}` en français.
| Méthode / URL | Rôle |
|---|---|
| `GET /api/chat/conversations/` | Liste (non paginée) de mes conversations. Rattache l'utilisateur à son fil boulangerie (s'il a un node) et au fil Direction (ADMIN/DIRECTION/COMPTABLE/superuser). Objet : `id, kind, node, title, last_message_at, last_message{id,conversation,sender,sender_name,is_mine,body,created_at}\|null, unread_count, other_user\|null`. Tri : dernier message d'abord. |
| `POST /api/chat/conversations/direct/` `{"user": "<uuid>"}` | Crée ou retrouve la conversation 1-à-1. 201 si créée, 200 sinon, 400 si soi-même, 404 si inconnu/inactif/UUID invalide. |
| `GET /api/chat/conversations/node/` | Fil de ma boulangerie. 403 si pas de boulangerie. |
| `GET /api/chat/conversations/direction/` | Fil Direction. 403 si rôle non siège. |
| `GET /api/chat/conversations/<id>/messages/` | Historique paginé, **plus récent d'abord**. `{count,next,previous,results[]}`, `page_size` défaut 30, max 100. |
| `POST /api/chat/conversations/<id>/messages/` `{"body": "..."}` | Envoi. 201 + message. 400 si vide / > 2000 caractères. 403 si destinataire inactif ou accès au fil perdu. 429 si anti-flood (défaut 10 messages / 30 s par utilisateur ; réglages `CHAT_FLOOD_MAX_MESSAGES`, `CHAT_FLOOD_WINDOW_SECONDS`). L'envoi marque la conversation lue pour l'expéditeur. |
| `POST /api/chat/conversations/<id>/read/` | Marque lu. `{"id","unread_count":0}`. |
| `GET /api/chat/unread-count/` | `{"unread_count": N}` total, pour le badge de l'en-tête (polling 5-10 s). |
| `GET /api/chat/users/?search=` | Annuaire des utilisateurs actifs (hors soi) : `id, name, role, role_label, node, node_code`. Ni email, ni téléphone, ni nom d'utilisateur. |

- Pas de PUT/PATCH/DELETE sur les messages (405/404).
- Conversation dont je ne suis pas participant, ID inexistant ou mal formé : **404** (pas de 403, pas de fuite).
- Pas de `log_activity` : le contenu n'est jamais journalisé (testé). Pas de `create_notification` : `SystemNotification` est globale (non adressée à un utilisateur) et révélerait l'existence de messages privés ; le compteur de non-lus joue ce rôle.
- Les fils de groupe créent les participants à l'envoi pour tous les membres éligibles actifs ; les non-lus d'un fil comptent donc les messages envoyés avant la première ouverture par un membre.

## Tests
`DB_NAME=<base isolée> python manage.py test chat` : 21 tests OK (~120 s, hachage des mots de passe). `makemigrations --check --dry-run` : aucun changement. Suite complète non lancée (autre développeur actif dans production/sales).

## Décisions à confirmer
- Fil Direction réservé aux rôles siège (ADMIN, DIRECTION, COMPTABLE).
- Un utilisateur siège n'a pas de fil boulangerie (pas de node).
- Annuaire : tous les actifs, tous rôles et boulangeries confondus (exception à l'isolation par nœud, voulue par le ticket).

## Ticket frontend à ouvrir
Icône en en-tête avec badge (`unread-count`), panneau liste + fil, sélecteur d'annuaire, polling 5-10 s, 360 px, gestion du 429. Types dans `src/api/`, appels dans `services.ts`.

## Note : BUG-308 (CORRIGÉ, non vérifié)
- Cause : l'accès aux fils NODE/DIRECTION ne reposait que sur la ligne `Participant` (jamais retirée après mutation de boulangerie ou de rôle).
- Correction (`backend/chat/views.py`) : `_can_access(conv, user)` s'appuie sur `_eligible_group_users` (éligibilité courante). Appliqué à GET/POST messages, `read` (404), liste (fils exclus) et `unread-count`/badge (`_accessible_participations`). Les fils DIRECT sont inchangés.
- Tests : les 2 `@expectedFailure` de `StaleMembership` sont retirés (aucun test supprimé). Aucun changement de schéma, de contrat d'API ni de `backend/production`.
- Statut : CORRIGÉ ; vérification réservée à testeur-permissions.
