# Brouillon de Pull Request — `dev-b` → `main`

> Brouillon mis à jour par dev-b le 2026-11-24 (remplace la version `dev-c` du 2026-11-22). **À ne pas ouvrir avant l'ordre du responsable.** `dev-b` contient tout le travail de dev-a (fusion `a2bd282`) et de dev-c. Sur GitHub, le corps de la PR se termine par la mention « Generated with Claude Code ».

## Résumé

313 commits depuis `main` (v1.0.0), environ 860 fichiers, 22 migrations. Contenu par thème :

- **Isolation entre boulangeries et permissions** : fuites corrigées (trésorerie, production, clients), comptes sans boulangerie refusés, paramètres invalides → 400. **Livreur = facturier** (Q-027, BUG-1050) : mêmes droits, il peut créer clients et factures dans sa boulangerie ; il ne voit les clients des autres boulangeries qu'en ligne (`sync/connectivity.py`). Gardes de routes du frontend alignées sur le menu (BUG-1115, 1203).
- **Synchronisation poste local ↔ cloud** : push/pull par lots, strictes vérifications d'identité, horloge, transferts (miroirs, états), conflits tracés (`SyncConflictLog`), blocs de pull `node_settings`, `consumable_types`, `closures`, `mirrors`, pagination, commande `sync_now`.
- **Clients / commissions** : taux de commission par boulangerie (`Node.default_commission_rate`, BUG-1103), carte retenue une seule fois par client et par mois (BUG-1104), retenue unique sur la ligne la plus ancienne (BUG-737/1013), cotisation 2 000 FC et carte 1 000 FC par boulangerie, nouveau client jamais « SUSPENDU » (BUG-1116), plafond 0 / dette 0 non « à risque » (BUG-742).
- **Clôture et blocage des ventes** (BUG-973) : heure de clôture et interrupteur par boulangerie, bannière et modale de clôture, `/api/treasury/closure-status/`, compteur de re-soumissions (BUG-996).
- **Production / intrants** : statistiques journalières par intrant (farine, levure, huile, sel ; BUG-1060/1061), farine du mois, **export Excel au format du client** (`/api/production/intrants-export/`), sel : 1 sac = 20 kg = 204 boîtes (stock en grammes), stock de départ, envoyés/reçus par transfert (A-1/A-3), restes par journée et clôture automatique (A-4).
- **Trésorerie, blockchain, finance** : chaîne de hash unique, alertes protégées, états N / N-1 (voir registre).
- **Interface** : 360 px (en-tête, tableaux de clôture), trois thèmes contrôlés dans Chrome pour l'historique du client.
- **Python 3.14** : `Pillow>=10.4,<14.0`. **Waitress** est le seul serveur WSGI. `desktop/` est gelé et la documentation de livraison est hors périmètre (ordre du 2026-11-23).

## Migrations à appliquer, dans l'ordre

| App | Migrations | Remarque |
|---|---|---|
| `core` | 0021 (carte par boulangerie), 0022 (défauts 2 000 / 1 000 : ne remplace que 0), 0023 (portée des catégories de dépenses), 0024 (blocage après clôture), 0025 (taux de commission par boulangerie, copie du taux global) | 0022 : une valeur propre déjà saisie n'est pas écrasée |
| `clients` | 0011 (`identity_updated_at`) | **pousser d'abord les clients en attente de synchronisation** sur les postes, sinon une édition locale non envoyée peut être écrasée |
| `commissions` | 0006 (`deduction_manual`), 0007 (`card_applied`) | additives |
| `production` | 0027 (flux de transfert), 0028 (inventaires de consommables), 0029 (prix 4 décimales), 0030 (`ConsumableCount.is_synced`), 0031 (conversion sac/boîtes) | additives |
| `sales` | 0011 (prix plein), 0012 (rétro-remplissage, par lots, `atomic = False`) | 0012 non mesurée sur gros volume : à chronométrer sur une copie de la base cloud |
| `sync` | 0002 à 0006 | additives |
| `treasury` | 0018 (`resubmit_count`) | additive |
| `blockchain` | 0002 (`PROTECT` sur le nœud) | réversible |

Base conservée : **SQLite** (décision du 2026-11-22). Les verrous `select_for_update` sont seulement simulés ; PostgreSQL non testé.

## Commandes de gestion (ne rien lancer sans sauvegarde)

- `check_users_sans_noeud` : lecture seule.
- `recompute_cump` : simulation par défaut ; `--apply` réécrit des valorisations passées.
- `fix_mojibake_names` : simulation par défaut.
- `auto_close_sessions` : clôture automatique des fournées (actif seulement où l'heure de clôture est activée).
- `sync_now` : synchronisation d'un poste avec le cloud.

## Changements de comportement d'API

- Paramètres invalides (`?node=ZZZ`, `?month=abc`) : 400 `{"detail": ...}`.
- Nombres : chiffres ASCII uniquement (`core/numeric.py`), exposants, NaN, bool et NBSP refusés.
- Livreur : mêmes routes que le facturier (clients create, factures, remboursements) ; ne modifie ni ne supprime de clients.
- Nouveaux endpoints : `closure-status`, `consumables/flour-month-stats`, `intrants-stats`, `intrants-export`, blocs de pull `node_settings` et `consumable_types`.

## Avant de fusionner

1. **Séries complètes** sur le code final : `core clients commissions sync chat` ; `production` ; `sales treasury finance blockchain` (résultats de la série finale du 2026-11-24 dans `docs/COMMUNICATION_A_B.md`), `makemigrations --check` (propre), `npx tsc --noEmit` (propre), `npm run build` (OK).
2. **Décisions du client en attente** (aucun code tant qu'elles ne sont pas tranchées) : rotation de 24 h (Q-017 à Q-021), Q-028 (BUG-513/518/520), Q-043, Q-044 à Q-054 (intrants, taux global, stock de départ, clôture automatique, date d'une réception hors ligne), BUG-625/671/684/937/953/986/1002/1029/1101, cinq points de BUG-973, montant de la carte, stock négatif de consommable (BUG-1020/216).
3. **E2E Playwright** : à rejouer sur un poste avec navigateur (`e2e/`).
4. **Sauvegarde de la base réelle** avant toute migration ou commande ci-dessus.

## Points connus, non bloquants

- Les tickets ont été vérifiés par vérification croisée dev-a / dev-b (relecture, rejeu des tests, contrôle Chrome sur instance jetable), selon `docs/PLAN_FIN_PROJET_A_B_2026-11-24.md`, et non par les agents testeurs.
- Concurrence réelle non testable sous SQLite.
- Matériel (imprimante thermique, POS Android) : exécution physique par un humain.
- Plusieurs pages restent volumineuses (`ClotureOperations.tsx`, `Clients.tsx`).
