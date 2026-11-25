# Rapport de tests — dev-b — 2026-11-25

Ordre : #51-A (responsable). Branche `dev-b`, code testé : **`29f112e`** (fusion de `origin/dev-a`, contient `5e12db5`).
Instance jetable : backend `127.0.0.1:8002` (base `e2e_b.sqlite3` dans le scratchpad, seed de démonstration), frontend Vite `5175`. Ni base réelle ni `data_kiese/`.

## 1. Tests automatisés

Depuis `backend/`, avec `PYTHONIOENCODING=utf-8 DJANGO_DEBUG=False DJANGO_SECURE_SSL_REDIRECT=False DJANGO_SECRET_KEY=<clé de test> KIESE_TEST_CLOCK_SHIFT=1` :

| Commande | Résultat |
|---|---|
| `manage.py test production.tests.test_bug1300_alerte_appelant_present_a production.tests.test_dev_b_rotation_q017_021 core.tests.test_bug284_password_change core.tests.test_verif_permissions_b8_v8` (avant 13:00, décalage d'horloge actif) | **Ran 59 tests — OK** |
| Runner forcé (décalage de 5 h imposé) + `core.tests.test_bug284_password_change` — preuve BUG-1302 (throttle DRF avec `time.time` remplacé) | **Ran 11 tests — OK** |
| `manage.py test clients commissions --noinput` (suite complète) | **Ran 977 tests in 4930 s — OK (expected failures=5)** |

Aucun échec, aucune erreur de concurrence SQLite à rejouer.

## 2. Vérification croisée (tickets de dev-a)

| Ticket | Contrôle | Statut |
|---|---|---|
| BUG-1300 — fausse alerte Q-021 quand l'appelant est un agent de la boulangerie | Relecture : `present_user` transmis par `shift-end-status` à `notify_direction_if_unattended_closure` ; tests rejoués OK | **VÉRIFIÉ** |
| BUG-1302 — runner d'horloge incompatible avec `SimpleRateThrottle.timer` | Relecture : remplacements `*_args` ; rejeu normal et forcé OK | **VÉRIFIÉ** |

BUG-1301 (verrou de vente si la veille n'a aucune clôture) : reste À CLARIFIER (question client).

## 3. Parcours Chrome (compte `pierre`, DIRECTION)

| Écran | Taille | Résultat |
|---|---|---|
| Succursales `/admin/nodes` — création : libellé « Heure de clôture », aide « midi à midi », bannière « direction ou comptable », rotation cochée par défaut, blocage décoché | bureau | OK (remarque ci-dessous) |
| Production — « Stock Pains du Jour » daté du jour ouvré (25/11/2026), colonnes stock de départ / Envoyés / Reçu / TOTAL | bureau | OK (B1 sans données) |
| Intrants > Statistiques — « situation du 25/11/2026 », K1 8, **D1 160**, TOTAUX 168, indice et écart | bureau | OK |
| Clients, Commissions, Finance, Paramètres — chargement sans message d'erreur | 1280 px | OK |
| 8 pages (Clients, Commissions, Finance, Paramètres, Trésorerie, Clôture journalière, Production, Succursales) — aucun débordement horizontal, aucun texte d'erreur | 360 px et 1280 px | OK |

**Remarque (non bloquante, pas de ticket ouvert)** : le formulaire de succursale propose encore la suggestion héritée « équipe A 06h00–13h00, B 13h00–20h00 » et affiche les horaires A/B même quand la rotation de 24 h est cochée. Lié à la question ouverte « sort du mode créneaux fixes A/B » (point client).

**Non couvert faute de données dans l'instance jetable** (à reprendre sur une base avec activité) : création de client et « Historique du client » dans les 3 thèmes (l.504, l.508), listing de paie avec montants, contenu chiffré des états N / N-1, badge d'écart de fournée (Excédent / Équilibre / Manquant) et modale de clôture des fournées avec fournées réelles, centre de notifications.

## 4. Tickets

- Ouverts par dev-b : **aucun** (plage BUG-1140+ inutilisée).
- Vérifiés : BUG-1300, BUG-1302.
- Toujours CORRIGÉ en attente de vérification par dev-a : BUG-1122 à 1126, 1130, 1131, 1134 (tickets de dev-b).

## 5. `remarque.md`

Aucune nouvelle ligne cochée dans cette série : l.460, 464, 470, 485 attendent la vérification croisée de dev-a (rotation et clôture à midi) ; l.504 et l.508 attendent le contrôle Chrome avec données.

## 6. Points en attente du client

BUG-1132 (ventes du 1er du mois avant midi : mois précédent ou courant ?), BUG-1133 (`shift_date` hors rotation), BUG-1301, sort du mode créneaux fixes A/B, activation par défaut de `block_sales_after_closure`, délai de l'alerte Q-021, Q-051 / Q-053 (l.510, 516), Q-044 à Q-050, Q-054, Q-028, Q-043, cinq points de BUG-973.

## 7. Corrections après la série (ordre #52-A)

| Ticket | Constat | Correction | Contrôles | Statut |
|---|---|---|---|---|
| **BUG-1140** (dev-b) | Formulaire Succursales : rotation de 24 h cochée, mais les horaires fixes A/B et la suggestion « 06h00–13h00 / 13h00–20h00 » restent affichés (contradictoire avec Q-017) | Backend vérifié : en rotation, les horaires A/B ne sont plus lus (relève à `handover_time`). En rotation, les 4 champs A/B sont masqués (valeurs conservées) et remplacés par « En rotation de 24 h, les équipes se relaient à l'heure de clôture (HH:MM) ». Hors rotation : inchangé. Helper `frontend/src/utils/nodeTeamSchedule.ts`, `pages/dashboard/Nodes.tsx` | `tsc` OK ; vitest `nodeTeamSchedule.test.ts` 5 OK ; `npm run build` OK | CORRIGÉ — à vérifier par dev-a (procédure dans le registre) |

Vérification croisée des nouveaux tickets de dev-a :
- **BUG-1303** (message de blocage « direction ou le comptable ») : relecture de `treasury/closure_lock.py` + `treasury.tests.test_bug1303_message_blocage_a` et `test_dev_d38_blocage_ventes` : **Ran 17 tests — OK** → **VÉRIFIÉ**.
- **BUG-1304** (Clôture Journalière positionnée sur la journée terminée, file des clôtures en attente) : relecture de `utils/closureDay.ts` + vitest `closureDay.test.ts` **7 tests OK** → **VÉRIFIÉ** (contrôle Chrome : celui de dev-a, non refait).
