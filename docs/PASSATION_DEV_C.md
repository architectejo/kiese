# Passation du rôle « Dev C » au Dev B

Rédigée le 2026-11-22 par le Dev C (Claude), sur décision du responsable : **à partir de ce push, le Dev B reprend les tâches du Dev C et cumule `dev-b` et `dev-c`.** Le Dev A est revenu et travaille seul sur `dev-a` (production, ventes, trésorerie, finance, blockchain). Le Dev C n'intervient plus après ce commit.

## 1. Où en est le dépôt

- `dev-c` = branche d'intégration : contient `dev-a` jusqu'à `9fbb757` et `dev-b` jusqu'à `a91086e`. Dernière référence de tests :
  - suite backend complète : **2694 tests OK** (6 ignorés, 11 échecs attendus), avant les derniers lots de B ;
  - `core` + `commissions` + `clients` après fusion de B : **816 tests OK** ;
  - `makemigrations --check` propre ; `tsc --noEmit` et `npm run build` OK.
- Registre `docs/qa/REGISTRE_BUGS.md` : 326 tickets, aucun doublon de ligne ; le tableau fait foi (les « Statut » des fiches détaillées sont l'historique).
- Fichiers de pilotage : `docs/PLAN_TROIS_DEVELOPPEURS.md` (rôles), `docs/COMMUNICATION_A_B.md` (messages #01 à #26 ; on cite l'expéditeur, ex. #23-A), `docs/PR_dev-c_vers_main.md` (brouillon de la PR), `docs/qa/rapports/` (un rapport par agent et par lot), `docs/qa/QUESTIONS_CLIENT*.md` (Q-022 à Q-028).

## 2. Règles en vigueur (décisions du responsable)

1. **Push autonome** : A, B et C poussent leur branche dès qu'un lot est prêt, sans demander ; jamais de `--force`. Critère de « prêt » : `check` et `makemigrations --check` propres, tests ciblés verts, `tsc` et build OK si le frontend a changé, aucun `.env`, `.venv`, `*.sqlite3`, `node_modules` dans le commit.
2. **Testeurs à la fin, sur l'ordre du responsable** : aucun `testeur-*`, `relecteur-code` ni `auditeur-comptable` ne démarre avant son ordre. D'ici là : `dev-backend` et `dev-frontend`, avec leurs propres tests de non-régression ; tickets à `CORRIGÉ`, jamais `VÉRIFIÉ`.
3. **`desktop/` est gelé** pour tous (backend et frontend seulement). Waitress est le seul serveur WSGI.
4. Numérotation : A `BUG-3NN`, B `BUG-4NN`, C `BUG-5NN` (dernier connu : BUG-532 ; lire le registre avant d'ouvrir un ticket, des agents en créent en parallèle). Registre : Edit ciblés, relire la ligne avant ; jamais de réécriture complète.
5. `remarque.md` : `[]` → `[c]` seulement si la remarque est implémentée **et** vérifiée par un testeur ≠ développeur ; repérer la ligne par son texte (les numéros bougent). En cas de contradiction entre documents de référence, ne pas trancher : signaler.
6. Environnement Windows / Python 3.14 : `python -m venv .venv`, `pip install -r requirements.txt` (Pillow >= 10.4) ; sans `.env`, définir `DJANGO_DEBUG=True` et une clé jetable `DJANGO_SECRET_KEY` en variables d'environnement. Tests : `manage.py test <apps> --noinput` **sans `--parallel`** (plante sous 3.14), sortie redirigée dans un fichier. Frontend : `npm ci`, `npx tsc --noEmit`, `npm run build` (Node 26, npm 11).

## 3. Tâches restantes du Dev C (à faire par B)

### 3.1 À l'ordre « testeurs » du responsable : vérification indépendante

Lancer le testeur d'origine sur chaque ticket `CORRIGÉ` (il écrit ses tests dans un nouveau fichier `…_c.py`, passe le ticket à `VÉRIFIÉ` ou le rouvre) :

| Tickets `CORRIGÉ` | Agent à lancer | Points d'attention |
|---|---|---|
| BUG-380, 381, 382, 383 (envoi direct, Versement de la direction, page « Caisse », formulaire) | `testeur-production`, `testeur-tresorerie`, `testeur-e2e` | pas de navigateur sur le poste d'origine : rejeu e2e à faire sur une machine qui en a ; rendu 360/768/1440 px à contrôler à la main |
| BUG-385 (découpage de `Production.tsx` et `Sales.tsx`) | `relecteur-code` | fidélité au comportement d'avant, 0 `any` |
| BUG-526, 527, 528, 529 (500 → 400) | `testeur-production`, `testeur-ventes`, `testeur-tresorerie` | helpers de `kiese/node_guard.py` |
| BUG-417 (cotisation 2 000 FC et carte 1 000 FC partout, migrations `core/0021` et `0022`), 412/413 compléments | `testeur-clients-commissions` | une valeur propre positive n'est jamais écrasée ; commissions déjà générées inchangées |
| BUG-519 (sync garde `unit_price` et `full_unit_price`), BUG-331/332 déjà vérifiés | `testeur-charge` | ancien payload sans prix inchangé |
| BUG-517, 523 (suppression d'un nœud : siège et chat), 530, 531, 532 | `testeur-permissions` | marques `@expectedFailure` déjà retirées ; 4 attaques à rejouer |
| BUG-148 (e2e `05-production` instable), spec 32 et 33 | `testeur-e2e` sur un poste avec navigateur | rejeu `--repeat-each=5` |
| BUG-416 (tests CUMP instables sous Windows) | `testeur-production` | 6 exécutions consécutives vertes |

Ensuite : **rejouer la matrice rôles × routes** (`testeur-permissions`, fichiers `core/tests/test_verif_matrice_c.py`, `test_verif_isolation_a_c.py`, `test_verif_params_invalides_c.py`).

### 3.2 `remarque.md` : `[]` → `[c]` après vérification

Lignes à `[]` à marquer **quand leur ticket est `VÉRIFIÉ`** : envoi direct de pains (BUG-380/382), « Versement » visible de la direction (BUG-381), « Clôture & Caisse » devenue « Caisse » (BUG-383), cotisation et carte en FC (BUG-417, ligne « Dit à dev-b … »). **Ne pas marquer** (non faites ou en attente du client) : clôture automatique à l'heure de relève, rotation 24 h, modale « Stock de départ » aux heures de rotation (BUG-161/278), régularisation d'un « Non servi » (BUG-356 b), vue globale des consommables pour la direction (à chiffrer), lignes sur les valeurs du formulaire §2.3 propres à chaque boulangerie (taux CM par défaut encore global).

### 3.3 Fin de projet

1. Suite backend **complète** (≈ 30 à 45 min) + `tsc` + build, puis mettre à jour `docs/PR_dev-c_vers_main.md` (chiffres, migrations, tickets) et **ouvrir la PR `dev-c` → `main`** sur l'ordre du responsable ; fusion après relecture.
2. Adapter les e2e qui lisent la clôture sur `/treasury` (désormais `/cloture-journaliere`) : `06`, `18`, `21`, `22`, `24` ; ajouter un scénario e2e du flux d'envoi direct (§3.3 de Production) ; rejouer 05, 31, 32 et 33.
3. Documentation de livraison (B-7), sans le guide d'installation desktop.

## 4. Points ouverts qui dépendent du client (ne pas coder)

Q-022 à Q-028 (`docs/qa/QUESTIONS_CLIENT_SIMPLIFIE.md`, `QUESTIONS_CLIENT.md`) : BUG-266/267/268 (commissions), BUG-507 et 253 et 411 (livreur), BUG-513/518/520 (tarif figé, DOC 1, catégories du CA ; Q-028), rotation 24 h (BUG-161/278), BUG-356 b, vue globale des consommables. Décisions prises par défaut, à révoquer par le client : le COMPTABLE ne voit pas « Versement » ; dépenses locales et rapport facturier §5.1.1 classés en « clôture » ; envoi direct sans annulation et refus si stock insuffisant.

## 5. Précautions avant la mise en production

- **`sales/0012`** (rétro-remplissage de `full_unit_price`) : non testée sur PostgreSQL. Mesure à faire sur une copie de la base cloud (`EXPLAIN (ANALYZE, BUFFERS)`, durée de `migrate sales`, verrous pendant des écritures, taille de la table) ; au-delà d'environ 10^6 lignes, découper l'`UPDATE` par plages de pk.
- **`recompute_cump`**, **`fix_mojibake_names`** : jamais lancées avec `--apply` sur une base réelle ; sauvegarde et lecture de la simulation d'abord, par la personne qui détient la base. `check_users_sans_noeud` (lecture seule) à lancer sur la base réelle.
- Sauvegarde de la base réelle avant toute migration (`core/0021`, `core/0022`, `blockchain/0002`, `production/0027`, `sales/0011`, `sales/0012`).
- Limite connue : `select_for_update()` n'a pas d'effet sous SQLite ; la concurrence réelle n'a été testée que par séquence et espion de verrou.
