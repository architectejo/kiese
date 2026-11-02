# Rapport — nettoyeur-securite — 2026-10-22

Périmètre traité (phase 0, voir `docs/qa/PLAN_2026-10-22.md`) : BUG-005, BUG-006, BUG-007, BUG-009, BUG-010.
Aucun autre fichier applicatif n'a été modifié.

## 1. Résumé des changements

| Ticket | Fichier(s) | Changement |
|---|---|---|
| BUG-005 | `backend/kiese/settings.py` | `DEBUG` par défaut `False` ; garde-fou qui refuse de démarrer hors DEBUG avec la clé de dev codée en dur ; bloc HTTPS complet (`SECURE_SSL_REDIRECT`, `SECURE_PROXY_SSL_HEADER`, `SECURE_HSTS_SECONDS`/`INCLUDE_SUBDOMAINS`/`PRELOAD`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS`) actif uniquement quand `DEBUG=False`. |
| BUG-006 | `backend/kiese/settings.py`, `backend/core/views.py` | `ACCESS_TOKEN_LIFETIME` 12h → 30 min (configurable) ; `BLACKLIST_AFTER_ROTATION=True` ; ajout de `rest_framework_simplejwt.token_blacklist` à `INSTALLED_APPS` (migrations appliquées sur `backend/db.sqlite3`) ; throttling DRF (`ScopedRateThrottle`, scope `login`, 5/min par défaut) posé sur `login_view`. |
| BUG-007 | `backend/.env.example` (nouveau) | Toutes les variables documentées avec valeurs factices ; explication de la confusion `.env` (venv) vs `.env` (config) et procédure de renommage. |
| BUG-009 | `backend/kiese/settings.py` | Réenregistré en UTF-8 **sans BOM** (un BOM avait été introduit par l'outil d'écriture — retiré explicitement et vérifié par lecture binaire) ; toutes les séquences `â€”`/`Ã¨`/`Ã©` corrigées en caractères français corrects. |
| BUG-010 | `secure.html` | Contenu vérifié (JS de test cassé, faux « blockchain integrity check », aucune information sensible) puis fichier supprimé. |

Le registre `docs/qa/REGISTRE_BUGS.md` a été mis à jour : les 5 tickets sont passés à **CORRIGÉ** (jamais VÉRIFIÉ — c'est le rôle de `testeur-permissions` / coordinateur), avec une fiche détaillée (cause, fichiers modifiés, test de non-régression, impact) pour chacun.

## 2. Vérifications effectuées

- `manage.py check` (DEBUG=True, dev) : **0 problème**.
- `manage.py check --deploy` simulé avec un `.env` de production factice (`DJANGO_DEBUG=False`, `DJANGO_SECRET_KEY` aléatoire fort, `DJANGO_ALLOWED_HOSTS`/`CORS_ALLOWED_ORIGINS` renseignés) : **0 avertissement `security.*`**. Avec une clé faible on retrouve uniquement `security.W009` (qualité de la clé elle-même), ce qui est normal et dépendra de la vraie clé générée par le client.
- Garde-fou SECRET_KEY : `DJANGO_DEBUG=False` sans `DJANGO_SECRET_KEY` → `ImproperlyConfigured` levée immédiatement, confirmé en exécutant `manage.py check`.
- `manage.py makemigrations --check --dry-run` : **drift pré-existant et sans rapport avec mon périmètre** sur `production`, `clients`, `treasury` (changements de type `id`/`unique_together` probablement liés à une version de Django différente de celle utilisée lors des dernières migrations). Aucun drift sur `core` (l'app que j'ai modifiée). Je n'ai pas touché aux modèles ni créé de migration — à signaler au coordinateur/`dev-backend` comme item séparé.
- `manage.py test` : 0 test (BUG-008, hors périmètre, toujours ouvert) — la commande s'exécute sans erreur.
- `npm run build` (frontend) : **passe**. Avertissement pré-existant de taille de chunk (> 500 kB), sans rapport avec cette itération.
- Migrations `token_blacklist` appliquées réellement sur `backend/db.sqlite3` (`manage.py migrate token_blacklist`) : ajout de tables uniquement (`OutstandingToken`, `BlacklistedToken`), **aucune donnée existante modifiée ou supprimée**. C'est la seule écriture faite sur la base réelle pendant cette itération ; elle est nécessaire pour que le logout (déjà codé correctement dans `core/views.py::logout_view`) puisse effectivement blacklister les tokens dès maintenant. Rien d'autre n'a été ajouté/laissé en base — pas de compte « DEMO » créé par cet agent (rien à nettoyer de ce côté).

## 3. Correction de l'hypothèse initiale sur `.env.production`

Le backlog initial (CLAUDE.md §6 point 7) supposait que `backend/.env.production` « contient une clé à considérer comme exposée ». Après lecture : ce fichier est en réalité un **gabarit** —
```
DJANGO_SECRET_KEY=REMPLACEZ-PAR-UNE-CLE-ALEATOIRE-LONGUE-ET-SECRETE-ICI
DJANGO_DEBUG=False
```
Il ne contient aucun secret réel. Je signale cette correction d'hypothèse au coordinateur plutôt que de la considérer close sans vérification : **reste à confirmer côté client** si un vrai `.env` (avec une vraie clé) existe directement sur le serveur de production (etskiese.com, hors de portée de cet agent) et, si oui, si cette clé a pu fuiter par un autre canal (sauvegarde, capture d'écran, dépôt précédent, etc.). Aucun dépôt git n'existe à ce stade (`git status` → « not a git repository »), donc aucun historique à nettoyer pour l'instant — mais dès l'initialisation du dépôt, il faudra s'assurer que `backend/.env`, `backend/.env.production` (si une vraie clé y est un jour mise) et `backend/.env/` (le venv) ne sont jamais ajoutés au suivi.

## 4. `backend/.env` est un venv — action humaine requise (BUG-007)

Confirmé : `backend/.env/` contient `Lib/`, `Scripts/`, `pyvenv.cfg` et les paquets installés (Django, DRF, openpyxl...). C'est un venv Windows, pas un fichier de config. Tant qu'il existe sous ce nom, impossible de créer un vrai fichier `.env` au même endroit (conflit de nom dossier/fichier) — c'est pourquoi je n'ai pas pu tester `manage.py` avec un vrai fichier `.env` local ; j'ai validé tous les scénarios avec des variables d'environnement shell équivalentes (résultats identiques, `load_dotenv` ne fait qu'ajouter ces mêmes variables au `os.environ`).

**Action humaine à faire avant la suite du projet** :
1. Renommer `backend/.env` → `backend/.venv` (ou le supprimer et recréer un venv propre : `python -m venv .venv`).
2. Copier `backend/.env.example` → `backend/.env` et renseigner les vraies valeurs (surtout `DJANGO_SECRET_KEY`).
3. `pip install -r backend/requirements.txt` dans le nouveau `.venv`.

Je n'ai supprimé aucun fichier/dossier de données pendant cette intervention. Pour mémoire (à faire par un humain, pas par un agent, avant toute mise en dépôt git) :
- `backend/db.sqlite3` et `backend/db.sqlite3.bak-pre-migrations` — données réelles, à ne jamais committer.
- `data_kiese/` (racine du dépôt) — données réelles clients/caisse, à ne jamais committer ni copier dans des fixtures de test.
- Tout fichier `.zip` d'archive éventuel à la racine.
- `backend/.env/` (le venv, une fois renommé en `.venv`, de toute façon à exclure).

## 5. Secrets à faire tourner par le client avant mise en production (sans affichage en clair)

- **`SECRET_KEY` Django de production réellement utilisée sur etskiese.com** : à vérifier/générer/roter directement sur le serveur de production. Je n'y ai pas accès et je n'ai rien changé côté infra réelle — point d'arrêt humain explicite demandé par le plan, respecté.
- **Mots de passe des comptes `seed_kiese`** (`admin2026`, `direction2026`, `comptable2026`, mot de passe des gérants généré par défaut dans `backend/seed_from_excel.py`) : ce sont des identifiants de démonstration en dur dans le script de seed, pas des secrets de production, mais ils sont prévisibles — à changer pour tout compte réellement utilisé en production.
- Aucun autre secret en dur trouvé lors de la recherche (`grep` ciblé sur `SECRET_KEY=`, `password=`, `API_KEY=`, hors le venv `backend/.env/` qui est du code tiers).

## 6. JWT dans `localStorage` — recommandation sans changement de code frontend

Confirmé dans `frontend/src/store/authStore.ts` : `access`/`refresh` sont stockés dans `localStorage` (clés `kiese_access_token`, `kiese_refresh_token`), lus/écrits à plusieurs endroits (login, refresh automatique, logout). C'est un vecteur de vol de token en cas de XSS (n'importe quel script injecté peut lire `localStorage` et exfiltrer les deux tokens).

Comme demandé, je n'ai **pas** réécrit ce flux (changement structurant : cookies httpOnly impliquent CSRF token, intercepteur axios différent, endpoint de refresh qui pose le cookie côté serveur, gestion du logout multi-onglets). Recommandation pour une itération dédiée (`dev-backend` + `dev-frontend` ensemble, avec tests e2e) :
1. Access token encore en mémoire (store Zustand, pas `localStorage`) pour réduire la fenêtre d'exposition.
2. Refresh token déplacé vers un cookie `httpOnly`, `Secure`, `SameSite=Strict` posé par le backend (nécessite un endpoint de refresh qui lit le cookie plutôt que le body).
3. Protection CSRF classique Django (déjà partiellement en place via `CsrfViewMiddleware`) à étendre à cet endpoint.

Avec la réduction de `ACCESS_TOKEN_LIFETIME` à 30 minutes faite dans cette itération, l'impact d'un vol de token via XSS est déjà réduit (fenêtre de 12h → 30 min), même sans ce changement structurant.

## 7. Audit rapide — endpoints `AllowAny`

Recherche exhaustive (`grep AllowAny` sur `backend/`, hors venv) : exactement 3 usages, tous justifiés et conformes à l'attendu du plan :
- `core/views.py::login_view` — endpoint public par nature (formulaire de connexion), désormais protégé par throttling (BUG-006).
- `core/views.py::ConfigView.get_permissions` (méthode GET uniquement) — utilisé par la vérification « en ligne / hors ligne » et par la vitrine publique ; écriture (PUT/PATCH) reste réservée à `IsDirection`.
- `core/views.py::BreadPriceViewSet.get_permissions` (actions `list`/`retrieve` uniquement) — grille de prix affichée sur la page vitrine publique ; création/modification/suppression réservées à `IsDirection`.

Aucun autre endpoint `AllowAny` trouvé dans le code applicatif. Correspond exactement à l'attendu du plan (login, config GET, bread-prices list/retrieve).

## 8. Points pour le coordinateur (contradictions / découvertes, pas tranchés seul)

- L'hypothèse « `.env.production` contient une clé exposée » (CLAUDE.md §6 point 7) ne se vérifie pas sur le fichier présent dans le dépôt : c'est un gabarit. À confirmer côté client pour le vrai serveur de production (voir §3).
- Drift de migrations pré-existant (`production`, `clients`, `treasury`) détecté par `makemigrations --check --dry-run`, sans rapport avec mon périmètre (je n'ai touché aucun modèle). Signalé ici pour que `dev-backend` ou `relecteur-code` investigue — potentiellement lié à une différence de version de Django entre l'environnement qui a généré les migrations existantes et celui utilisé maintenant (Django 5.0 vs 5.x plus récent dans la contrainte `>=5.0,<6.0`).
- Le dépôt n'est pas (encore) un repository git (`git status` → erreur « not a git repository »). Les règles d'hygiène `.gitignore`/`git rm --cached` de la mission initiale ne s'appliquent donc pas encore littéralement ; je recommande que ce soit fait dès l'initialisation du dépôt (hors périmètre strict de cette itération, qui portait uniquement sur BUG-005/006/007/009/010).
- Throttling de login validé par lecture de code et par la présence confirmée de `login_view.cls.throttle_scope = 'login'` + `DEFAULT_THROTTLE_RATES`. Je n'ai pas fait de test automatisé (par construction, ce n'est pas mon rôle de me valider moi-même) — à `testeur-permissions` d'écrire un test qui envoie 6 logins erronés en moins d'une minute et vérifie le HTTP 429 sur le 6e, ainsi qu'un test qui vérifie qu'un refresh token blacklisté après logout ne permet plus de rafraîchir.

## 9. Ce qui reste dans `backend/db.sqlite3` après cette session

Uniquement les nouvelles tables vides `token_blacklist_outstandingtoken` et `token_blacklist_blacklistedtoken` (migration additive). Aucune donnée de démonstration « DEMO »/« TEST » n'a été créée par cet agent — rien à nettoyer, rien à signaler au coordinateur sur ce point.

## 10. Fichiers modifiés/ajoutés/supprimés

- Modifiés : `D:\Projects\kiesse\backend\kiese\settings.py`, `D:\Projects\kiesse\backend\core\views.py`
- Ajoutés : `D:\Projects\kiesse\backend\.env.example`
- Supprimés : `D:\Projects\kiesse\secure.html`
- Registre mis à jour : `D:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (BUG-005/006/007/009/010 → CORRIGÉ, fiches détaillées ajoutées)
- Base réelle modifiée (additif uniquement) : `D:\Projects\kiesse\backend\db.sqlite3` (migrations `token_blacklist`)

## 11. Critère de fin

- `manage.py check` : OK (0 problème).
- `manage.py check --deploy` avec `.env` de production simulé : OK (0 avertissement `security.*`).
- `manage.py test` : OK (0 test — BUG-008 toujours ouvert, hors périmètre).
- `npm run build` : OK.
- `manage.py makemigrations --check --dry-run` : drift pré-existant hors périmètre (voir §8), rien de nouveau introduit par ce travail.
