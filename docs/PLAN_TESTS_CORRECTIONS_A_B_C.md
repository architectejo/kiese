# Plan de tests et corrections répétés — A, B, C (2026-11-22)

Décision du responsable : chacun des trois développeurs prend **une partie de l'application** et enchaîne des **cycles test → correction → re-test** jusqu'à ce qu'il n'y ait plus d'erreur. Les agents testeurs sont désormais autorisés (ordre du responsable du 2026-11-22). Règles inchangées : push autonome sans `--force`, `desktop/` gelé, pas de `.env`/`.venv`/`*.sqlite3`/`node_modules` dans un commit, registre en Edit ciblés (jamais de réécriture complète), `[]` → `[c]` dans `remarque.md` seulement après `VÉRIFIÉ`.

## 1. Partage de l'application (propriété du code et des tests)

| Dev | Parties | Backend | Frontend (`src/pages`, `src/components`) | Agents testeurs |
|---|---|---|---|---|
| **A** | Production et stocks, Ventes (facturation, livraison, reçus) | `production/`, `sales/` | Production, Sales, ThermalReceipt | `testeur-production`, `testeur-ventes` |
| **B** | Clients, Commissions, Core (utilisateurs, nœuds, config, RBAC), Sync, Chat | `clients/`, `commissions/`, `core/`, `sync/`, `chat/`, `kiese/` | Clients, Commissions, Settings, Nodes, Chat, Login, vitrine | `testeur-clients-commissions`, `testeur-permissions` (RBAC transversal), `testeur-charge` (sync, concurrence) |
| **C** | Trésorerie, Caisse/Clôture, Livre de caisse (hash), Blockchain, Finance (états N / N-1), e2e et intégration | `treasury/`, `blockchain/`, `finance/`, `e2e/` | Treasury, Cloture, Caisse, Finance, tableau de bord | `testeur-tresorerie`, `auditeur-comptable`, `testeur-e2e`, `relecteur-code` |

Changement par rapport à l'ancien partage : `treasury/`, `finance/`, `blockchain/` passent de A à **C**. A ne les modifie plus ; s'il trouve une anomalie dedans, il ouvre un ticket et le message va à C.

**Règle d'indépendance** : le testeur d'origine vérifie, jamais le développeur qui a corrigé. Un dev peut lancer les testeurs de **sa** partie (agents ≠ `dev-backend`/`dev-frontend`). Un ticket trouvé dans la partie d'un autre est transmis à son propriétaire par message dans `docs/COMMUNICATION_A_B.md` (ne pas corriger chez l'autre).

**Numérotation** (nouvelle phase) : A `BUG-6NN`, B `BUG-7NN`, C `BUG-8NN`. Avant d'ouvrir un ticket, relire le registre.

## 2. Le cycle (à répéter par chaque dev sur sa partie)

1. **Tester** : les testeurs de la partie attaquent (scénarios de `CLAUDE.md` §5, `remarque.md`, cas limites, rôles, autre boulangerie, paramètres invalides, concurrence par séquence). Ils écrivent des tests dans `…_c.py`/`…_v2.py`, ouvrent des tickets (`OUVERT`).
2. **Corriger** : `dev-backend` / `dev-frontend` corrigent chaque ticket **avec un test qui échouait avant et passe après**, passent le ticket à `CORRIGÉ`.
3. **Re-tester** : le testeur d'origine rejoue ses tests, vérifie la correction (`VÉRIFIÉ`) ou rouvre, **et attaque sous de nouveaux angles** (régression, voisinage de la correction).
4. **Série de la partie** : `python manage.py test <apps de la partie> --noinput` (sans `--parallel`, sortie dans un fichier), `check`, `makemigrations --check`, et `tsc --noEmit` + `npm run build` si le frontend a bougé. Commit + push de sa branche.
5. **Recommencer** au 1 avec de nouveaux angles.

**Critère d'arrêt d'une partie** : **deux cycles consécutifs sans aucun nouveau ticket** (hors tickets « client » ci-dessous), tous les tickets de la partie `VÉRIFIÉ`/`REJETÉ`/`À CLARIFIER`, série de la partie verte. Alors le dev l'écrit dans `COMMUNICATION_A_B.md` (« partie X terminée »).

## 3. Tickets déjà ouverts à reprendre (issus de la vérification du 2026-11-22)

| Ticket | Sujet | Propriétaire |
|---|---|---|
| BUG-555 | `ConfigForm.tsx` : « Frais d'Imprimés » modifiable mais sans effet (carte = `Node.card_fee_fc`) | B |
| BUG-564 | ADMIN peut renommer le code `SIEGE` puis supprimer le nœud (contourne BUG-517) | B |
| BUG-540, 541, 562 | `transfers/send` accepte SIEGE/nœud inactif ; `dispatch` avec `node: true` ; quantité `1e400` → 500 | A |
| BUG-560, 563 | `?node=` invalide → 500 sur `journal`/`savings` ; second `POST reports/` même jour → 500 ; `versements` liste SIEGE | C |
| BUG-561 | `blockchain/snapshots/run_check/` avec corps JSON liste → 500 | C |
| BUG-388 et synchro `ConsumableInventory` (B, livrés `98adc3e`) | à faire vérifier par le testeur de la partie concernée | A (production) |

D'autres tickets arriveront des agents encore en cours (production, trésorerie, ventes) : le propriétaire de la partie les reprend.

## 4. Hors boucle (client ou matériel)

Q-022 à Q-028 (BUG-266/267/268, 507, 253, 411, 513/518/520, 161/278, 356 b) : ne rien coder avant réponse. Rendu navigateur 360/768/1440 px et e2e : à rejouer sur un poste avec Chromium (B en dispose, voir #27-B). `desktop/` gelé. Documentation de livraison : à la toute fin, répartie à nouveau.

## 5. Intégration et fin

- Chacun pousse **sa** branche (`dev-a`, `dev-b`, `dev-c`) à chaque lot vert. **C intègre** : fusion de `origin/dev-a` et `origin/dev-b` dans `dev-c`, série **complète** (30 à 45 min), puis met à jour `docs/PR_dev-c_vers_main.md`. La PR `dev-c` → `main` ne s'ouvre que sur l'ordre du responsable.
- Fin du projet de tests : les trois parties « terminées », série complète verte sur `dev-c`, e2e verts sur poste avec navigateur, registre sans ticket `OUVERT`/`CORRIGÉ` hors client.

## 6. Environnement (rappel)

Windows, Python 3.14 : `python -m venv .venv`, `pip install -r requirements.txt` ; sans `.env` : `DJANGO_DEBUG=True` et `DJANGO_SECRET_KEY` jetable. Tests **sans `--parallel`**, sortie redirigée dans un fichier. Voir `docs/PASSATION_DEV_C.md` §2.
