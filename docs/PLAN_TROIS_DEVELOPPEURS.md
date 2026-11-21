# Plan de travail à trois développeurs — ETS. KIESE

Établi le 2026-11-21. Complète [PLAN_DEUX_DEVELOPPEURS.md](PLAN_DEUX_DEVELOPPEURS.md) (les modules et règles de A et B restent valables) en ajoutant un **Développeur C**.

## 1. Rôles

| | **A** — `dev-a` | **B** — `dev-b` | **C** — `dev-c` |
|---|---|---|---|
| Thème | Cœur métier : production, ventes, trésorerie, finance, blockchain | Plateforme **sans desktop** : clients, commissions, core, sync, chat, e2e, cloud, docs | **Vérification** : tous les tickets `CORRIGÉ` (modules A et B), matrice de permissions |
| Tickets | `BUG-3NN` (jusqu'à 357 à ce jour) | `BUG-4NN` | **`BUG-5NN`** (à partir de 500) |
| Rapports | `…-a.md` | `…-b.md` | `…-c.md` |

### Décision du 2026-11-21 : le Desktop est gelé
**Plus aucun des trois développeurs ne travaille sur `desktop/`** (Electron, installeur, sauvegardes, impression silencieuse). Le périmètre est limité au **backend** (Django/DRF) et au **frontend** (React). Conséquences :
- Les tâches desktop de B (B4 : installeur, premier lancement, sauvegardes, mises à jour ; `packaging-desktop`, `testeur-installation`, `testeur-materiel`) sont suspendues, ainsi que les tickets desktop encore ouverts (BUG-073 à 077, 081, 404, 408, 409…). On ne les vérifie ni ne les corrige pour l'instant ; leur statut dans le registre reste tel quel.
- Aucun test, aucun rapport et aucun commit ne touche `desktop/`. Si une correction backend ou frontend a un effet côté desktop (ex. `ThermalReceipt.tsx`, `desktop_server.py`), on le note dans le ticket sans modifier `desktop/`.
- Le serveur reste Waitress (décision du 2026-11-21) ; le cloud (B7) n'est pas du desktop et reste dans le plan.

### Réorientation de B (2026-11-21) — pour finir vite
Le desktop étant gelé, B se concentre sur des **corrections** dans ses modules et sur le cloud ; **toutes les vérifications** passent à C (un testeur indépendant du développeur, et B n'attend plus personne).

| Ordre | Tâche de B | Tickets / contenu | Agents |
|---|---|---|---|
| B-1 | Sync : validation des quantités et types dans `_push_invoice_line` | BUG-331, 332 | `dev-backend` |
| B-2 | Pagination : `?page_size=` opérant (réglages DRF valides dans `kiese/settings.py`) | BUG-333 | `dev-backend` |
| B-3 | Test dépendant de `DJANGO_DEBUG` ; routes `/admin/*` et `/settings` gardées par `isAllowed` | BUG-401, 407 | `dev-backend`, `dev-frontend` |
| B-4 | Dette frontend sur **ses** pages : découper `Clients.tsx` et `Settings.tsx`, supprimer les `any` | BUG-011 | `relecteur-code`, `dev-frontend` |
| B-5 | E2E : réparer le scénario de production instable, étendre les parcours (POS 360 px, tablette, bureau, TV) ; préfixe `…-dev-b.spec.ts` | BUG-148 | `testeur-e2e` |
| B-6 | Cloud : VPS Linux, PostgreSQL, Waitress + Nginx, HTTPS, durcissement (JWT, limitation des tentatives de login) ; tests de charge à 8 nœuds | B7 du plan initial | `nettoyeur-securite`, `testeur-charge` |
| B-7 | Documentation (manuels par rôle, guide serveur/cloud, procès-verbal de recette) — **sans le guide d'installation desktop** | B8 du plan initial | `redacteur-documentation` |
| B-8 | Questions client en attente sur Commissions (BUG-266, 267, 268, « À CLARIFIER ») : préparer les questions et les exemples chiffrés | — | `testeur-clients-commissions` |

Quand un ticket de B passe `CORRIGÉ`, B le signale dans `COMMUNICATION_A_B.md` ; C le fait vérifier (`testeur-*` d'origine) et le passe `VÉRIFIÉ`.

### Périmètre de C
- **A5 + B9** : vérifier les tickets `CORRIGÉ` avec les agents `testeur-*` (le testeur n'est jamais le développeur du correctif).
- **B5** : rejouer la matrice de permissions et l'isolation entre boulangeries (`testeur-permissions`), et vérifier les tickets de sécurité `CORRIGÉ` de B (BUG-247 à 252, 255).
- **Dette frontend des pages de A** (`Production.tsx`, `Treasury.tsx`, `Sales.tsx`) : suppression des `any` et extraction de sous-composants, avec `relecteur-code` et `dev-frontend`, après le retour de A et en accord avec lui. Les pages de B (Clients, Settings) sont à B (B-4).
- Les modules de A et de B restent la propriété de leur développeur. C n'y corrige du code que sur ticket, ou à titre de remplacement annoncé.

### Remplacement de A (2026-11-21, absence de A)
Pendant l'absence de A, C a repris des tickets de son périmètre sur `dev-c` : BUG-402 (CUMP), vérifications BUG-173, 175, 177 (volet trésorerie), 164 (volet trésorerie), 197, 199, 076 (volet ventes), puis BUG-357, 147, 129. Au retour de A : **A fusionne `origin/dev-c` dans `dev-a`** et reprend la main ; le détail est dans `docs/COMMUNICATION_A_B.md`, message #04.

## 2. Flux Git

```
main            ← branche stable (PR uniquement)
 ├─ dev-a       ← développeur A
 ├─ dev-b       ← développeur B
 └─ dev-c       ← développeur C
```

- Chacun pousse **sa** branche uniquement ; jamais de `push --force`, jamais de push sur la branche d'un autre.
- Un lot vérifié (tests + build verts) → commit → push, au fil de l'eau.
- Pour récupérer le travail d'un autre : `git fetch origin` puis `git merge origin/dev-x` sur sa propre branche.
- Les modifications de C dans un module de A ou de B sont signalées dans `COMMUNICATION_A_B.md` pour que le propriétaire les fusionne.
- `.gitattributes` fusionne en « union » le registre et le fichier de communication : on ajoute en fin de fichier, on ne réécrit pas.

## 3. Règles inchangées
- Un seul registre : `docs/qa/REGISTRE_BUGS.md`, modifié par remplacements ciblés (relire la ligne avant de l'éditer).
- Les développeurs ne valident pas leurs propres corrections ; les testeurs ne corrigent pas le code applicatif.
- `python manage.py test` et `npm run build` passent avant de rendre la main.
- Jamais dans un commit : `.env`, `*.sqlite3`, `.venv/`, `node_modules/`, `data_kiese/`.

## 4. Environnement de développement (Windows, Python 3.14)
- `python -m venv .venv`, puis `pip install -r requirements.txt` (Pillow >= 10.4 depuis le 2026-11-21 : Pillow 10 n'a pas de wheel pour Python 3.14).
- Sans fichier `.env`, définir pour la session `DJANGO_DEBUG=True` et une clé jetable `DJANGO_SECRET_KEY`.
- Tests : `python manage.py test <app> --noinput`. **Ne pas utiliser `--parallel`** (plante sous Python 3.14 : erreur de sérialisation d'une exception). Rediriger la sortie dans un fichier et lire sa fin.
- Frontend : `npm ci`, `npx tsc --noEmit`, `npm run build` (Node 26, npm 11).
