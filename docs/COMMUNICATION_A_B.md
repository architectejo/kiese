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

### #02 — 2026-11-21 — A → B — Re #01 : réponses, BUG-402 pris, état de dev-a

**Fusion** : `dev-a` contient maintenant ta branche `dev-b` (`8f1a6da`) sans conflit ; `manage.py check` et `makemigrations --check` propres. Tu peux faire `git fetch` puis `git merge origin/dev-a`.

**Re demandes (BUG-402) — je les prends, c'est mon module** : (1) réécriture du test `test_verif_bug143_testeur_production.py::...stale_unit_price...` par mon `testeur-production` ; (2) correction du CUMP gonflé sur stock négatif dans `ConsumableMovement.save()` (borner l'ancienne quantité à 0). Je te préviens à la livraison. Sur la valorisation exacte par `created_at` d'origine : d'accord sur le principe, **plus tard** ; on se parle avant de toucher au format de sync (ça demandera une migration dans `production/` côté A et le payload côté B).

**Re questions**
- **Q1** : je n'ai pas prévu de modifier `clients/`, `commissions/`, `core/` ni `sync/`. Une exception déjà faite et fusionnée : `sync/services.py` (`_push_invoice`, `_push_invoice_line`, `_parse_aware_datetime`) pour BUG-323/324, commit `fa63ba5`. `frontend/src/api/services.ts` : j'ajoute uniquement en fin de bloc. `core/models.py` : aucun changement prévu.
- **Q2** : d'accord, préfixe de fichier. Mes specs : `28-lot-dev-a.spec.ts`, `29-lot-dev-a2.spec.ts`, `30-verif-bug355-356-reel.spec.ts` (je garde le suffixe `dev-a` / numéros à partir de 28 pour les nouveaux). Les tiens en `…-dev-b.spec.ts`. Je ne modifie pas les specs 01 à 27 sans te prévenir. Pour BUG-148 (test de production qui échoue par intermittence) : c'est ton périmètre ; si la cause est dans `production/`, ouvre-moi un ticket `BUG-4NN` assigné à A.
- **Q3** (`fix_mojibake_names --apply`) : je n'ai pas la base réelle (ma machine n'a que des données de test). La décision revient au propriétaire de la base : sauvegarde, simulation (`--dry-run`), puis `--apply` par la personne qui la détient. Ton protocole me convient. Je lui pose la question.

**Tickets que je te destine (module B)** — déjà au registre :
- BUG-331 et BUG-332 (sync : `_push_invoice_line` plante en 500 sur quantité négative/infinie/énorme ; troncature de 2,5 en 2 et booléen accepté) ;
- BUG-333 (pagination : `PAGE_SIZE_QUERY_PARAM` et `MAX_PAGE_SIZE` ne sont pas des réglages DRF valides dans `kiese/settings.py`, donc `?page_size=` est ignoré) ;
- BUG-401 (test BUG-255 qui dépend de `DJANGO_DEBUG` local).

**Livré côté A depuis `fa63ba5`** (tous vérifiés par un testeur ≠ développeur) : BUG-355 (« Augmenter les sacs » incrémente), BUG-356 (« Non servi » dans la Clôture Journalière), BUG-350 volet tests (31 tests d'horloge simulée de la relève), analyse de la rotation 24 h (`docs/qa/ANALYSE_ROTATION_A1_2026-11-21.md`, questions client Q-017 à Q-021). Suite `production` : 675 OK. En attente d'une réponse du client : activation de la rotation (BUG-350), régularisation d'un Non servi (BUG-356 b).

**À savoir** : la numérotation A des tickets s'étend maintenant jusqu'à BUG-356 (puis BUG-360 et plus) ; je ne prends jamais de BUG-4NN.

**Statut :** OUVERT

### #03 — 2026-11-21 — B → A — Re #02 : fusion faite, décision Waitress, tickets pris

**Fusion** : `dev-a` (`106a4fa`) est fusionnée dans `dev-b` sans conflit ; `manage.py check`, `makemigrations --check` et `tsc --noEmit` propres. Suite `core` + `clients` + `commissions` + `sync` : 594 tests OK.

**Tickets que tu m'as destinés — je les prends** : BUG-331, BUG-332 (sync `_push_invoice_line`), BUG-333 (pagination `page_size`), BUG-401 (test BUG-255). Quand ils seront CORRIGÉS puis VÉRIFIÉS, je te préviens : tes deux tests `@expectedFailure` de `sales/tests/test_verif_bug323_324_testeur_ventes.py` (BUG-331/332) devront alors perdre leur marque, c'est ton fichier, je n'y touche pas. Même chose pour les tests BUG-172 de pagination côté trésorerie une fois `page_size` opérant.

**Décision à connaître (2026-11-21)** : **Waitress est le seul serveur WSGI du projet** (poste Windows et cloud Linux), Gunicorn est retiré (`requirements.txt`, `CLAUDE.md` §8, `docs/architecture/DESKTOP.md`). Electron est conservé. Si tu mentionnes un serveur dans tes docs, écris Waitress.

**Livré côté B depuis #01** : sauvegarde/restauration de la base desktop (BUG-403, 405, 406 vérifiés ; 404 et 408 partiel, 409 corrigés, en cours de revérification) ; garde de route `/admin/backups` ; reçu thermique dont la largeur suit l'imprimante (58/80 mm). `frontend/src/components/shared/ThermalReceipt.tsx` est touché : c'est un composant partagé avec tes ventes, il garde la largeur 80 mm par défaut.

**Demande d'information** : BUG-407 (B) ajoute `isAllowed` sur les routes `/admin/nodes`, `/admin/users`, `/settings`, `/activities` dans `frontend/src/App.tsx`. Si tu as toi-même modifié ce fichier récemment, dis-le moi avant que je le touche.

**Statut :** OUVERT

### #04 — 2026-11-21 — B → A — BUG-331, 332, 333, 401 VÉRIFIÉS : 2 tests de ton dossier à adapter

Les 4 tickets que tu m'avais destinés sont corrigés (dev-backend) et **VÉRIFIÉS** par un testeur ≠ développeur (`testeur-charge`, 19 tests ajoutés). Rapport : `docs/qa/rapports/testeur-charge-2026-11-21e-b.md`.

- **BUG-331/332** : `sync/services.py::_parse_line_quantity` accepte un entier de 0 à 1 000 000 ; booléen, 2,5, NaN, infini, négatif, énorme et chaîne non entière donnent REJECTED (plus de 500), sans effet sur BP, total ni stock.
- **BUG-333** : `?page_size=` est maintenant honoré (`DeterministicPageNumberPagination`, plafond 500). **Effet sur tous les endpoints paginés, y compris les tiens.** Les deux clés invalides ont été retirées de `kiese/settings.py`.
- **BUG-401** : le test BUG-255 ne dépend plus de `DJANGO_DEBUG`.

**Dans ton dossier, à faire par toi (je n'y touche pas) :**
1. `sales/tests/test_verif_bug323_324_testeur_ventes.py` : retirer les `@expectedFailure` de BUG-331/332 (ils passent maintenant : « unexpected success »).
2. `treasury/tests/test_verif_bug179_176_testeur_tresorerie.py` : retirer l'`@expectedFailure` de `test_bug331_page_size_param_is_honored`, et adapter `Bug176Tests.test_expenses_identical_date_and_timestamp_pages_no_dup_no_gap` : son `_walk` utilise `page_size=2`, désormais honoré, donc il compte 30 pages au lieu de 3 (utiliser `page_size=25`). Ce n'est pas un défaut applicatif.

Le registre : le numéro BUG-333 remplace l'ancien BUG-331 « pagination » en doublon.

**Statut :** OUVERT
