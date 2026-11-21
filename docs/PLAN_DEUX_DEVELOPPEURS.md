# Plan de travail à deux développeurs — ETS. KIESE

Établi le 2026-11-20 à partir de l'état du dépôt (v1.0.0, 28 commits) et de `docs/qa/REGISTRE_BUGS.md`.

## 1. Où en est le projet

- Registre : ~204 tickets `VÉRIFIÉ`, ~39 `CORRIGÉ` (à vérifier par un testeur), **9 `OUVERT`** : BUG-161, 176, 179, 021, 129, 146, 147, 148, 228, 278.
- La synchronisation (`backend/sync`, `docs/architecture/SYNC.md`), le desktop (`desktop/`) et la messagerie existent déjà.
- Reste à faire : fermer les tickets ouverts, vérifier les `CORRIGÉ`, refonte comptable (`docs/qa/ECART_CADRE_COMPTABLE.md`, à valider avec le client), emballage/installation desktop, durcissement et hébergement cloud, charge, matériel, documentation, pilote et recette.
- ⚠️ `backend/db.sqlite3` est **suivi par Git** (données réelles) alors que CLAUDE.md l'interdit : à traiter en premier (voir tâche B0).

## 2. Principe de découpage

Découpage **vertical par module** (backend + frontend d'un même module chez le même développeur) pour éviter qu'un développeur attende l'API de l'autre. Les fichiers partagés sont réduits à quelques règles (section 4).

| | **Développeur A** (cette machine) — branche `dev-a` | **Développeur B** — branche `dev-b` |
|---|---|---|
| Thème | **Cœur métier : production, ventes, trésorerie, finance** | **Plateforme : clients, sync, desktop, sécurité, QA, docs** |
| Modules (backend + page React) | `production/`, `sales/`, `treasury/`, `finance/`, `blockchain/` ; pages Production, ClotureJournaliere, Sales, Treasury, Finance, Blockchain | `clients/`, `commissions/`, `core/`, `sync/`, `chat/` ; pages Clients, Commissions, Users, Settings, Administration, Nodes, Dashboard, Activities, vitrine ; `desktop/`, `e2e/` |

## 3. Tâches

### Développeur A — cœur métier
| Ordre | Tâche | Tickets | Agents |
|---|---|---|---|
| A1 | Rotation d'équipes 24 h : terminer la conception puis fermer | BUG-161, 278 | `coordinateur` (conception), `dev-backend`, `dev-frontend`, `testeur-production` |
| A2 | Consommables : sortie avant entrée, stock inexistant | BUG-147 (et BUG-146 côté modèle consommable, à coordonner avec B) | `dev-backend`, `testeur-production` |
| A3 | Trésorerie : permissions/filtres des viewsets, facture `RG` sur vacation rapportée | BUG-176, 179 | `dev-backend`, `testeur-tresorerie`, `ingenieur-blockchain` |
| A4 | Ventes : case « vente sans commission 25 % » ; erreur création fournée | BUG-021, 129 | `dev-backend`, `dev-frontend`, `testeur-ventes` |
| A5 | Vérifier les tickets `CORRIGÉ` des modules A (BUG-163/164/170–175, 177, 185–199…) | — | testeurs d'origine |
| A6 | Refonte finance selon le cadre comptable (après validation et chiffrage client, Q-003) | `ECART_CADRE_COMPTABLE.md` | `auditeur-comptable`, `dev-backend`, `dev-frontend` |

### Développeur B — plateforme
| Ordre | Tâche | Tickets | Agents |
|---|---|---|---|
| B0 | **Hygiène du dépôt** : retirer `backend/db.sqlite3` de l'index (`git rm --cached`), changer clés et mots de passe, vérifier `.gitignore` | BUG-005…010 (relecture) | `nettoyeur-securite` |
| B1 | Sync : sortie avant entrée de consommable (côté application des événements), reprise après coupure | BUG-146 | `architecte-sync`, `testeur-charge` |
| B2 | Données réelles : double encodage des prénoms | BUG-228 | `dev-backend` |
| B3 | E2E : réparer et étendre les parcours (4 tailles d'écran, POS 360 px) | BUG-148 | `testeur-e2e` |
| B4 | Desktop : build installeur, premier lancement, sauvegardes, mises à jour | `DESKTOP.md` D1–D8 | `packaging-desktop`, `testeur-installation`, `testeur-materiel` |
| B5 | Permissions et isolation : rejouer la matrice après les changements de A | `MATRICE_PERMISSIONS.md` | `testeur-permissions` |
| B6 | Dette technique : découper Clients.tsx et Settings.tsx, supprimer les `any` | BUG-011 | `relecteur-code`, `dev-frontend` |
| B7 | Cloud : VPS Linux, PostgreSQL, Waitress + Nginx, HTTPS (décision du 2026-11-21 : Waitress partout, pas de Gunicorn) ; tests de charge 8 nœuds | — | `nettoyeur-securite`, `testeur-charge` |
| B8 | Documentation, manuels par rôle, procès-verbal de recette | — | `redacteur-documentation` |
| B9 | Vérifier les tickets `CORRIGÉ` des modules B | — | testeurs d'origine |

**Ordre de démarrage de B** : B0 d'abord (avant le premier push), puis B1/B2/B3 en parallèle de A1–A3. B4 et B7 sont les plus longs : à lancer tôt.

Équilibre : A porte la logique métier la plus délicate (rotation, trésorerie, finance), B porte le volume d'infrastructure et de vérification.

## 4. Règles pour ne pas se marcher dessus

1. **Propriété des fichiers** : chacun ne modifie que ses modules (section 2). Besoin d'un changement chez l'autre → ticket `BUG-NNN` assigné à l'autre, ou changement minimal prévenu par message.
2. **Migrations Django** : chaque développeur ne crée des migrations que dans ses apps. Si une app de l'autre doit changer, le lui demander. Aucune migration appliquée ne se modifie.
3. **Fichiers partagés** (`frontend/src/api/services.ts`, `core/`, `CLAUDE.md`, `package-lock.json`) : petits commits, fréquents, ajouts en fin de bloc ; pull avant de les toucher.
4. **Numérotation des tickets** : A utilise `BUG-3NN` (à partir de 330), B utilise `BUG-4NN`. `.gitattributes` fusionne le registre en « union » ; le `gestionnaire-git` contrôle les doublons.
5. **Rapports d'agents** : `docs/qa/rapports/<agent>-<date>-<dev>.md` (suffixe `a` ou `b`).
6. **Données** : jamais de `db.sqlite3`, `.env`, `data_kiese/` dans un commit.

## 5. Flux Git

```
main            ← branche stable (PR uniquement)
 ├─ dev-a       ← développeur A
 └─ dev-b       ← développeur B
```

Mise en place (une fois, par chacun) :
```bash
git fetch origin
git switch -c dev-a        # ou dev-b
git push -u origin dev-a
```

Rythme :
- Chaque lot vérifié (tests + build verts) → commit → push de **sa** branche (comme `feedback_push_regulier`).
- **Au moins deux fois par jour et avant de commencer une nouvelle tâche** : lancer l'agent `gestionnaire-git` (« mets ma branche à jour depuis main et l'autre branche »).
- Fin de lot : PR `dev-x` → `main`, relue par l'autre développeur, fusion après tests verts ; puis les deux se re-synchronisent.
- Règle d'or : on ne pousse jamais sur la branche de l'autre ; pas de `push --force`.

## 6. Utilisation avec Claude Code

Chaque développeur ouvre Claude Code à la racine du dépôt sur sa branche et commence par :

- A : « Utilise l'agent coordinateur pour planifier mes tâches A1 à A6 de `docs/PLAN_DEUX_DEVELOPPEURS.md`. »
- B : « Utilise l'agent coordinateur pour planifier mes tâches B0 à B9 de `docs/PLAN_DEUX_DEVELOPPEURS.md`. »
- Les deux : « Utilise l'agent gestionnaire-git pour mettre ma branche à jour. »

Les règles de CLAUDE.md §7 restent valables : le développeur qui corrige ne valide pas ; le testeur d'origine passe en `VÉRIFIÉ`. Avec deux humains, l'autre développeur peut déclencher la vérification croisée via les agents testeurs.

## 7. Jalons

1. Dépôt propre, deux branches poussées, premier cycle de fusion réussi (B0).
2. Zéro ticket `OUVERT` Bloquant/Majeur ; tous les `CORRIGÉ` vérifiés (A1–A5, B1–B3, B5, B9).
3. Installeur desktop testé sur machine vierge (B4) + cloud en ligne (B7).
4. Pilote d'un mois dans une boulangerie, puis recette signée (B8).
5. Refonte comptable (A6) planifiée après avenant signé.
