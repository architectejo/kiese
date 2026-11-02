# CLAUDE.md — Projet ETS. KIESE

Ce fichier guide Claude (et les sous-agents de `.claude/agents/`) sur ce dépôt.
Langue de travail : **français** (code et noms techniques en anglais, interface et messages en français).

---

## 1. Le projet en bref

Plateforme de gestion pour les **8 boulangeries de l'ETS. KIESE** (Mbanza-Ngungu, Kongo-Central, RDC) :
K1 TABORA · K2 COQ · K3 ATHENEE · K4 LOMA · K5 MPIANGU · K6 ZADIM · B1 KUMBI · B2 MPETE.
Siège : 49, Av. Tabora. Monnaie : Franc Congolais (FC).

Elle remplace les cahiers papier et les fichiers Excel par une application unique :
clients et commissions → facturation et livraison → production et stocks → clôture de caisse → livre de caisse direction (chaîne de hash) → états financiers N / N-1.

Documents de référence (à lire avant toute modification métier) :
- `cahierDesCharges.md` : spécification contractuelle initiale.
- `remarque.md` : retours du client après les démos (**prioritaire sur le cahier des charges en cas de conflit**).
- `adaptes.md` : écarts relevés entre l'app et les Excel réels d'août 2026.
- `cadre_comptable.md` : plan comptable et TFR signés le 21/09/2026 (refonte du module finance, hors forfait initial).

Ordre de priorité en cas de contradiction : **remarque.md > adaptes.md > cadre_comptable.md > cahierDesCharges.md**. Signaler toute contradiction dans le registre au lieu de trancher seul.

---

## 2. Structure du dépôt

```
backend/                Django 5 + DRF (API REST, JWT)
  kiese/                settings.py, urls.py
  core/                 User, Node (boulangerie), Config, BreadPrice, ExpenseCategory,
                        ActivityLog, SystemNotification, permissions RBAC, SyncableModel
  clients/              Client, caisse sociale (SocialContribution/Distribution), import Excel
  sales/                Invoice, InvoiceLine (facturation, BP, reçus)
  production/           ProductionSession, BreadStock, Consumable*, BreadTransfer, BreadDisposal
  treasury/             LocalExpense, FacturierReport, CashClosure, CashbookEntry (hash),
                        JournalEntry, DailySavings, DisbursementVoucher
  commissions/          CommissionPeriod, ClientCommission (CM, retenues, net à payer)
  finance/              FinancialYear + états financiers calculés (views.py)
  blockchain/           TamperAlert, BlockchainSnapshot, vérification de chaîne
frontend/               React 19 + TypeScript + Vite + Zustand + axios
  src/api/              client.ts (axios + refresh JWT), services.ts
  src/pages/dashboard/  une page par module
  src/pages/website/    vitrine publique
  src/components/       layout, Modal, Charts, ThermalReceipt
docs/qa/                registre des bugs et rapports des agents
e2e/                    tests Playwright (à créer)
desktop/                application Electron (à créer, phase 3)
```

Toutes les routes API sont préfixées : `/api/core/`, `/api/clients/`, `/api/sales/`, `/api/production/`,
`/api/treasury/`, `/api/commissions/`, `/api/finance/`, `/api/blockchain/`. Documentation : `/api/docs/swagger/`.

---

## 3. Commandes

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # puis renseigner les variables
python manage.py migrate
python manage.py seed_kiese                              # données de démonstration
python manage.py runserver 8000
python manage.py test                                    # tous les tests
python manage.py test sales                              # une app
python manage.py makemigrations --check --dry-run        # aucune migration oubliée
```

> ⚠️ Dans l'archive d'origine, `backend/.env` est un **environnement virtuel Windows**, pas un fichier de configuration.
> `settings.py` lit `BASE_DIR / '.env'` comme fichier. Le venv doit être renommé `.venv` et `.env` doit être un fichier texte.

### Frontend
```bash
cd frontend
npm ci
npm run dev          # http://localhost:5173 (VITE_API_URL dans .env)
npm run build        # tsc + vite build → doit passer sans erreur
npx tsc --noEmit     # vérification des types seule
```

### E2E (à mettre en place)
```bash
cd e2e && npm ci && npx playwright test
```
Chromium est déjà installé dans l'environnement cloud : **ne pas lancer `playwright install`**.

---

## 4. Architecture et conventions de code

### Backend
- Les modèles métier synchronisables héritent de `core.models.SyncableModel` : clé **UUIDv4**, `node_origin`, `is_synced`, `created_at`, `updated_at`. Ne jamais introduire d'ID auto-incrémenté sur une entité synchronisable.
- **Argent = `Decimal` uniquement.** Jamais de `float` pour un montant, un taux ou une quantité de consommable. Arrondi explicite (`quantize`) au moment de l'affichage ou de l'écriture comptable.
- Toute opération qui modifie un solde (dette client `current_debt`, stock de pains, stock de consommables, livre de caisse) doit être dans `transaction.atomic()` avec `select_for_update()` sur la ligne lue, ou une mise à jour `F()`.
- Permissions : utiliser les classes de `core/permissions.py` (`IsAdmin`, `IsDirection`, `IsHeadquarters`, `IsGerant`, `IsFacturier`, `IsLivreur`, `IsFacturierOrLivreur`). Tout `get_queryset()` doit filtrer par `user.node` si `not user.can_access_all_nodes`, **sauf** la recherche de clients par les facturiers (voir règle 5.1).
- Toute action métier significative appelle `log_activity(...)`. Toute alerte passe par `create_notification(...)`.
- Les prix des pains viennent **toujours** de `BreadPrice` (jamais saisis librement). `InvoiceLine.save()` fige `unit_price`.
- Migrations : ne jamais modifier une migration déjà appliquée. Une migration par changement de schéma, avec migration de données si nécessaire.
- Messages d'erreur API en français, format `{"detail": "..."}`.

### Frontend
- TypeScript strict : **pas de nouveau `any`**. Types des réponses API dans `src/api/` (ou `src/types/`).
- Tous les appels HTTP passent par `src/api/services.ts`, jamais d'axios direct dans une page.
- Les pages font aujourd'hui jusqu'à 150 Ko : toute modification importante d'une page doit extraire les sous-composants touchés dans `src/components/<module>/`.
- Interface en français. Montants formatés `12 500 FC` (séparateur d'espace, sans décimales sauf consommables).
- Responsive obligatoire : POS Android (≈ 360 px), téléphone, tablette, bureau, TV.

### Données et sécurité
- **Ne jamais committer** : `.env`, `*.sqlite3*`, `.venv/`, `node_modules/`, `dist/`, `*.zip`, `data_kiese/`.
- `data_kiese/` contient des données réelles (clients, téléphones, caisse). Ne jamais les copier dans des fixtures de test : fabriquer des données fictives.
- Ne jamais afficher ni journaliser de mot de passe, jeton JWT ou `SECRET_KEY`.

---

## 5. Règles métier (référence pour le code et les tests)

### 5.1 Clients
- Code unique généré automatiquement. Recherche prédictive par nom partiel ou code.
- Un facturier **peut rechercher et facturer les clients des autres boulangeries** (remarque.md).
- **Plafond crédit par défaut : 50 000 FC**, modifiable par le gérant et ses supérieurs.
- Catégories automatiques : *Meilleur client* (seuil `Config.best_client_threshold`), *Client à risque* (dette ≥ plafond ou retraits irréguliers).
- Types de vente (adaptes.md) : client régulier (CM 25 %), **VENTE SOLDE** et **VENTE CASH** (prix à 75 %, CM = 0), **client épargne** (commande = 0, paiement = dépôt, BP négatif possible).
- Codes spéciaux : `NV` nouveau client, `RG` régularisation, `NS` non servi, code boulangerie (`K1`, `B2`…) = transfert.

### 5.2 Balance de paiement (BP) et facturation
- `BP_après = BP_avant + valeur_commande − paiement_du_jour`. Cumulatif, **jamais remis à zéro** d'un mois à l'autre. BP négatif = crédit en faveur du client.
- **Blocage** : si `BP_avant ≥ plafond` **et** `paiement < valeur_commande` → refus (HTTP 403) + notification. Contrôle complémentaire existant : déficit net du mois (`commandé − versé − CM`) ≥ plafond.
- **Remboursement** : facture sans ligne, commande = 0, réduit la BP, n'est pas une vente.
- Flux : facturier crée la facture (statut *En attente de livraison*) → livraison confirmée (**par le facturier ou le livreur**, remarque.md) → déstockage + impression du reçu.
- Le reçu contient : entête légal (RCCM 021-A-650, Id.Nat 10-F4300-N85947U, N° Impôt A1902266K), code boulangerie, horodatage, facturier + équipe, client, lignes, valeur commande, versement, taux CM, BP avant, BP après, « Solde arrêté ce jour ».
- Équipes : **A et B uniquement** (pas de jour/nuit).

### 5.3 Commissions
- `CM brute = valeur commande pains × taux (0,25 ou 0,30)`
- `Total retenues = dette + sociale + imprimés + autre`
- `Remise annuelle = 0,025 × volume total livré` (incorporable au net à la liquidation)
- `Net à payer = (CM brute + remise incorporée) − total retenues`
- Listing de paie par boulangerie avec totaux verticaux.

### 5.4 Production et stocks
- Le propriétaire raisonne **en valeur** : un sac (50 kg) vaut une valeur théorique en FC (`Node.sac_value_fc` ou config, ex. 200 000 FC), variable. Les catégories de pains sont configurables (ajout/suppression, ex. pain de 200 FC).
- `Écart = valeur théorique (sacs × valeur_sac) − valeur produite déclarée` → afficher clairement **manquant** ou **excédent**.
- Consommables : farine (sacs, décimaux), **sel en grammes**, **levure en paquets décimaux** (ex. 0,25), **huile en litres décimaux**. Une fournée décrémente tous les consommables utilisés.
- `Stock restant = stock initial + entrées − utilisé`.
- **Transfert inter-boulangeries** : sortie en attente → validation par la boulangerie réceptrice → opération miroir (−N émettrice, +N réceptrice, marqués « reçus »). Écart quantité validée ≠ envoyée → alerte et blocage de la clôture. **Somme nulle au niveau du groupe.**
- Pains non vendus au prix fort : soldés, déclassés, invendus, sorties gratuites, reste à vendre.

### 5.5 Trésorerie
- Niveau 1 : rapport facturier par équipe (cash, crédit, espèces théoriques).
- Niveau 2 : clôture gérant — `caisse nette = ventes cash − dépenses locales`, **ventilation des billets** obligatoire (20 000, 10 000, 5 000, 1 000, 500, 200, 100, 50 FC) ; écart physique/théorique journalisé et non modifiable.
- Niveau 3 : livre de caisse direction, **lecture seule**, `solde = solde_précédent + entrée − sortie`, chaque écriture chaînée par SHA-256 (`previous_hash`). **Une seule fonction de hash** pour l'écriture et la vérification.

### 5.6 Finance
- États N / N-1 : balance, compte de résultat, bilan, cash-flow. Le plan comptable de `cadre_comptable.md` est la cible (refonte à valider et chiffrer avec le client avant développement).

---

## 6. Problèmes connus au démarrage (backlog initial)

À enregistrer dans `docs/qa/REGISTRE_BUGS.md` dès la première session :
1. **Deux formules de hash différentes** : `treasury/views.py::_compute_hash` (JSON) vs `blockchain/views.py::_verify_chain_for_node` (concaténation) → toutes les écritures seront signalées falsifiées.
2. `_get_last_balance()` sans verrou : deux validations simultanées créent deux blocs de même parent.
3. Le hash ne couvre ni `node`, ni `imputation`, ni `source_closure`.
4. Synchronisation nœud local ↔ cloud **non implémentée** (aucun endpoint, aucun mode hors-ligne frontend).
5. `SECRET_KEY` et `DEBUG=True` par défaut ; aucun réglage HTTPS (HSTS, cookies sécurisés, redirection).
6. JWT dans `localStorage`, 12 h, `BLACKLIST_AFTER_ROTATION=False`, pas de limitation des tentatives de login.
7. `backend/.env` est un venv ; `.env.production` contient une clé à considérer comme exposée.
8. **Aucun test automatisé** (les 8 `tests.py` sont vides).
9. Encodage cassé dans `settings.py` (« â€” ») : réenregistrer en UTF-8 sans BOM.
10. `secure.html` à la racine : fichier de test à supprimer.
11. Pages React géantes et nombreux `any` (Treasury, Clients, Production, Settings).

---

## 7. Organisation des agents

Les sous-agents sont dans `.claude/agents/`. Le **coordinateur** pilote ; les autres agissent sur demande.

| Phase | Agents |
|---|---|
| 0. Préparation | `coordinateur`, `nettoyeur-securite` |
| 1. Fondations | `ingenieur-blockchain`, `architecte-sync` |
| 2. Tests par module | `testeur-clients-commissions`, `testeur-ventes`, `testeur-production`, `testeur-tresorerie`, `testeur-permissions` |
| 3. Corrections | `dev-backend`, `dev-frontend` |
| 4. Contrôle global | `auditeur-comptable`, `testeur-e2e`, `testeur-charge`, `relecteur-code` |
| 5. Desktop | `packaging-desktop`, `testeur-installation`, `testeur-materiel` |
| 6. Livraison | `redacteur-documentation` |

### Règles de collaboration (obligatoires)
1. **Un seul registre** : `docs/qa/REGISTRE_BUGS.md`. Chaque anomalie y reçoit un identifiant `BUG-NNN`.
2. **Les testeurs ne corrigent pas le code applicatif.** Ils écrivent des tests (dans `backend/<app>/tests/`, `e2e/`) et ouvrent des tickets.
3. **Les développeurs ne valident pas leurs propres corrections.** `dev-backend` / `dev-frontend` passent un ticket à `CORRIGÉ` ; seul le testeur d'origine (ou le coordinateur) le passe à `VÉRIFIÉ`.
4. Chaque correction est accompagnée d'un **test qui échouait avant et passe après**.
5. Avant de rendre la main : `python manage.py test` et `npm run build` passent.
6. Un agent qui découvre une contradiction entre documents de référence la signale au coordinateur au lieu de choisir.
7. Les rapports d'agents vont dans `docs/qa/rapports/<agent>-<AAAA-MM-JJ>.md`.

### Cycle de vie d'un ticket
`OUVERT` → `EN COURS` (dev) → `CORRIGÉ` (dev, avec test) → `VÉRIFIÉ` (testeur) — ou `REJETÉ` / `À CLARIFIER` (question client).

### Définition de « terminé » pour un module
- Tous les scénarios de la section 5 couverts par des tests automatisés qui passent.
- Aucun ticket bloquant ou majeur ouvert sur le module.
- Parcours E2E du module vert sur bureau et sur largeur POS (360 px).
- Résultats recoupés avec les Excel d'août 2026 par `auditeur-comptable` (pour les modules financiers).

---

## 8. Cible desktop (phase 5)

Application Electron installable dans chaque boulangerie, servant de **nœud local** :
- Electron lance le backend Django empaqueté (PyInstaller) servi par **Waitress** sous Windows (Gunicorn ne fonctionne pas sous Windows ; Gunicorn + Nginx restent pour le serveur cloud Linux).
- Pas de Nginx sur le poste : Electron charge le build React et parle à `http://127.0.0.1:<port>`.
- SQLite en mode WAL, sauvegarde quotidienne automatique, migrations au démarrage.
- `SECRET_KEY` générée à l'installation, unique par poste.
- Impression thermique silencieuse via Electron ; mises à jour via `electron-updater` ; installeur `electron-builder` (.exe) avec assistant de première configuration (code boulangerie, compte admin, URL du cloud).
- Synchronisation avec le cloud par le module conçu par `architecte-sync`.
