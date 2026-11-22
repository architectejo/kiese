# Plan de répartition B / C pour finir (2026-11-22)

Rédigé par le Dev B (qui a cumulé A, B et C pendant l'absence de C). A reste hors service. Branche d'intégration : `dev-b` (contient `dev-a` et `dev-c` jusqu'à `3248e29` et le travail suivant). Règles inchangées : voir `docs/PASSATION_DEV_C.md` §2 (push autonome sans `--force`, `desktop/` gelé, numérotation BUG-3NN / 4NN / 5NN, registre en Edit ciblés, `[]` → `[c]` seulement après vérification par un testeur ≠ développeur).

## Principe de partage

- **B (développement)** : tout ce qui modifie le code applicatif (`backend/`, `frontend/src/`), avec `dev-backend` et `dev-frontend`, et la documentation de livraison.
- **C (vérification)** : tout ce qui contrôle sans modifier l'application : testeurs indépendants, matrice de permissions, `remarque.md`, e2e, PR. **C ne corrige pas le code applicatif** : il ouvre un ticket `BUG-5NN` et le transmet à B (règle du dépôt : les testeurs ne corrigent pas).
- Deux personnes sur deux fichiers différents : B ne touche pas `backend/**/tests/*_c.py`, `e2e/` (sauf demande), ni `remarque.md` ; C ne touche pas au code applicatif.
- Conflits probables à éviter : `docs/qa/REGISTRE_BUGS.md` et `docs/COMMUNICATION_A_B.md` (Edit ciblés, ajout en fin de fichier, relire avant d'éditer, `git pull` avant chaque push).

## Part de B (développement)

| # | Tâche | Détail | Durée estimée |
|---|---|---|---|
| B1 | Alimentation du stock direction | petit formulaire « Approvisionner le stock direction » (ENTRY sur le stock du nœud `SIEGE`), sinon la vue globale (BUG-386/387) est inutilisable | 30–45 min |
| B2 | Synchronisation de `ConsumableInventory` | enregistrer le modèle dans `sync/` (BUG-386, hors périmètre noté) | 45 min |
| B3 | Corrections issues des tickets de C | tout `BUG-5NN` ouvert par C : B corrige avec ses propres tests, passe à `CORRIGÉ` | au fil de l'eau |
| B4 | Documentation de livraison (B-7) | manuels par rôle, guide d'exploitation (sauvegarde, migrations, incidents), procès-verbal de recette ; **sans** guide d'installation desktop | 1–2 h |
| B5 | Mise à jour de `docs/PR_dev-c_vers_main.md` | chiffres, migrations (`core/0021-0022`, `production/0027-0028`, `sales/0011-0012`, `blockchain/0002`), tickets | 20 min |
| B6 | Série complète finale et push | trois groupes, `tsc`, build, `makemigrations --check` | 45 min |

## Part de C (vérification indépendante) — **sur l'ordre du responsable**

L'ordre « testeurs » est nécessaire (règle #20/#26). Si le responsable relance C, c'est cet ordre.

| # | Tâche | Agents | Notes |
|---|---|---|---|
| C1 | Vérification des tickets `CORRIGÉ` | table de `docs/PASSATION_DEV_C.md` §3.1 | BUG-380 à 383, 385, 526 à 529, 417, 412/413, 519, 517, 523, 530 à 532, 148, 416 ; en plus : **BUG-386 et 387** (consommables direction) |
| C2 | Matrice rôles × routes | `testeur-permissions` | `core/tests/test_verif_matrice_c.py`, isolation, paramètres invalides ; ajouter les routes `consumables/global`, `dispatch`, `inventories` |
| C3 | e2e sur un poste avec navigateur | `testeur-e2e` | rejouer 05, 31, 32, 33, 34 et 35 en `--repeat-each=5` ; contrôle visuel 360 / 768 / 1440 px |
| C4 | `remarque.md` | — | `[]` → `[c]` **seulement** après `VÉRIFIÉ` ; lignes concernées : voir `PASSATION_DEV_C.md` §3.2 + ligne sur les consommables (BUG-386/387) |
| C5 | Contrôle de cohérence finale | `relecteur-code`, `auditeur-comptable` | dette frontend, résultats financiers (BUG-513/518/520 en attente du client) |
| C6 | PR `dev-c` → `main` | — | à ouvrir sur l'ordre du responsable, après C1 à C4 verts |

## Ce qui ne peut pas avancer (client)

BUG-411/507/253 (livreur), BUG-266/267/268 (commissions), BUG-513/518/520 (tarif figé, Q-028), rotation 24 h et stock de départ (BUG-161/278, lignes 460/464/470), régularisation « Non servi » (BUG-356 b), taux CM par défaut par boulangerie (ligne 452). À coder seulement après réponse du client (`docs/qa/MESSAGE_CLIENT_2026-11-21.md`, `docs/qa/QUESTIONS_CLIENT_SIMPLIFIE.md`). Hors périmètre : `desktop/`, cloud B-6 (reporté), mesure PostgreSQL de `sales/0012` (nécessite une copie de la base cloud).

## Ordre conseillé et durée

1. **B** : B1, B2, B6 partiel, push (environ 2 h).
2. **C** (en parallèle dès que B a poussé B1/B2, car la vérification porte sur du code stable) : C1 sur les tickets déjà `CORRIGÉ` (3–4 h), C2, C3.
3. **B** : B4 et B5 pendant que C vérifie, puis B3 au fil des tickets de C.
4. **C** : C4 et C6 en dernier.

Durée totale réaliste : **6 à 8 heures** de travail d'agents, dont l'essentiel est du temps de séries de tests (30 à 45 min par série complète sur ce poste). Gain attendu : les deux flux (développement et vérification) tournent en parallèle au lieu de se suivre.

## Point d'attention pour C au démarrage

- `git pull` (ou fusion de `origin/dev-b`) : `dev-b` contient tout.
- Les tests de C `@expectedFailure` ne s'ouvrent que dans les fichiers `…_c.py`.
- Environnement : voir `PASSATION_DEV_C.md` §2.6 (Python 3.14, pas de `--parallel`, sortie dans un fichier).
