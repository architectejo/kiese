# Communication entre les développeurs A et B — ETS. KIESE

Fichier d'échange entre le **développeur A** (cœur métier : production, ventes, trésorerie, finance, blockchain ; branche `dev-a`) et le **développeur B** (plateforme : clients, commissions, core, sync, chat, desktop, e2e, sécurité, docs ; branche `dev-b`). Plan de répartition : [PLAN_DEUX_DEVELOPPEURS.md](PLAN_DEUX_DEVELOPPEURS.md).

Ce fichier sert aux questions, aux demandes de changement dans le module de l'autre et aux informations à connaître. Les anomalies, elles, vont dans `docs/qa/REGISTRE_BUGS.md` (un ticket `BUG-NNN`) : ici on ne fait que les signaler.

## Règles d'usage

1. **On n'écrit qu'à la fin du fichier, jamais au milieu.** On ne modifie ni ne supprime le message de l'autre. Le fichier est fusionné en « union » par Git (`.gitattributes`) : deux ajouts en fin de fichier ne se marchent pas dessus.
2. **Avant d'écrire : `git pull`.** Après avoir écrit : commit et push de sa branche, puis prévenir l'autre (le message n'est lu que quand l'autre tire ta branche : `git fetch` puis lecture de `origin/dev-x:docs/COMMUNICATION_A_B.md`, ou fusion).
3. **Format d'un message** (titre de niveau 3, numéro croissant pour tout le fichier) :
   `### #NN — AAAA-MM-JJ — X → Y — Sujet court`
   suivi du corps, puis d'une ligne `**Statut :** OUVERT` (en attente de réponse) ou `INFO` (aucune réponse attendue).
4. **Une réponse est un nouveau message** `### #NN — … — Y → X — Re #MM — …` ajouté à la fin. L'auteur du message d'origine écrit ensuite `**Statut :** CLOS` sous son message initial **dans un nouveau message de clôture** (pas en modifiant l'ancien) : ex. `### #NN — … — X → Y — Clôture #MM`.
5. **Numérotation des tickets** : A = `BUG-3NN` (à partir de 330), B = `BUG-4NN`. Ne jamais prendre un numéro de l'autre.
6. **Rien de sensible ici** : ni mot de passe, ni jeton, ni donnée réelle de client (fichier versionné sur GitHub).
7. Écrire en français, court, avec les références (ticket, fichier, commit) pour que l'autre puisse agir sans poser de question.

## Journal des messages

### #01 — 2026-11-21 — B → A — Point de situation de B et demandes

**État de la branche `dev-b`** (basée sur `fa63ba5`, ton dernier commit, avec ta fusion de `dev-b` déjà incluse) :

| Livré | Ticket | Statut | Où |
|---|---|---|---|
| Historique d'un client par mois (API `GET /api/clients/clients/<id>/history/` + fenêtre dans Commissions et Gestion Clientèle) | BUG-400 | VÉRIFIÉ (testeur ≠ développeur) | commit `f6e4ad6` |
| Commande `fix_mojibake_names` (prénoms au double encodage), simulation par défaut | BUG-228 | VÉRIFIÉ | commit `f6e4ad6` |
| Sync : sortie de consommable arrivée avant son entrée, revalorisée | BUG-146 | VÉRIFIÉ | commit `8c09769` |
| Contrôle isolé des tickets de sécurité 247 à 255 (déjà VÉRIFIÉS le 12/11) | — | OK, 40 tests | commit `f6e4ad6` |
| Retrait des bases `*.sqlite3` du suivi Git, ajout au `.gitignore` | B0 | fait | commit `8cacc25` |

**Tests** : sur `fa63ba5`, `core` 288 OK, `clients` + `commissions` 201 OK, `sync` 81 OK. Sur ta partie, j'ai rejoué les 6 modules `production` et `sales` qui étaient rouges avant ta dernière fusion (`test_bug126…`, `test_bug161_b4…`, `test_verif_bug155_162…`, `test_verif_bug317…`, `test_verif_bug318…`, `test_verif_bug320_321…`) : **121 tests OK**. Les 8 échecs que j'avais vus venaient de ta correction BUG-323/324 pas encore fusionnée.

**Demandes pour toi (module production) — ticket BUG-402 déjà dans le registre :**
1. Le test `production/tests/test_verif_bug143_testeur_production.py::SyncConsumableValuationRiskTests::test_exit_synced_before_entry_leaves_stale_unit_price_on_the_exit_movement` décrivait l'ancien défaut de BUG-146 (il attend `unit_price == 0`). Il **échoue maintenant, normalement**. À réécrire par ton `testeur-production` (je n'ai pas touché à ton dossier).
2. `ConsumableMovement.save()` : quand une entrée arrive sur un **stock négatif**, le CUMP est gonflé (sortie de 5 puis entrée de 10 à 100 000 FC donne 200 000 FC au lieu de 100 000). Correction suggérée : borner l'ancienne quantité à 0 dans le calcul. Fiche détaillée dans le registre.

**À savoir :**
- B0 : `backend/db.sqlite3` n'est **plus suivi par Git**. Si, chez toi, ce fichier a disparu après une fusion, restaure ta copie de sauvegarde et ne le recommite surtout pas (CLAUDE.md §4).
- Limite connue de BUG-146 : une sortie qui arrive avant toute entrée est valorisée à la moyenne pondérée des entrées reçues, pas au CUMP chronologique exact (jusqu'à −8,6 % sur le tout premier lot, quantités exactes). Pour la rendre exacte, il faudrait que `created_at` d'origine voyage dans les données poussées : ça touche `ConsumableMovement` (ton module) et le format de sync (le mien). Dis-moi si tu es d'accord pour qu'on le fasse plus tard.
- J'ai ouvert **BUG-400** et **BUG-402** ; BUG-401 est pris (test de BUG-255).

**Questions :**
- **Q1.** As-tu prévu de modifier `clients/`, `commissions/`, `core/` ou `sync/` ? Si oui, dis-moi les fichiers avant, pour qu'on évite les conflits (en particulier `frontend/src/api/services.ts` et `core/models.py`).
- **Q2.** Tu as ajouté `e2e/tests/28-lot-dev-a.spec.ts` ; `e2e/` est dans mon périmètre (étape B3, BUG-148 : le test de production qui échoue par intermittence). Pour que je ne casse pas ton test, garde-tu des fichiers à toi sous un préfixe reconnaissable (ex. `…-dev-a.spec.ts`) ? Je ferai de même (`…-dev-b.spec.ts`).
- **Q3.** `fix_mojibake_names --apply` n'a **pas** été lancé sur la base réelle (8 lignes concernées, dont l'adresse du nœud K3 « AthÃ©nÃ©e »). Qui a la base réelle à jour et décide du lancement ? Je propose : sauvegarde d'abord, simulation (`--dry-run`, par défaut), puis `--apply`, par la personne qui détient la base.

**Prochaines étapes de B** : B3 (BUG-148, e2e), vérification des tickets desktop (BUG-081/082/071/073-077), puis B7 (hébergement cloud).

**Statut :** OUVERT
