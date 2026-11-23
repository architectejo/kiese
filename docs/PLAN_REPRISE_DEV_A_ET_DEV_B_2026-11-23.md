# Plan de reprise : dev-a et dev-b (2026-11-23)

Ce plan répartit le travail restant entre **dev-a** (qui reprend du service) et **dev-b**.
Il s'appuie sur `docs/PLAN_TESTS_CORRECTIONS_A_B_C.md` (méthode et règle de sortie, inchangées), `docs/COMMUNICATION_A_B.md`, `docs/qa/REGISTRE_BUGS.md` et `remarque.md`.
dev-c a terminé : sa partie (trésorerie, blockchain, finance, e2e) est répartie ci-dessous.

## 0. Règles communes

1. **Avant de commencer, dev-a fusionne `origin/dev-b` dans `dev-a`** (`git fetch origin && git merge origin/dev-b`). La branche `dev-b` contient déjà tout le travail de `dev-a` (dernier push) et de `dev-c`.
2. **Méthode** : cycle test, correction, re-test, par module. Un module est terminé après **deux cycles consécutifs sans nouveau ticket**, tous les tickets VÉRIFIÉS, REJETÉS ou À CLARIFIER, la série du module verte.
3. **Les testeurs ne corrigent pas le code applicatif. Les développeurs ne vérifient pas leurs propres corrections** (voir CLAUDE.md §7).
4. **Pas d'édition simultanée du même fichier** par deux agents. Les fichiers partagés sont `backend/sync/services.py`, `backend/sync/management/commands/sync_now.py`, `docs/qa/REGISTRE_BUGS.md`. Pour le registre : éditions ciblées, relire juste avant d'écrire.
5. **Numérotation des tickets** (le registre va aujourd'hui jusqu'à environ BUG-990) : dev-a utilise **BUG-1000 et suivants**, dev-b utilise **BUG-1100 et suivants**. Relire le registre avant d'écrire un numéro.
6. **Base SQLite conservée** (décision du 2026-11-22) : les verrous `select_for_update` sont seulement simulés, à noter dans les tickets concernés. Pas de PostgreSQL.
7. **Commandes de test** : voir CLAUDE.md §3. Sous Windows, utiliser `./.venv/Scripts/python.exe`, des noms de journaux uniques par agent, et lancer les longues séries en arrière-plan. Une suite complète de `sales` dure plus de 40 minutes.
8. **Ne jamais commiter** `docs/qa/captures/*.png`, `.env`, `*.sqlite3`. Ne pas utiliser `git stash` quand plusieurs agents travaillent.
9. Les statuts « À CLARIFIER » ne sont pas codés : les consigner dans le message de fin de partie, pour le client.

## 1. Répartition

| | dev-a | dev-b |
|---|---|---|
| Backend | `production/`, `sales/`, `treasury/`, `blockchain/`, `finance/` | `core/`, `clients/`, `commissions/`, `sync/`, `chat/`, `kiese/` |
| Frontend | Production & Stocks, Facturation, Clôture & Caisse, Livre de caisse, Blockchain, Finance, reçu thermique | Clients, Commissions, Paramètres, Boulangeries, Chat, Connexion, vitrine, layout |
| Transversal | e2e Playwright (`e2e/`), rendu 360 / 768 / 1440 px | Intégration, PR (le desktop et la documentation sont hors périmètre) |

Frontière sur le sync : dev-b possède le **moteur** de synchronisation. dev-a ouvre les tickets pour tout modèle de production, ventes ou trésorerie qui se synchronise mal, et dev-b les corrige.

## 2. À finir avant le push (dev-b, en cours)

- Cycle 15 des testeurs (production : transferts BUG-974 à 980 ; trésorerie : BUG-981 à 984 et blocage des ventes BUG-973 ; clients : BUG-981, 982, 984) : récupérer les rapports, corriger les nouveaux tickets, commiter.
- Frontend de la demande client 3 (bannière de blocage, modale de clôture du gérant, réglages de l'heure de clôture) : **fait** (BUG-973, `tsc` et build passent), non vérifié visuellement.
- Compte à jour de la règle de sortie : **le compte « deux cycles sans nouveau ticket » n'a pas commencé** pour les parties A, B et C, les cycles récents trouvent encore des tickets.

## 3. dev-a : production, ventes, trésorerie, finance

### 3.1 Tickets à corriger ou vérifier
- **Ventes** : BUG-660, 661, 662, 663 (OUVERT, mineurs), puis cycle de vérification. BUG-671 est À CLARIFIER.
- **Trésorerie** : relire dans le registre les statuts de BUG-810 à 819. Le registre contient des sections de détail dont le statut est resté périmé : **nettoyer le registre** (aligner les lignes de détail sur les lignes de tableau) et ne rouvrir que ce qui est réellement ouvert.
- **Finance** : BUG-513, 518, 520 (bloqués par la question client Q-028), 804, 805, 808, 809, 870 : tous À CLARIFIER, rien à coder tant que le client n'a pas répondu.
- **Production** : BUG-684 À CLARIFIER. BUG-625 : le test passe, la clarification client reste ouverte.
- **Fournées, stocks, rotation** : BUG-161, 278 (rotation 24 h) restent bloqués par les questions Q-017 à Q-021.

### 3.2 Frontend (non rejoué visuellement jusqu'ici)
- Vérifier à 360, 768 et 1440 px et en conditions réelles : BUG-655, 656, 674 à 677 (journal des sorties non valorisées par date, base de répartition, portée des catégories de dépenses), BUG-685 (export de la clôture, « Appro Reçu » en négatif), BUG-973 (bannière de blocage et modale de clôture, après le travail de dev-b).
- Découper `ClotureOperations.tsx` (84 Ko) en sous-composants dans `src/components/treasury/` (CLAUDE.md §4).

### 3.3 Demandes client à suivre
- **Demande 3** (heure de clôture, blocage des ventes) : le backend est fait (BUG-973, interrupteur désactivé par défaut par boulangerie), le frontend est en cours chez dev-b. dev-a relit le lien avec la clôture journalière et avec le stock de départ du lendemain (« les restes du jour deviennent le stock de départ »). Cinq points restent à clarifier avec le client : voir BUG-973.
- **Demande 4** : faite (BUG-674 à 677). À valider par l'auditeur comptable : le signe des transferts (BUG-675) sur les chiffres d'août.

### 3.4 Contrôle global (dans l'ordre)
1. `auditeur-comptable` : recoupement avec les Excel d'août 2026, états N et N-1.
2. `testeur-e2e` : rejouer `e2e/` avec `--repeat-each=5`, bureau et largeur POS (360 px) ; base jetable, Chromium déjà installé (**ne pas lancer `playwright install`**).
3. `testeur-charge` : pics du matin, 8 boulangeries.
4. Série complète `production`, puis `sales treasury finance blockchain`, en arrière-plan.

## 4. dev-b : clients, commissions, core, sync, intégration

### 4.1 Tickets à corriger ou vérifier
- **Cycle 15** (voir §2) puis cycles suivants jusqu'à deux cycles sans ticket sur : clients et commissions, permissions, synchronisation et charge.
- **À CLARIFIER (client)** : BUG-738, 742, 748, 783, 811(b), 937, 953, et les décisions sur COMPTABLE.
- **Questions client en attente** : rotation 24 h (Q-017 à Q-021), plafond 0, BUG-507 (recherche de clients entre boulangeries), BUG-411 (routes sans contrôle d'accès côté frontend).
- **Sync (décisions métier non tranchées)** : transfert déjà CONFIRMED au cloud inconnu d'un poste ; réponse positive du siège à une demande PENDING sans débit de l'émettrice ; clôture confirmée mais non versée, versée par un rejeu du poste.

### 4.2 Frontend
- Demande 3 : faite (bannière `ClosureBlockBanner`, modale `ClosureModal`, réglages dans `Nodes.tsx`). Reste : vérifier que la page des boulangeries est réservée à la direction et à l'admin (le formulaire ne contrôle pas le rôle), et le parcours réel (activer l'interrupteur, passer l'heure, valider côté direction).
- Vérifier le rendu des pages Clients, Commissions, Paramètres à 360, 768 et 1440 px.

### 4.3 Desktop : HORS PÉRIMÈTRE (ordre du responsable, 2026-11-23)
- Application Electron (CLAUDE.md §8) : Waitress, SQLite WAL, sauvegarde quotidienne, assistant de première configuration, mises à jour. Tickets BUG-073, 074, 075, 077, 081 à relire. Test d'installation sur machine vierge : poste avec navigateur et Windows propre.
- **Avant de déployer la migration `clients/0011`** : pousser d'abord les clients en attente de synchronisation, sinon une édition locale non envoyée peut être écrasée.

### 4.4 Intégration, livraison
1. Fusionner `dev-a` dans `dev-b` à chaque fin de partie, trancher les conflits sans perdre les règles strictes de `node_guard`.
2. Série complète des trois groupes : `core clients commissions sync chat` ; `production` ; `sales treasury finance blockchain`. Puis `npx tsc --noEmit`, `npm run build`, `makemigrations --check`.
3. Mettre à jour `docs/PR_dev-c_vers_main.md`. **La pull request vers `main` seulement sur l'ordre du responsable.**
4. **Documentation de livraison : HORS PÉRIMÈTRE** (ordre du responsable, 2026-11-23). Ne pas la rédiger ni lancer `redacteur-documentation`.
5. Marquer `[c]` dans `remarque.md` seulement après vérification indépendante.

## 5. Ce qui ne peut pas être fait sur ce poste
- Rendu visuel 360 / 768 / 1440 px et e2e : il faut un poste avec navigateur.
- Verrous réels (`select_for_update`) : seulement simulés sous SQLite.
- Matériel (imprimante thermique, POS Android, scanner) : exécution physique par un humain, procédures préparées par `testeur-materiel`.

## 6. Messages à écrire dans `docs/COMMUNICATION_A_B.md`
- **dev-b** écrit le message de reprise (n° suivant) pointant vers ce plan, et la liste des décisions « À CLARIFIER » à poser au client.
- **dev-a** écrit « partie A terminée » (production, ventes, trésorerie, finance) quand les critères du §0 sont remplis.
- **dev-b** écrit « partie B terminée » (clients, commissions, core, sync) de même.
