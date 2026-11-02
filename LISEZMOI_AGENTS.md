# Équipe d'agents IA — Projet ETS. KIESE

Ce paquet contient la configuration pour finaliser et tester la plateforme KIESE avec Claude Code.

## Contenu

```
CLAUDE.md                          instructions générales du projet (lues automatiquement par Claude)
.claude/agents/                    les 19 agents (format sous-agents Claude Code)
docs/architecture/DESKTOP.md       architecture et plan de l'application de bureau Electron
docs/qa/REGISTRE_BUGS.md           registre unique des bugs, prérempli avec les 11 problèmes connus
docs/qa/QUESTIONS_CLIENT.md        questions à faire trancher par le client
LISEZMOI_AGENTS.md                 ce fichier
```

## Installation

Décompresser **à la racine du projet** `kiesse/` (à côté de `backend/`, `frontend/`, `cahierDesCharges.md`) :

```
kiesse/
  CLAUDE.md
  .claude/agents/*.md
  docs/...
  backend/
  frontend/
  cahierDesCharges.md
  remarque.md
  adaptes.md
  cadre_comptable.md
```

Le dossier `.claude` commence par un point : il peut être masqué dans l'explorateur de fichiers.

## Les 19 agents

| Agent | Rôle | Modifie le code ? |
|---|---|---|
| `coordinateur` | Planifie, délègue, tient le registre, décide quand un module est terminé | Non |
| `nettoyeur-securite` | Dépôt propre, secrets, réglages Django/JWT/HTTPS | Oui (config) |
| `ingenieur-blockchain` | Chaîne de hash du livre de caisse : correction et tests | Oui |
| `architecte-sync` | Conception puis code de la synchronisation hors-ligne | Oui (après validation) |
| `testeur-clients-commissions` | Clients, plafonds, caisse sociale, CM, retenues, net à payer | Tests seulement |
| `testeur-ventes` | Facturation, BP, blocage crédit, livraison, reçus | Tests seulement |
| `testeur-production` | Fournées, consommables, transferts, pains déclassés | Tests seulement |
| `testeur-tresorerie` | Rapport facturier, clôture, billets, livre de caisse | Tests seulement |
| `testeur-permissions` | Rôles, isolation entre boulangeries, authentification | Tests seulement |
| **`dev-backend`** | **Corrige les bugs backend trouvés par les testeurs** | Oui |
| **`dev-frontend`** | **Corrige les bugs d'interface trouvés par les testeurs** | Oui |
| `auditeur-comptable` | Compare les calculs aux Excel d'août 2026, vérifie les états N/N-1 | Tests seulement |
| `testeur-e2e` | Parcours complets dans le navigateur (Playwright), 4 tailles d'écran | Tests seulement |
| `testeur-charge` | 8 boulangeries en parallèle, pics, coupures, volumétrie | Scripts de charge |
| `relecteur-code` | Relit les corrections, mesure la dette technique | Non |
| `packaging-desktop` | Application Electron + Django/Waitress + installeur | Oui (`desktop/`) |
| `testeur-installation` | Installation, mises à jour, sauvegardes, coupures de courant | Non |
| `testeur-materiel` | Imprimantes thermiques, POS Android, scanner, TV | Non |
| `redacteur-documentation` | Manuels par rôle, guides d'installation, PV de recette | Non (docs) |

## Le circuit d'un bug

```
Testeur trouve un écart ──▶ BUG-NNN « OUVERT » + test qui échoue
          │
          ▼
dev-backend / dev-frontend ──▶ « EN COURS » ──▶ corrige + test ──▶ « CORRIGÉ »
          │
          ▼
relecteur-code relit le diff
          │
          ▼
Testeur d'origine relance ──▶ « VÉRIFIÉ »  (ou rouvert)
```

Règle d'or : **celui qui corrige ne valide jamais sa propre correction.**

## Comment lancer le travail dans Claude Code

Ouvrir Claude Code dans le dossier `kiesse/`, puis par exemple :

- « Utilise l'agent coordinateur pour démarrer la phase 0 et préparer le planning. »
- « Lance testeur-ventes sur le module facturation. »
- « Demande à dev-backend de traiter les tickets bloquants du registre. »
- « Demande à testeur-ventes de vérifier les tickets corrigés de son module. »
- « Utilise packaging-desktop pour réaliser l'étape D1 de DESKTOP.md. »

Astuce : le coordinateur écrit le plan dans `docs/qa/PLAN_<date>.md` ; vous dites ensuite simplement « exécute le plan du coordinateur » et la session principale lance les agents désignés.

Ordre conseillé :
1. `nettoyeur-securite`
2. `ingenieur-blockchain`, puis la conception de `architecte-sync` (à valider vous-même)
3. Les 5 testeurs de module
4. `dev-backend` et `dev-frontend`
5. Vérification par les testeurs, puis `auditeur-comptable`, `testeur-e2e`, `testeur-charge`, `relecteur-code`
6. Desktop : `packaging-desktop`, `testeur-installation`, `testeur-materiel`
7. `redacteur-documentation` et recette avec le client

## Avant de commencer

- Retirez du projet les fichiers sensibles (`backend/.env.production`, `db.sqlite3*`, `backend.zip`, `dist.zip`) et changez la clé secrète de production et les mots de passe.
- Gardez `data_kiese/` hors de tout dépôt partagé : l'auditeur comptable y accède localement uniquement.
- Les agents marqués `model: inherit` utilisent le modèle de votre session ; les autres utilisent `sonnet`. Vous pouvez modifier la ligne `model:` de chaque fichier.
