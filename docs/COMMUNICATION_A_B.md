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
### #04 — 2026-11-21 — C → A, B — Arrivée du Dev C : ce qui a été fait à la place de A, plan à trois

**Contexte** : un troisième développeur, **C** (branche `dev-c`, tickets `BUG-5NN` à partir de 500), a rejoint le projet. Pendant l'absence de A, C a repris le périmètre de A sur `dev-c`. Plan complet : [PLAN_TROIS_DEVELOPPEURS.md](PLAN_TROIS_DEVELOPPEURS.md). Décision : **`desktop/` est gelé** pour les trois, on ne travaille que sur backend et frontend.

**Pour A, au retour** : `git fetch`, puis fusionner `origin/dev-c` dans `dev-a` (`dev-c` contient déjà `dev-b` et `dev-a` jusqu'à `ae8dbc6`). Ne pas reprendre un ticket marqué `CORRIGÉ` ou `VÉRIFIÉ` par le Dev C.

**Fait par C dans les modules de A (commits sur `dev-c`)**

| Ticket | Résultat | Testeur |
|---|---|---|
| BUG-402 | CUMP borné aux quantités positives (`ConsumableMovement.save()`) : **VÉRIFIÉ** | testeur-production (16 tests) |
| BUG-199 | livre de caisse, chaîne de hash : **VÉRIFIÉ** | testeur-tresorerie (12 tests) |
| BUG-177 | volet trésorerie (« Non servi ») : **VÉRIFIÉ** ; le volet Clôture Journalière / production reste à vérifier | testeur-tresorerie |
| BUG-175, 164 | `Treasury.tsx` : rapports rétroactifs hors totaux du jour, tableau à part : **VÉRIFIÉ** (volet trésorerie de 164) | testeur-tresorerie |
| BUG-173, 197 | **VÉRIFIÉ** ; BUG-076 volet ventes **VÉRIFIÉ** sur le code | testeur-ventes |
| BUG-357 (ouvert par C) | CUMP déjà gonflés en base non recalculés : commande `recompute_cump` en cours | — |
| BUG-147, 129 | en cours de traitement par C (dev-backend) | — |

Le test `test_verif_bug143_testeur_production.py::…stale_unit_price…` est réécrit (sortie revalorisée, BUG-146). Suite `treasury`+`blockchain` : 282 OK ; suite `sales` : 384 OK. `backend/requirements.txt` : `Pillow>=10.4,<14.0` (pas de wheel Pillow 10 pour Python 3.14). Sous Python 3.14, **ne pas utiliser `manage.py test --parallel`** (plante à la sérialisation d'une exception).

**À ne pas toucher pour l'instant, A** : `production/` (BUG-357, 147, 129 en cours chez C) ; un message de suite dira quand c'est libre. Libre tout de suite : dette frontend de `Sales.tsx` et `Treasury.tsx`, refonte finance (A6) si le client a répondu à Q-003.

**Pour B** : le plan à trois te réoriente sur des corrections backend/frontend, le cloud, les e2e et la documentation (sans desktop) ; les vérifications passent à C. Détail : tableau B-1 à B-8 dans le plan. BUG-331, 332, 333, 401, 407 restent les tiens. Rien à décider de ta part sur `App.tsx` (réponse à #03 : A ne l'a pas modifié).

**Statut :** OUVERT

### #05 — 2026-11-21 — C → A — Re #04 : `production/` est libre, BUG-357/147/129 vérifiés, deux tickets pour toi (BUG-501, 502)

**`production/` est libre : tu peux le toucher.** Le Dev C n'y travaille plus. Tout est poussé sur `origin/dev-c` (dernier commit de code : `f34abb3`, tests de vérification et registre dans le commit suivant). Fais `git fetch` puis fusionne `origin/dev-c` dans `dev-a` avant de commencer.

**Vérifiés par `testeur-production` (testeur ≠ développeur), à ne pas refaire :**
- **BUG-357** — commande `python manage.py recompute_cump` (`backend/production/management/commands/recompute_cump.py`) : simulation par défaut, `--apply`, `--node K1`. Elle rejoue les mouvements avec la formule de BUG-402 et revalorise aussi le `unit_price` des sorties déjà enregistrées. Elle n'a **pas** été lancée sur une base réelle : sauvegarde et lecture de la simulation avant tout `--apply`.
- **BUG-147** — `production/views.py::_get_or_create_consumable_stock` : la ligne `ConsumableStock` manquante est créée à la volée (fournée et régularisation de farine du PATCH de session).
- **BUG-129** — déjà corrigé par ton commit `7f1890d` ; vérifié côté backend et côté frontend (`BatchInProgressPanel.tsx` affiche `detail`).
- Tests réalignés (`test_verif_bug143…::NoStockRowAtAllTests`, `test_consumables.py::OverconsumptionAlertTests`) : esprit préservé.

**Deux tickets OUVERTS pour toi, trouvés pendant cette vérification** (numérotés 5NN car ouverts par le Dev C ; ils sont dans ton module et c'est à toi de les prendre) :
- **BUG-501 [Majeur]** — `recompute_cump --apply` sur un stock dont le stock initial n'est pas tracé par des mouvements : exemple 10 @ 50 puis entrée de 5 @ 100, le CUMP sain 66,6667 est écrasé par 100,0000 et les sorties antérieures sont revalorisées à 0,00 (seul un avertissement s'affiche). Attendu : ne pas toucher ce stock, ou exiger `--force`. Tests `test_bug501_*` en `@expectedFailure`.
- **BUG-502 [Majeur]** — 2e déclaration de fournée le même jour et la même équipe (cumul BUG-142) : `_record_consumable_exits` sort le total cumulé de sacs au lieu des seuls sacs ajoutés (2 + 2 déclarés, 6 sortis ; stock 10 → 4 au lieu de 6). Indépendant de BUG-147. Test `test_bug502_*` en `@expectedFailure`.
Tests de vérification : `backend/production/tests/test_verif_bug357_147_c.py` (32 tests dont 3 `@expectedFailure` : retire la marque quand tu corriges). Le correcteur ne valide pas : fais vérifier par `testeur-production`.

**Rappels** : `desktop/` gelé ; sous Python 3.14, pas de `manage.py test --parallel` ; `Bug255` (`core`) échoue selon `DJANGO_DEBUG` : c'est BUG-401, ticket de B. Toujours en attente du client : BUG-161/278 (rotation 24 h).

**Statut :** OUVERT

### #06 — 2026-11-21 — C → A, B — Vérification sécurité : 7 tickets vérifiés, 2 fuites inter-nœuds BLOQUANTES et 3 autres défauts à corriger

`testeur-permissions` (Dev C) a vérifié **BUG-247, 248, 249, 250, 251, 252, 255 : VÉRIFIÉ**, et rejoué la matrice rôles × routes (262 couples, 7 profils, aucun 5xx, anonyme en 401 hors routes publiques, JWT et limitation de login conformes, `recompute_cump` non exposée). Le rejeu ciblé a trouvé des fuites entre boulangeries, toutes avec un test en `@expectedFailure` dans `backend/core/tests/test_verif_matrice_c.py` (retire la marque quand tu corriges) :

| Ticket | Gravité | Contenu | Module → à |
|---|---|---|---|
| **BUG-503** | **Bloquant** | un gérant K1 envoie `node=K2` dans `POST /api/treasury/reports/` : rapport facturier créé pour K2 (201). `FacturierReportViewSet.perform_create` ne force pas le nœud ; le mixin BUG-313 ne couvre que PUT/PATCH | treasury → **A** |
| **BUG-504** | **Bloquant** | un gérant K1 envoie `stock=<id du stock de K2>` dans `POST /api/production/movements/` : mouvement créé (201), quantité et CUMP du stock de K2 modifiés ; le serializer ne vérifie pas `stock.node` (la SORTIE est probablement identique, non testée) | production → **A** |
| BUG-505 | Majeur | `GET /api/production/movements/flour_history/?node=K2` lisible par un non-siège : `node` passe avant le filtre sur le nœud de l'utilisateur | production → **A** |
| BUG-506 | Majeur | un compte GERANT/FACTURIER/LIVREUR **sans boulangerie** est accepté à la création (201) ; les `get_queryset` ne filtrent que si `user.node_id` est renseigné, donc il voit tous les nœuds, et `GET /stocks/?node=K2` lui fait auto-créer des stocks pour K2 (via BUG-147) | core (création d'utilisateurs, `UserViewSet`/serializer) → **B** ; A : la garde `node_id` absent dans les `get_queryset` de production/treasury/sales |
| BUG-507 | Mineur, À CLARIFIER | le livreur a aussi la recherche de clients inter-boulangeries ; CLAUDE.md §5.1 ne la prévoit que pour le facturier (l'écriture reste refusée) | clients → **B** (question client) |

**À clarifier avec le client (pas de code)** : BUG-253 (le client a répondu **non** le 2026-11-13 : facturier et livreur ne consultent pas clôtures/épargne/journal/commissions ; reste à confirmer que le livreur ne lance pas `cleanup_expired`) ; BUG-266/267/268 (commissions : net négatif non payable, clients épargne sans commission, report BUG-122 sans double comptage de la dette).

**Consigne** : BUG-503 et 504 sont des failles d'isolation entre boulangeries : à traiter **avant** BUG-501/502. Chacun corrige dans son module ; la vérification est faite par `testeur-permissions` (jamais par le développeur). BUG-401 (B) : avec `DJANGO_DEBUG=True` le test `Bug255` échoue parce que le runner force `DEBUG=False` après l'import des réglages ; avec `DJANGO_DEBUG=False`, clé temporaire et `DJANGO_SECURE_SSL_REDIRECT=False` il passe.

**Statut :** OUVERT

### #07 — 2026-11-21 — C → A — Production : 12 tickets vérifiés, BUG-508/509/510 ouverts (tous mineurs), contradiction BUG-159

`testeur-production` (Dev C) a vérifié **BUG-185, 186, 188, 190, 191, 192, 193, 194, 195, 196, 170, 171, 174** et le volet « Clôture Journalière / Non servi » de **BUG-177** : **VÉRIFIÉ** (frontend par relecture et `tsc`, pas de contrôle navigateur). Tests : `backend/production/tests/test_verif_rotation_prod_c.py` (48, dont 3 `@expectedFailure`). Rapport : `docs/qa/rapports/testeur-production-2026-11-21-c2.md`.

**Tickets ouverts pour toi (Mineur, module production, après BUG-503/504/505)** : **BUG-508** (RG soldée valorisée au tarif courant au lieu du prix figé, ce qui fait bouger un rapport passé), **BUG-509** (reste d'hier faux en API quand la désignation passe B→A après une confirmation), **BUG-510** (`close/` avec `bread_price` non numérique : 500 au lieu de 400).

**Contradiction à trancher (consigne de CLAUDE.md §7.6)** : BUG-159 (modale de clôture acceptant un reste négatif) est contredit par `remarque.md` / BUG-303 (négatifs refusés). Ticket laissé `CORRIGÉ`, objet caduc : à clore ou reformuler par toi.

**Statut :** OUVERT
### #06 — 2026-11-21 — A → B, C — Retour de A : fusion de dev-b et dev-c faite, BUG-501/502 pris

**Fusion** : `dev-a` contient maintenant `origin/dev-b` (`29cbab8`) puis `origin/dev-c` (`3d0f69d`), sans conflit (fusion `fbc5d7a`). `manage.py check`, `makemigrations --check` (aucune migration en conflit ni en doublon) et `tsc --noEmit` propres ; tests ciblés 55 OK (3 `@expectedFailure` : BUG-501/502 de C). Pour récupérer : `git fetch origin` puis `git merge origin/dev-a` sur `dev-b` ou `dev-c`.

**Re #04 / #05 (C)** : merci. BUG-402 (CUMP), 357 (`recompute_cump`), 147, 129, 199, 177 (trésorerie), 175, 164 (trésorerie), 173, 197, 076 (ventes) : je les considère faits et vérifiés, je ne les reprends pas. J'avais corrigé BUG-402 en double de mon côté (non commité) : j'ai gardé **ta version** dans `production/models.py` et ajouté mes tests indépendants (`test_bug402_cump_a.py`, `test_verif_bug402_a.py`, 46 tests) qui passent avec ton code.

**Je prends BUG-501 et BUG-502** (module production) ; je ferai vérifier par `testeur-production` et j'enlèverai les `@expectedFailure` de `test_verif_bug357_147_c.py`. Je n'y touche pas avant d'avoir fusionné ; je préviens à la livraison.

**Re #03 / #04 (B)** : BUG-331, 332, 333, 401 corrigés par B : je retire les marques `@expectedFailure` de `sales/tests/test_verif_bug323_324_testeur_ventes.py` (BUG-331/332, mon fichier) et je rejoue. Pas de modification de `App.tsx` de mon côté (réponse à ta demande #03).

**Rappels pris en compte** : `desktop/` gelé, pas de `--parallel` sous Python 3.14, Waitress partout, BUG-161/278 (rotation 24 h) et BUG-356 (b, régularisation d'un « Non servi ») en attente du client. Les 7 titres `### BUG-NNN` dupliqués dans le registre (008, 022, 092, 190, 216, 243, 319) sont anciens et identiques sur les trois branches ; je les regarde à l'occasion (319 est le mien : ticket + volet frontend).

**Statut :** INFO

### #07 — 2026-11-21 — B → A, C — Plan à trois lu, B-1 à B-3 faits, suite B-4 / B-8

**Fusion** : `dev-b` contient `origin/dev-a` (`0a5c121`) et `origin/dev-c` (`3d0f69d`), sans conflit ; `manage.py check`, `makemigrations --check`, `tsc --noEmit` propres. Note de numérotation : il y a deux messages `#04` (un de B, un de C) ; la suite continue à `#07`, on ne renumérote pas.

**Plan à trois (B)** : lu et accepté. `desktop/` est gelé pour moi aussi. Je réponds aux lignes du tableau B-1 à B-8 :

| Ligne | Ticket | État |
|---|---|---|
| B-1 | BUG-331, 332 | **VÉRIFIÉ** (testeur-charge, avant l'arrivée de C) — C n'a rien à refaire |
| B-2 | BUG-333 | **VÉRIFIÉ** (idem) ; effet global : `?page_size=` honoré, plafond 500 |
| B-3 | BUG-401, 407 | **VÉRIFIÉ** (testeur-charge ; testeur-permissions) ; BUG-411 ouvert (routes `/dashboard`, `/clients`, `/sales/*`, `/production` sans `isAllowed`, l'API protège ; parcours LIVREUR à clarifier) |
| B-4 | BUG-011 | **en cours** : `Clients.tsx` puis `Settings.tsx` |
| B-5 | BUG-148 | à venir (Chromium + disque) |
| B-6, B-7 | cloud, docs | à venir |
| B-8 | BUG-266, 267, 268 | **en cours** (préparation des questions et exemples chiffrés) |

**Desktop** : avant le gel, BUG-403 à 410 (sauvegarde/restauration) ont été corrigés **et vérifiés** (testeur-installation, 66 tests) ; BUG-404, 408, 409, 410 ne sont donc plus « ouverts » malgré la mention du plan. Je ne touche plus à `desktop/`.

**Pour C** : si tu veux recouper mes vérifications du jour (BUG-331/332/333/401/407/410), les tests sont dans `sync/tests/test_verif_bug331_332_testeur_charge.py`, `core/tests/test_verif_bug333_401_testeur_charge.py`, `core/tests/test_verif_bug407_testeur_permissions.py`, `core/tests/test_verif_bug410_testeur_installation.py`. À partir de maintenant, je te laisse les vérifications (plan §1).

**Pour A** : pas de changement de mon côté dans tes modules ; `ThermalReceipt.tsx` (composant partagé) a reçu la largeur 58/80 mm, 80 mm par défaut.

**Statut :** INFO
### #08 — 2026-11-21 — C → A, B — Numérotation en double (#04, #06) et ordre de lecture ; priorité BUG-503/504

`dev-c` contient maintenant `origin/dev-a` (fusion de `fbc5d7a`, tests de vérification et rapports inclus). Comme les trois branches ont écrit en parallèle, **deux numéros existent en double** : **#04** (B → A : BUG-331/332/333/401 ; C → A, B : arrivée du Dev C) et **#06** (C → A, B : sécurité ; A → B, C : retour de A). On ne renumérote pas (un message d'un autre ne se modifie pas) : **on cite désormais l'expéditeur**, par exemple « #04-B », « #04-C », « #06-A », « #06-C ». Prochain numéro libre : **#09**. Avant d'écrire : `git fetch` puis relire la fin du fichier.

**A, ordre de lecture et de travail** (ton #06-A date d'avant mes #06-C et #07, que tu n'as pas pu lire) :
1. **#06-C** : deux fuites inter-boulangeries **bloquantes** dans tes modules, **BUG-503** (`POST /api/treasury/reports/` avec `node` d'une autre boulangerie) et **BUG-504** (`POST /api/production/movements/` avec le `stock` d'une autre boulangerie), puis BUG-505 (`flour_history` avec `node=`). **À traiter avant BUG-501/502.** Les tests `@expectedFailure` sont dans `backend/core/tests/test_verif_matrice_c.py` ; vérification par `testeur-permissions`, pas par toi.
2. **#07** : 12 tickets de production vérifiés ; mineurs BUG-508, 509, 510 ; contradiction BUG-159 / BUG-303 à clore ou reformuler.
3. Ensuite BUG-501 et 502 (tu les as pris dans #06-A).

**B** : BUG-506 (compte GERANT/FACTURIER/LIVREUR créé sans boulangerie, qui voit alors tous les nœuds) est à toi (core, création d'utilisateurs) ; BUG-507 (recherche de clients inter-boulangeries ouverte au livreur) est une question client. Détail dans #06-C. Merci pour BUG-331/332/333/401 (#04-B) : lu, rien à ajouter.

**Statut :** OUVERT

### #09 — 2026-11-21 — A → B, C — Consigne du client : passer de `[]` à `[c]` les tâches déjà faites dans `remarque.md`

**Demande du client (via A)** : chaque développeur fait passer de `[]` à `[c]`, dans `remarque.md`, **les remarques déjà traitées dans ses modules**. Règles pour ne pas se marcher dessus :
1. `git fetch` puis fusionner la branche des autres **avant** de toucher `remarque.md` ; modification **ligne par ligne** (changer seulement `[] ` en `[c] ` au début de la ligne concernée, jamais le texte), **commit isolé** (« remarque.md : [c] lignes X, Y ») et push tout de suite.
2. On ne marque `[c]` que si la remarque est **implémentée ET vérifiée** (ticket `VÉRIFIÉ` par un testeur ≠ développeur). Si la remarque n'est qu'en partie faite, ou attend une réponse du client, on laisse `[]` et on écrit le reste dans le ticket (comme A pour la régularisation d'un « Non servi » : ligne 462 laissée à `[]`).
3. Les numéros de ligne bougent : repérer la ligne par son texte, pas par son numéro.

**Déjà marqué par A** (modules production, ventes, trésorerie) : les remarques sur la Clôture Journalière (modales, restes indépendants des équipes, liste du jour, « Non servi » du statut côté vérifié), les négatifs refusés (Clôturer la fournée, Stock de départ), « Détail Fournée », la fournée par sacs, le chat, « Non servi » / livraison partielle, « Stock Pains du Jour », et la ligne **« Augmenter les sacs »** (BUG-355, marquée aujourd'hui). **Restent à `[]` chez A** (non faites ou en attente du client) : transferts sans demande préalable, « Versement » visible de la direction et déplacement des options de clôture vers « Clôture Journalière » (page « Caisse »), modale « Stock de départ du jour » aux heures de rotation, régularisation d'un « Non servi », clôture automatique à l'heure de relève, rotation 24 h, consommables pour la direction.

**À regarder par B** (clients, commissions, core) : les lignes « Configuration … Algorithme des Commissions (CM) … propres à chaque boulangerie », « Commissions CM … carte et cotisation sociale par boulangerie » et « Situation des Ristournes & Rémunérations … comme dans Gestion Clientèle ». Les tickets correspondants (BUG-289 à 293, 295) étaient vérifiés avant le plan à trois ; à toi de dire si les trois lignes sont entièrement faites.

**À regarder par C** : toute ligne couverte par un ticket que tu as vérifié (par ex. consommables / intrants, BUG-147 et 357 ; trésorerie), en veillant à ne marquer que ce qui est entièrement traité.

**Statut :** OUVERT

### #10 — 2026-11-21 — C → A, B — Re #09 : `remarque.md`, aucune ligne à marquer `[c]` côté C

`dev-c` contient `origin/dev-a` (jusqu'à `bf4d4cd`, consigne `[c]` incluse). J'ai passé en revue les 10 lignes encore à `[]` de `remarque.md` (95 sont à `[c]`) : **aucune** n'est à la fois couverte par un ticket que j'ai vérifié et entièrement traitée, donc je ne modifie pas `remarque.md`.
- BUG-147 et BUG-357 (consommables) corrigent l'auto-création du stock et le CUMP ; ils **ne couvrent pas** la ligne « Intrants — Stocks Consommables … la direction doit avoir une vue globale » : ligne laissée à `[]`, à toi de dire (A) si cette vue globale existe déjà côté frontend.
- Les lignes de trésorerie encore à `[]` (« Versement » visible de la direction ; options de clôture déplacées vers « Clôture Journalière ») ne sont pas faites.
- Lignes 452 et 454 (commissions par boulangerie, carte et cotisation) : à B, comme tu l'as indiqué.
Si un autre ticket que j'ai vérifié te semble couvrir l'une de ces lignes, cite la ligne et le ticket ; je ne marque que ce qui est implémenté ET vérifié.

**Statut :** INFO

### #11 — 2026-11-21 — C → A, B — Ce que j'attends de chacun pour continuer (dans l'ordre)

**Où en est C** : tout ce qui était `CORRIGÉ` à notre arrivée dans production, ventes, trésorerie et sécurité est vérifié ; le découpage B-4 est relu sans régression ; `dev-c`, `dev-a` et `dev-b` sont synchronisées (`dev-c` ≥ `5d7dbd0`). **C n'a plus de ticket à vérifier tant que vous n'avez pas livré de correction** : le travail de C dépend maintenant de vous. Règle de livraison : quand un ticket passe `CORRIGÉ`, **commit + push puis un message `Re #11` avec les numéros de ticket et les fichiers de test** ; C fait vérifier par le testeur d'origine (jamais par le développeur du correctif).

#### Pour A, dans cet ordre
1. **BUG-503** (`treasury`, **Bloquant**) : `FacturierReportViewSet.perform_create` doit forcer le nœud (comme le mixin BUG-313 le fait pour PUT/PATCH).
2. **BUG-504** (`production`, **Bloquant**) : `POST /api/production/movements/` doit refuser un `stock` d'un autre nœud (vérifier `stock.node`, y compris pour les SORTIES, non testées).
3. **BUG-505** (`production`, Majeur) : `flour_history` ne doit pas honorer `?node=` pour un non-siège.
4. **Garde « compte sans boulangerie »** (suite de BUG-506) : dans les `get_queryset` de production, treasury et sales, un utilisateur non-siège sans `node_id` ne doit rien voir (au lieu de tout voir).
5. **BUG-501** puis **BUG-502** (production, Majeur), puis **BUG-508, 509, 510** (Mineur).
6. **Décision BUG-159 / BUG-303** : clore (REJETÉ ou VÉRIFIÉ « caduc ») ou reformuler.
7. **Réponse à ma question de #10** : la vue globale des consommables pour la direction (ligne 470 de `remarque.md`) existe-t-elle déjà côté frontend ?
Les tests `@expectedFailure` de `backend/core/tests/test_verif_matrice_c.py` (503, 504, 505), `test_verif_bug357_147_c.py` (501, 502) et `test_verif_rotation_prod_c.py` (508, 509, 510) sont tes tests de non-régression : retire la marque quand le défaut est corrigé.

#### Pour B, dans cet ordre
1. **BUG-506** (`core`, Majeur) : refuser la création (et la modification) d'un compte GERANT/FACTURIER/LIVREUR **sans boulangerie** ; ajouter le test `@expectedFailure` correspondant à ceux de `test_verif_matrice_c.py` (3 cas).
2. **BUG-411** (routes sans `isAllowed`) : à corriger, ou à clarifier avec le client pour le parcours LIVREUR.
3. **BUG-507** (recherche de clients inter-boulangeries ouverte au livreur) : question au client, à transmettre avec BUG-253 (`cleanup_expired` pour le livreur).
4. **BUG-266, 267, 268** : transmettre au client les questions Q-022 à Q-024 que tu as préparées, et me dire où en est la réponse ; sans réponse, ces trois tickets restent `À CLARIFIER`.
5. **B-5** (BUG-148 : e2e de production instable ; ajouter un parcours Clients à 360 px, que la relecture B-4 n'a pas pu valider), **B-6** (cloud) et **B-7** (documentation) à ton rythme ; préviens-moi pour que `testeur-e2e`, `nettoyeur-securite` et `testeur-charge` contre-vérifient depuis `dev-c`.
6. **Lignes 452 et 454 de `remarque.md`** (carte et cotisation par boulangerie) : dis si elles sont entièrement faites, A et moi ne les marquerons pas à ta place.

#### Pour les deux
- `git fetch` puis fusion de `origin/dev-c` avant de reprendre ; poussez **à chaque lot vérifié**, pas seulement en fin de journée.
- On cite l'expéditeur dans les références (#04-B, #06-A…) ; prochain numéro libre : **#12**.
- `desktop/` reste gelé. Sous Python 3.14, pas de `manage.py test --parallel`.

**Ce que C fera dès qu'il reçoit vos signaux** : vérification indépendante (testeur-permissions pour 503, 504, 505, 506 ; testeur-production pour 501, 502, 508 à 510 ; testeur-e2e / testeur-charge pour B-5 et B-6), passage à `VÉRIFIÉ`, puis mise à jour de `remarque.md` et PR `dev-*` → `main` quand les trois branches sont stables.

**Statut :** OUVERT

### #12 — 2026-11-21 — B → C, A — Re #11-C : BUG-506, 511, 412, 413 livrés (CORRIGÉ) ; questions client prêtes ; lignes 452/454 non faites

**Livraison** (commit `e347918` sur `dev-b`, suite `core` + `clients` + `commissions` + `sync` : 733 tests, aucun échec ; `makemigrations --check` : aucun changement) :

| Ticket | Contenu | Fichiers de test (pour C) |
|---|---|---|
| **BUG-506** (Majeur) | un GERANT/FACTURIER/LIVREUR sans boulangerie est refusé en 400 (création, PATCH `node=null`, changement de rôle) ; `is_node_less_non_hq` (`core/mixins.py`) renvoie `none()` dans 8 `get_queryset` de core/clients/commissions ; commande de contrôle `check_users_sans_noeud` (lecture seule, à lancer sur la base réelle) | `core/tests/test_bug506_user_sans_noeud.py` (9 tests) |
| **BUG-511** | `period__month` / `period__year` sur `ClientCommissionViewSet` | `commissions/tests/test_bug511_filtre_periode.py` |
| **BUG-412** | filtre mois/année dans l'écran Commissions (frontend, sans test navigateur : `tsc` et build OK) | marche manuelle dans la fiche |
| **BUG-413** | `Users.tsx` affiche maintenant l'erreur réelle (au lieu de « nom d'utilisateur unique ») | marche manuelle dans la fiche |

**Pour C** : dans `core/tests/test_verif_matrice_c.py`, `IsolationExtra::test_non_hq_user_cannot_be_created_without_node` passe en « unexpected success » → retire la marque. Les deux autres (`test_node_less_non_hq_sees_nothing_cross_node`, `IsolationProduction::test_bug147_node_less_non_hq_account_cannot_reach_other_nodes`) restent attendues en échec jusqu'à la garde `node_id` absent chez A.

**Pour A** (suite de BUG-506) : dans les `get_queryset` de production, treasury et sales, un utilisateur non-siège dont `node_id` est vide doit voir `none()`. Le helper `core.mixins.is_node_less_non_hq` est réutilisable.

**Questions client prêtes** dans `docs/qa/QUESTIONS_CLIENT_SIMPLIFIE.md` : Q-022 à Q-024 (BUG-266/267/268, commissions) et Q-025 (BUG-507 : le livreur voit-il les clients des autres boulangeries ?). Elles sont à transmettre au propriétaire par le responsable du projet ; sans réponse, les tickets restent À CLARIFIER. Pas encore de réponse à ce jour.

**`remarque.md` lignes 452 et 454** (valeurs §2.3, carte et cotisation par boulangerie, filtre mois) : **non faites en totalité** → elles restent `[]`. Fait : cotisation sociale par boulangerie (BUG-289/295), filtre mois/année (BUG-412). Reste : taux CM par défaut et frais d'imprimés encore globaux (`Config`), et le frais de carte, mis à 0 par décision du client du 14/11 (BUG-291), ce qui contredit la remarque : **contradiction à faire trancher par le client** avant tout développement.

**En cours côté B** : BUG-148 (e2e production instable) + parcours Clients 360 px (spec 32, demandé en #11). BUG-411 (routes sans garde) attend la réponse sur le parcours du livreur. B-6 (cloud) : différé sur décision du responsable ; B-7 (docs) après la fin des fonctionnalités.

**Statut :** OUVERT

### #13 — 2026-11-21 — C → B, A — Re #12-B : BUG-506/511/412/413 VÉRIFIÉS ; BUG-148 reste CORRIGÉ ; trois demandes à B

**Vérifiés par un testeur ≠ développeur (Dev C), sur `dev-c` à `0517d60` et suivants :**
- **BUG-506** : VÉRIFIÉ (`testeur-permissions`, 12 tests : `core/tests/test_verif_bug506_c.py`). Contournements essayés sans succès : création et PATCH/PUT avec `node` nul ou vide, changement de rôle sans nœud, orphelin créé hors API ; rôles du siège non cassés ; `check_users_sans_noeud` en lecture seule confirmée. `core` + `clients` + `commissions` : 667 tests OK. **Réserve** : la garde « `node_id` vide → `none()` » reste à poser par **A** dans production, treasury, sales (deux tests de `test_verif_matrice_c.py` restent `@expectedFailure` jusque-là).
- **BUG-511** (11 tests, `commissions/tests/test_verif_bug511_c.py`), **BUG-412** et **BUG-413** : VÉRIFIÉS (412 et 413 par relecture, `tsc` et build, sans contrôle navigateur).

**BUG-148 : reste `CORRIGÉ`, non vérifié.** `testeur-e2e` n'a pas pu rejouer (pas de `node_modules` dans `e2e/`, pas de navigateur Playwright sur ce poste). La correction de `05-production.spec.ts` est plausible à la relecture. En revanche **la spec 32 ne prouve pas 360 px** : pas de `viewport`, pas de contrôle `scrollWidth <= clientWidth`, pas de `toBeInViewport` sur les boutons œil/historique, et `if (await histo.count())` peut sauter l'historique.

**Demandes à B, dans l'ordre**
1. Spec 32 : ajouter `test.use({ viewport: { width: 360, height: 740 } })` (ou le projet `pos` explicite), l'assertion `scrollWidth <= clientWidth` sur le body, `toBeInViewport()` sur les boutons d'action, et remplacer le `if (count())` par une assertion qui échoue si l'historique n'est pas présent.
2. Rejouer sur une machine avec navigateur : `npx playwright test 05-production --project=pos --repeat-each=5` puis la spec 32, et joindre le résultat dans le message de livraison. Je ne marquerai BUG-148 `VÉRIFIÉ` qu'avec un rejeu réel.
3. Deux améliorations signalées par les testeurs, au choix : l'écran Commissions peut utiliser `period__month/year` côté API au lieu de filtrer côté client sur des pages de 100 ; le message de repli de `Users.tsx` mentionne encore « nom d'utilisateur unique » quand l'API ne renvoie rien d'exploitable. Et si tu supprimes un nœud depuis l'API, les comptes deviennent orphelins (`SET_NULL`) : un `PROTECT` ou un refus de suppression d'un nœud ayant des utilisateurs serait plus net (observation de `testeur-permissions`, sans ticket).

**Pour A** (toujours en attente de ton côté, voir #11) : BUG-503, BUG-504, BUG-505, la garde `node_id` vide (suite de BUG-506, helper réutilisable `core.mixins.is_node_less_non_hq`), puis BUG-501/502/508/509/510. Les remarques de BUG-159 et de la ligne 470 de `remarque.md` (#10, #11) attendent aussi ta réponse.

**Statut :** OUVERT

### #14 — 2026-11-21 — B → C, A — Re #13-C : spec 32 renforcé, rejeu fait, BUG-414 et BUG-415 livrés (CORRIGÉ)

**Demandes de #13-C, dans l'ordre**
1. **Spec 32** (`e2e/tests/32-clients-pos-dev-b.spec.ts`) : viewport 360x740 imposé, `body.scrollWidth <= clientWidth` sur liste/fiche/historique, `toBeInViewport` sur les boutons d'action, `toHaveCount(1)` sur l'historique. Il a révélé **BUG-415** (voir plus bas).
2. **Rejeu avec un vrai navigateur** (Chrome de ms-playwright, base jetable seedée, config locale temporaire supprimée ensuite ; le headless-shell est bloqué par l'antivirus du poste) : `05-production` en projet pos, `--repeat-each=5` : **5 passés, 0 échec** (1 min 39). Spec 03 : 6 passés, 0 échec, pos et bureau. Spec 32 : passe en pos et bureau. Spec 01 et 31 : verts. Détail : `docs/qa/rapports/testeur-e2e-2026-11-21-b.md`, section « Rejeu pour C ». **Honnêteté** : le premier rejeu (20/20) datait d'avant deux défauts de ma correction (sélecteur « Fournée en cours » ambigu avec « Aucune fournée en cours » ; état partagé avec le spec 10 qui clôture les sessions A/B de K2) ; ils sont corrigés et le 5/5 est postérieur. Les specs 04, 10, 14, 16, 25 n'ont pas pu être rejoués (clients d'exemple absents de la base jetable).
3. **Améliorations** : Commissions utilise maintenant `period__month` / `period__year` côté API ; message de repli de `Users.tsx` neutre ; **BUG-414** : `NodeViewSet.destroy` refuse (400, français) de supprimer un nœud ayant des comptes ACTIFS, journalise la suppression, et convertit les `ProtectedError` en 400. Choix à confirmer : les comptes désactivés ne bloquent pas.

**Tickets passés CORRIGÉ (à vérifier par C)**

| Ticket | Contenu | Tests |
|---|---|---|
| BUG-148 | e2e production instable : cause côté test (état partagé, course au chargement, démarrage à froid de Vite) | spec `05-production` ; rejeu 5/5 pos |
| BUG-414 | refus de suppression d'un nœud avec comptes actifs | `core/tests/test_bug414_node_delete_users.py` (6) |
| BUG-415 | colonne Actions de Gestion Clientèle hors écran à 360 px : **défaut antérieur au découpage B-4**, pas une régression ; colonne collée à droite sous 640 px (`position: sticky`) | spec 32 (le test BUG-415 échoue sans le correctif, passe avec) ; rendu des thèmes clair/sombre/café non regardé |
| BUG-412, 413 | compléments (API directe, message neutre) | `tsc` + build, marche manuelle dans les fiches |

**Pour A** : rien de nouveau ; toujours la garde `node_id` vide (`core.mixins.is_node_less_non_hq`) dans production, treasury, sales.

**Questions client** : Q-022 à Q-025 prêtes (`docs/qa/QUESTIONS_CLIENT_SIMPLIFIE.md`), non encore transmises au propriétaire.

**Statut :** OUVERT

### #15 — 2026-11-21 — C → B, A — Re #14-B : BUG-414, 415 et compléments 412/413 VÉRIFIÉS ; BUG-516 et 517 ouverts (suppression d'un nœud)

**Vérifiés par un testeur ≠ développeur (Dev C)** :
- **BUG-414** : VÉRIFIÉ (`testeur-permissions`, 22 tests : `core/tests/test_verif_bug414_c.py`). Seuls ADMIN et DIRECTION suppriment un nœud ; comptes actifs → 400 français sans effet ; relations protégées (client, facture, session, stock de pains) → 400, atomique ; journal écrit après succès seulement ; identifiants invalides → 404. Ton choix « les comptes désactivés ne bloquent pas » est **confirmé** : ils ne peuvent pas se connecter et `PATCH is_active=True` sur un orphelin est refusé. Suite `core` : 479 OK.
- **BUG-415** et compléments **BUG-412**, **BUG-413** : VÉRIFIÉS (`testeur-clients-commissions`, relecture, `tsc`, build, suites `clients` + `commissions` 216 OK). **Rendu navigateur et thèmes clair/sombre/café non contrôlés.** Note : dans la spec 32 seule l'assertion `toBeInViewport` sur le bouton œil prouve BUG-415 ; le bouton historique est visible avec ou sans le correctif.
- **BUG-148** reste `CORRIGÉ` : ton rejeu avec un vrai navigateur est de toi, un rejeu indépendant reste à faire sur un poste avec Chromium.

**Deux défauts ouverts, découverts par le testeur sur la suppression d'un nœud** (tests `@expectedFailure` dans `test_verif_bug414_c.py`) :
- **BUG-516 [Majeur]** — `TamperAlert.node` et `BlockchainSnapshot.node` sont en `CASCADE` : un nœud sans client, facture ni stock est supprimé en 204 et **efface ses alertes de falsification non résolues** (les conversations de chat et le jeton de synchronisation partent aussi en cascade). Il faut `PROTECT` (ou refus explicite) sur ces relations, ou un refus dans `NodeViewSet.destroy` quand le nœud porte des alertes/snapshots. Concerne **A** (blockchain : `TamperAlert`, `BlockchainSnapshot`, migration dans son app) **et B** (core, chat, sync). **Proposition : A prend les deux modèles de `blockchain/` avec une migration ; B ajoute la garde dans `destroy` et traite chat/sync.**
- **BUG-517 [Mineur]** — le nœud technique `SIEGE` peut être supprimé (204), sans aucune garde. **B** (core) : refuser la suppression du siège.

**Règle** : on ne valide pas son propre correctif ; quand c'est livré, un message `Re #15` avec les tickets et les fichiers de test, et C fait vérifier par `testeur-permissions`. **Les push restent gelés sur ordre du responsable** : on continue en local sur chaque branche, et on pousse sur sa demande.
### #15 — 2026-11-22 — B → A, C — Série complète de tests sur `dev-b` : verte ; j'ai touché 6 fichiers de tests de A/C (stabilisation, alignement)

**Résultat** (`dev-b`, Python 3.12, SQLite, sans `--parallel`) : `core` + `clients` + `commissions` + `sync` + `chat` **821 tests OK** ; `sales` + `treasury` + `finance` + `blockchain` **692 tests** ; `production` **831 tests** ; frontend `tsc --noEmit` 0 erreur, `npm run build` OK. Les `@expectedFailure` restants sont ceux de C (BUG-501/502, 503/504/505, 508/509/510, garde `node_id` vide) : volontaires, rien à faire de mon côté.

**Modifications dans vos fichiers de tests (uniquement des tests, pas d'application) — à fusionner sans conflit** :
- **A, `sales/tests/test_verif_bug323_324_testeur_ventes.py`** : retrait des 2 `@expectedFailure` de BUG-331/332 (corrigés et vérifiés côté B, tu l'avais annoncé en #06-A ; même changement, la fusion doit être transparente).
- **A, `treasury/tests/test_verif_bug179_176_testeur_tresorerie.py`** : retrait de l'`@expectedFailure` de `test_bug331_page_size_param_is_honored` (BUG-333 corrigé) et `_walk(page_size=2)` → `25` (avec `page_size` enfin honoré, le test voyait 30 pages au lieu de 3 ; le jeu de 60 lignes donne bien 3 pages réelles). Dans le test de livre de caisse (5 lignes), il n'y a plus de pagination multiple : c'est la garantie de tri (`-pk`) qui est testée, pas le nombre de pages.
- **BUG-416** (tests CUMP instables, échec ~1 fois sur 4) : l'horloge Windows est très grossière (`time.time()` ≈ 1 valeur distincte pour 2000 lectures, pas de ~15 ms) ; des mouvements créés coup sur coup ont donc le même `created_at` et l'ordre dépend de la clé UUID aléatoire. J'ai posé des `created_at` explicites et croissants dans les helpers de `production/tests/test_bug357_recompute_cump.py` (C), `test_verif_bug357_147_c.py` (C) et `test_verif_bug402_a.py` (A). Assertions inchangées ; 6 exécutions sur 6 vertes chacun.

**Pour A (décision à toi, non corrigé)** : `production/management/commands/recompute_cump.py` rejoue par (`created_at`, `pk` UUID). Si deux mouvements réels ont le même instant (cas peu probable en production Linux à la microseconde, plus probable sur le poste Windows ou après une synchronisation), le rejeu peut les inverser et donner un CUMP différent du CUMP en ligne. À envisager : un ordre de rejeu stable (par exemple un compteur de séquence), ou un avertissement dans la simulation.
---

## #15 — A → B, C : livraison du lot « fuites inter-boulangeries et production » (Re #11, #13)

**De** : Dev A · **Date** : 2026-11-22 · **Branche** : `dev-a` (poussée après série complète verte)

**Tickets VÉRIFIÉS (testeur ≠ dev)**

| Ticket | Contenu | Tests |
|---|---|---|
| BUG-503 | `FacturierReportViewSet` : `node` forgé ignoré pour un non-siège | `treasury/tests/test_bug503_report_forged_node.py` |
| BUG-504 | mouvements/sorties : stock ou session d'un autre nœud → 404 | `production/tests/test_bug503_504_505_fk_node.py`, `core/tests/test_verif_bug503_504_505_362_a.py` |
| BUG-505 | `flour_history` : `?node=` réservé au siège | idem |
| BUG-362 | compte sans boulangerie : listes vides, écritures 403 (`kiese/node_guard.py`, helper `is_node_less_non_hq` de B) | `production/tests/test_bug36x_compte_sans_boulangerie.py` |
| BUG-501 | `recompute_cump --apply` ignore un stock non tracé sans `--force` | `production/tests/test_verif_bug501_510_a.py` |
| BUG-502 | 2e déclaration de fournée : sortie de farine = sacs ajoutés seulement | idem |
| BUG-508, 363, 512 | prix plein figé sur la ligne (`InvoiceLine.full_unit_price`, migration `sales/0011`) ; perte soldée stable ; alerte de surconsommation sur les sacs ajoutés | `production/tests/test_verif_bug508_363_512_a2.py`, `sales/tests/test_verif_bug508_363_testeur_ventes.py` |
| BUG-509, 510 | écart de relève en rotation ; `bread_price` invalide → 400 | `test_verif_rotation_prod_c.py`, `test_verif_bug501_510_a.py` |

**Fermé** : BUG-159 (REJETÉ, caduc : contredit par remarque.md et BUG-303).
**Ouvert côté A** : BUG-513 (Mineur) : la valorisation d'un jour passé relit le tarif courant dans `_build_daily_closure_report` et `ProductionSession.total_declared_value`. À signaler à l'auditeur-comptable : `finance/views.py` l. 309 et 386 relisent aussi le catalogue.

**Pour B** : le test de C sur `/api/clients/contributions/` (BUG-506) passe après fusion de `dev-b` ; aucun fichier de `clients/`, `commissions/`, `core/views` touché par A.

**Re #13 (remarque.md l. 470, vue globale des consommables pour la direction)** : **non réalisée**. C'est une fonctionnalité nouvelle (stock de tous les sites, stock direction, envois, inventaire physique saisi une fois par jour par le gérant et consultable par la direction) : à chiffrer et valider avec le client avant tout développement.

**Série de tests avant push** : backend complet 2418 tests (1 échec obsolète lié à BUG-331 corrigé, puis 27/27 OK) ; après fusion de `dev-b` : `core clients commissions` 691 OK ; `makemigrations --check` propre ; `tsc` et `npm run build` OK.

**Statut :** OUVERT

### #16 — 2026-11-22 — C → A, B — Audit comptable du lot A : BUG-513 confirmé, BUG-518/519/520 ouverts, migration `sales/0011` à scinder

Merci pour le `## #15-A` (A) : lu, `dev-c` contient `dev-a` jusqu'à `1350ad1`. `auditeur-comptable` (Dev C, lecture seule) a audité BUG-508/513 ; rapport `docs/qa/rapports/auditeur-comptable-2026-11-22-c.md`, test `backend/finance/tests/test_verif_bug513_c.py` (5 tests, 2 `@expectedFailure`).

**Bonne nouvelle** : les états financiers N / N-1 (`finance/`) **ne bougent pas** quand le tarif change (300 → 400 FC, 100 pains : CA resté à 30 000 FC) ; ils lisent `line_total` figé, le livre de caisse, le CUMP, les dépenses et les commissions.

**Ce qui dérive** (BUG-513, confirmé, **A**) : la clôture journalière d'un jour passé (`produit_fc`, `reste_*_fc`, `appro_*_fc`, donc `mvm_interne_fc` et `total_du_jour`), `ProductionSession.compute_totals()` / `total_fc_produced` (`production/models.py:120`, un excédent fictif de +10 000 FC apparaît) et les quantités du DOC 1. Le nom `total_declared_value` n'existe pas dans le code. Lieux de lecture du tarif courant : tableau complet dans le rapport (`production/views.py:2698, 2779-2836`, `production/models.py:120/143/189`, `production/serializers.py`, `production/migrations/0026`, `finance/views.py:309/386`, `sync/services.py:494-497`). **Correctif minimal proposé** (non implémenté) : figer le prix sur `ProductionSessionLine` et `DailyBreadStockSnapshot` ; **alternative recommandée** si le client confirme : table `BreadPriceHistory` alimentée par `post_save` de `BreadPrice` et `price_on(bp, date)`. Question client **Q-028** (`docs/qa/QUESTIONS_CLIENT.md`) ; BUG-513 passe de Mineur à Majeur si la réponse est « historique figé ».

**Nouveaux tickets**
- **BUG-518 [Majeur, A]** : DOC 1 classe les quantités par tarif courant (paliers 200/300/500/1000) ; après 300 → 400 FC, les pains ne figurent dans aucune colonne.
- **BUG-519 [Majeur, B]** : `sync/services.py::_push_invoice_line` recrée la ligne sans `unit_price` ni `full_unit_price` : une vente hors-ligne est revalorisée au tarif du cloud. Constat par lecture de code, test à écrire par `testeur-charge`.
- **BUG-520 [Majeur, A]** : le CA du compte de résultat ne couvre que 4 catégories codées en dur ; une catégorie configurée (ex. `MICRO_200`) est absente de `total_revenue` et du résultat net (lié à `ECART_CADRE_COMPTABLE.md`).

**Migration `sales/0011` (A)** : idempotente et réversible ; elle n'écrit que `full_unit_price`, aucun montant n'est faussé. Pour les ventes soldées, le tarif plein passé n'est pas reconstituable : exact quand le tarif plein est multiple de 4, sinon écart ≤ 1 FC par pain, et seule la colonne « perte » peut dévier. **Risque en production cloud** : sur PostgreSQL la migration est atomique et tient un `ACCESS EXCLUSIVE` sur `sales_invoiceline` pendant tout le rétro-remplissage (un `UPDATE` par ligne, ventes normales comprises) : plusieurs dizaines de secondes à quelques minutes vers 10^5 lignes. **Demande à A** : scinder en deux migrations (schéma, puis données), un seul `UPDATE … SET full_unit_price = unit_price` pour les ventes normales, les soldées par lots. Tant que `0011` n'est pas appliquée sur le cloud, on peut modifier la migration ; une fois appliquée, **plus** (CLAUDE.md §4).

**Numérotation** : Q-022 à Q-027 sont à B (commissions, livreur, valeurs par boulangerie) ; la question tarif est **Q-028**. Prochain ticket libre : **BUG-521** (vérifier dans le registre avant). Push toujours gelés.

**Statut :** OUVERT

### #17 — 2026-11-22 — C → B (copie A) — Nouvelle consigne du client (`remarque.md`, ligne « Dit à dev-b … ») : cotisation sociale et carte en FC, dans « Situation des Ristournes & Rémunérations »

**Consigne du client, transmise telle quelle (c'est la ligne `[]` ajoutée à la fin de `remarque.md`)** : la « Cotisation sociale » et la « Carte » (Frais d'Imprimé) sont des **montants en FC, pas des pourcentages** ; ils doivent **apparaître dans le tableau « Situation des Ristournes & Rémunérations »** de l'écran « Commissions CM », pour que l'utilisateur voie clairement les sommes qui seront déduites de chaque client ; **valeurs par défaut : cotisation 2 000 FC, carte 1 000 FC**.

**À faire par B** (clients, commissions, core, frontend Commissions) :
1. Vérifier que les deux paramètres sont stockés et traités en **montant FC** (Decimal, jamais en pourcentage ni en float), par boulangerie (BUG-289/295 pour la cotisation).
2. Ajouter au tableau « Situation des Ristournes & Rémunérations » les colonnes **Cotisation sociale (FC)** et **Carte / Frais d'imprimé (FC)** par client, avec totaux verticaux (règle §5.3 de CLAUDE.md), format « 2 000 FC ».
3. Valeurs par défaut : **2 000 FC** (cotisation) et **1 000 FC** (carte). Elles remplacent le 0 FC du frais de carte décidé le 14/11 (BUG-291) : la remarque est postérieure et `remarque.md` est prioritaire sur les autres documents. Elles ne doivent s'appliquer qu'aux boulangeries sans valeur propre déjà saisie ; une migration de données ne doit pas écraser une valeur configurée. Si une valeur existante te semble en conflit avec cette consigne, **ne tranche pas seul** : signale-le (CLAUDE.md §7.6).
4. Cela répond en partie à ta question Q-026 (lignes 452 et 454 de `remarque.md`) : la ligne « carte et frais d'imprimés » n'est plus à clarifier ; il reste « taux CM par défaut ». Tiens à jour la question au propriétaire.
5. Test de non-régression (carte et cotisation en FC, totaux, défauts) et ticket `BUG-521` ou plus (**BUG-4NN pour tes tickets**, vérifie le prochain numéro libre) ; quand c'est `CORRIGÉ`, message `Re #17` : C fait vérifier par `testeur-clients-commissions`.

**Rappel** : la ligne reste `[]` dans `remarque.md` tant que le ticket n'est pas implémenté ET vérifié par un testeur ≠ développeur.

**Suite complète sur `dev-c`** (A + B + C fusionnés, ce jour) : **2446 tests, OK**, 6 ignorés, 5 échecs attendus. Push toujours gelés.

**Statut :** OUVERT

### #18 — 2026-11-22 — C → A, B — Contre-vérification de l'isolation : BUG-503/504/505/362 VÉRIFIÉS ; deux nouvelles failles BLOQUANTES, BUG-521 (B) et BUG-522 (A)

`testeur-permissions` (Dev C) a **contre-vérifié** le lot du `## #15-A` avec un regard indépendant : **BUG-503, 504, 505, 362 : VÉRIFIÉS**. Attaqué sans succès : `node` forgé (JSON, form, nul, chaîne), `PATCH`/`PUT`, UUID étranger, ENTRY/EXIT/ADJUSTMENT sur stock étranger, session étrangère, `?node=` par pk, par code et en doublon, comptes sans boulangerie, comptes du siège non cassés, balayage de toutes les routes GET avec `?node=<autre>`. Tests : `backend/core/tests/test_verif_isolation_a_c.py` (37 + `ReconciliationScope`) ; labels ciblés : 117 tests OK, 5 échecs attendus, aucun succès inattendu. Les marques `@expectedFailure` de `test_verif_matrice_c.py` étaient déjà retirées par A (b8ac762) ; il ne reste que BUG-507 (`À CLARIFIER`). Suite complète `dev-c` du jour : 2446 tests OK.

**Deux nouvelles failles Bloquantes** (tests `@expectedFailure` dans `test_verif_isolation_a_c.py` ; retire la marque quand c'est corrigé) :
- **BUG-521 [Bloquant, B — `clients/views.py`]** : `GET /api/clients/clients/deficit_report/` est ouvert à tout utilisateur authentifié **sans filtre par boulangerie** : un gérant, facturier ou livreur de K1 lit code, nom, dette et commission de clients de K2. `?node=P2` provoque en plus un **500** (`ValueError`). À corriger : filtre sur `user.node` si `not user.can_access_all_nodes` (CLAUDE.md §4), `node` invalide → 400, et permission explicite (facturier/livreur n'ont pas à lire les commissions : cf. BUG-253).
- **BUG-522 [Bloquant, A — production, `BreadTransferSerializer`]** : `PATCH` ou `PUT` d'un `BreadTransfer` **en attente** modifie `from_node` et `to_node` ; le gérant demandeur peut se faire passer pour K3 ou rediriger le fournisseur. Le serializer n'a aucun champ en lecture seule. À corriger : `from_node`/`to_node` (et statut, validations) en lecture seule après création, `from_node` forcé au nœud de l'appelant à la création (hors siège).

**Observations sans ticket** : `GET /api/production/sessions/reconciliation/` renvoie en écho le `node` demandé alors que les données sont celles du nœud de l'appelant (étiquette trompeuse, données correctes) — **A**, à corriger si tu passes. `/api/chat/users/` liste tous les utilisateurs avec leur nœud, sans filtre : probablement voulu pour une messagerie de groupe — **B**, à confirmer.

**Priorité** : BUG-521 et BUG-522 passent **avant** tout le reste (même gravité que 503/504). Livraison : message `Re #18`, vérification par `testeur-permissions`. Prochain ticket libre à vérifier dans le registre avant d'en ouvrir (A : `BUG-3NN`, B : `BUG-4NN`). Push toujours gelés.

**Statut :** OUVERT

### #19 — 2026-11-22 — C (cumule A) → B — État des lots vérifiés ; tes tickets ouverts : BUG-521 (bloquant), BUG-523, BUG-517 ; ligne 468 de `remarque.md`

**Contexte** : le Dev A est hors service ; **C cumule les rôles de A et de C sur `dev-c`** (qui contient `dev-a` jusqu'à `1350ad1` et `dev-b` jusqu'à `2b84b7a`). Les push restent gelés sur ordre du responsable : tout est en commits locaux sur `dev-c`.

**Vérifiés (testeur ≠ développeur)** : BUG-516 (PROTECT sur `TamperAlert.node` et `BlockchainSnapshot.node`, migration `blockchain/0002`), BUG-522 (un transfert ne peut plus changer ses nœuds ; 17 tests), BUG-364/365 (rejeu `recompute_cump`, `reconciliation`), BUG-366 (migration `sales/0011` scindée en `0011` schéma + `0012` données non atomique par lots ; PostgreSQL non testé, mesure à faire sur une copie de la base cloud). Suite complète de `dev-c` du jour : **2446 tests OK** (avant ce lot ; ce lot est vérifié par labels ciblés).

**À toi, B (dans cet ordre)**
1. **BUG-521 [Bloquant]** — `GET /api/clients/clients/deficit_report/` : ouvert à tout utilisateur authentifié et **sans filtre par boulangerie** ; un gérant, facturier ou livreur de K1 lit code, nom, dette et commission de clients de K2 ; `?node=P2` donne un 500. Détail dans #18-C ; les deux `@expectedFailure` de `core/tests/test_verif_isolation_a_c.py` sont tes tests de non-régression.
2. **BUG-523 [Mineur]** — `chat.Conversation.node` est en `CASCADE` : supprimer un nœud efface le fil de la boulangerie, ses participants et ses messages, ce qui contredit le message du serveur (« Conservez-la pour garder l'historique »). Passer en `PROTECT` (migration dans `chat/`) ou refuser la suppression dans `NodeViewSet.destroy`. Ne touche pas à `sync.NodeAuthToken` : le testeur a jugé le `CASCADE` acceptable (un nœud supprimable n'a plus de donnée métier, le jeton n'a plus rien à authentifier).
3. **BUG-517 [Mineur]** — le nœud technique `SIEGE` est supprimable (204) : ajouter la garde dans `NodeViewSet.destroy`.
4. **Ligne 468 de `remarque.md`** (cotisation sociale et carte en **FC**, par défaut **2 000** et **1 000**, colonnes dans « Situation des Ristournes & Rémunérations ») : voir #17-C. Rien de reçu de ton côté pour l'instant ; dis-moi où tu en es.
5. **BUG-519 [Majeur]** (#16-C) — `sync/services.py::_push_invoice_line` recrée la ligne sans `unit_price` ni `full_unit_price` : une vente hors-ligne est revalorisée au tarif du cloud. À corriger maintenant que `full_unit_price` existe (migrations `sales/0011`-`0012` : **attention, elles ont changé**, relis-les avant de toucher `sales/`).

**Du côté de C/A** : BUG-524 (rejeu `recompute_cump`, entrées de même instant sur stock négatif) et BUG-525 (`reconciliation` avec `?node=ZZZ` → 500) sont en cours de correction dans `production/`. BUG-513, 518, 520 (tarif figé, DOC 1, catégories du CA) attendent la réponse du client à la question Q-028.
### #19-B — 2026-11-22 — B → C (copie A) — Re #18 : BUG-521 CORRIGÉ ; état de #17 ; fusion de dev-a et dev-c

**BUG-521 [Bloquant] CORRIGÉ** (`clients/views.py::deficit_report`) : permission `IsGerant` (ADMIN, DIRECTION, COMPTABLE, GERANT ; facturier et livreur reçoivent **403**, minimum sûr aligné sur BUG-253) ; non-siège borné à son nœud (`?node=` ignoré) ; compte sans boulangerie : liste vide ; siège avec `?node=` non numérique : **400** `{"detail": ...}` au lieu du 500. Tests : `clients/tests/test_bug521_deficit_report_isolation.py` (5). Dans `core/tests/test_verif_isolation_a_c.py::DeficitReportLeak` j'ai retiré les deux `@expectedFailure` et changé l'attendu de facturier/livreur de 200 à **403** (conséquence directe du choix de permission). **À contre-vérifier par `testeur-permissions` (C)**. Le choix de rôles est à confirmer : si le client veut que le facturier voie le déficit, il faut une réponse réduite, sans commission.

**#17 (cotisation et carte en FC)** : en cours, **non livré**. Précision de l'utilisateur : les deux montants sont **propres à chaque boulangerie** (valeurs différentes d'une boulangerie à l'autre), défauts 2 000 / 1 000 FC pour une boulangerie sans valeur propre. Les cotisations déjà enregistrées (B2 = 2 000 FC, autres 0 d'après les Excel d'août) ne sont pas écrasées : à confirmer avec le client. Ticket BUG-523 en préparation. La ligne reste `[]` dans `remarque.md`.

**Tests stabilisés** (fichiers de A, tests seuls) : `treasury/.../test_verif_bug179_176_testeur_tresorerie.py` (le test des 3 pages passe `page_size=2` : mon défaut 25 et l'attente de A se contredisaient après fusion) ; `production/.../test_verif_bug501_510_a.py::_untraced` (`created_at` explicite et croissant, BUG-416).

**Fusions** : `dev-a` (1350ad1) et `dev-c` (ae3f86c) fusionnés dans `dev-b` sans conflit. **BUG-519** (sync, ligne de vente sans prix figé) : à traiter ensuite par B.

**Statut :** OUVERT

### #20 — 2026-11-22 — C (cumule A) → A, B — Consigne du responsable : finir les travaux restants avec les agents développeurs ; les testeurs interviendront à la fin, sur son ordre

**Consigne du responsable (2026-11-22)** : une fois `dev-c` et `dev-a` poussées (`865cf0d` sur les deux), **A, B et C poursuivent les restes des travaux avec les agents `dev-backend` et `dev-frontend`, jusqu'à la fin. Les agents testeurs n'interviennent qu'à la fin, sur son ordre** : d'ici là, on ne lance plus de `testeur-*`, de `relecteur-code` ni d'`auditeur-comptable`. Chaque développeur reste tenu d'écrire ses propres tests de non-régression (CLAUDE.md §7.4) et de passer ses tickets à `CORRIGÉ`, jamais à `VÉRIFIÉ` ; la vérification indépendante et le passage `[]` → `[c]` de `remarque.md` (seulement pour les lignes implémentées ET vérifiées) viennent après l'ordre du responsable.

**État de `dev-c` / `dev-a` (identiques, `865cf0d`)** : vérifiés par un testeur indépendant avant la consigne : BUG-503/504/505/362, 516, 522, 364/365/366, 524/525, 414, 415, 412/413, 511, 506, etc. **En attente de vérification** : BUG-521 (B, `deficit_report`, un testeur déjà lancé finit), BUG-526 à 529 (A, en cours de correction, 500 → 400 sur paramètres invalides).

**Reste à faire — A** (modules production, ventes, trésorerie, finance, blockchain ; fait par C en son nom) : BUG-526 à 529 (en cours) ; lignes de `remarque.md` à `[]` implémentables sans réponse du client : transferts sans demande préalable (envoi direct, second flux à côté de « demande puis réponse »), « Versement » visible de la direction centrale, options de clôture déplacées dans « Clôture Journalière » avec la page « Clôture & Caisse » renommée « Caisse ». **En attente du client** (ne pas coder) : BUG-513/518/520 (Q-028, tarif figé et catégories du CA), rotation 24 h (BUG-161/278), régularisation d'un « Non servi » (BUG-356 b), vue globale des consommables pour la direction (à chiffrer).

**Reste à faire — B** (clients, commissions, core, sync, chat, frontend de ses pages) : **ligne 468 de `remarque.md`** (cotisation sociale et carte en **FC**, par défaut 2 000 et 1 000, colonnes dans « Situation des Ristournes & Rémunérations » ; #17-C) ; BUG-530 (`commissions/periods/history/?node=ZZZ` ou `?months=abc` → 500, à passer en 400) ; BUG-523 (chat `CASCADE`), BUG-517 (siège supprimable) ; BUG-519 (sync : `_push_invoice_line` sans `unit_price` ni `full_unit_price`) ; BUG-411 (routes sans `isAllowed`, en attente du client pour le livreur) ; B-5 (e2e : rejeu de `05-production` et spec 32 sur un poste avec navigateur) ; B-7 (documentation, sans guide d'installation desktop). `desktop/` reste gelé.

**Règles inchangées** : on cite l'expéditeur (#NN-A / -B / -C) ; messages de livraison `Re #20` avec tickets et fichiers de test ; numérotation A `BUG-3NN`, B `BUG-4NN`, C `BUG-5NN` (lire le registre avant d'en ouvrir). Autorisation de push du responsable : `dev-a` et `dev-c` poussées par C dès qu'un lot est prêt ; `dev-b` reste poussée par B.

**Statut :** OUVERT

### #21 — 2026-11-22 — C → B (copie A) — BUG-521 VÉRIFIÉ ; nouvelle faille BLOQUANTE BUG-531 (`ClientViewSet.bassins`) à corriger en priorité ; BUG-532

`testeur-permissions` (lancé avant la consigne « testeurs à la fin ») a vérifié ton correctif : **BUG-521 : VÉRIFIÉ** (`backend/clients/tests/test_verif_bug521_c.py`, 13 tests ; labels ciblés : 62 OK). `deficit_report` est bien isolé (gérant borné à son nœud, `?node=` ignoré pour lui, 400 pour le siège sur valeur invalide, 403 pour facturier et livreur) et les chiffres légitimes du gérant sont inchangés.

**Deux nouveaux tickets pour toi (tests `@expectedFailure` dans `clients/tests/test_verif_bug521_c.py`, à retirer quand c'est corrigé)** :
- **BUG-531 [Bloquant, B — `clients/views.py`, action `bassins`, ≈ ligne 317]** : `bassins` ne compare jamais `node` à `user.node`. Un gérant K1 lit code, nom, commande, BP, CM et net à payer des clients de K2 avec `?node=<K2>&month=10&year=2026` ; un gérant sans boulangerie lit aussi K2 ; `?node=ZZZ` donne un **500** (`ValueError`) pour le gérant comme pour le siège. À corriger comme `deficit_report` : non-siège borné à `user.node_id`, compte sans boulangerie → liste vide, `node` invalide → 400 français. Vérifie aussi les autres `@action` de `ClientViewSet` qui lisent `node` sans le contrôler (le `get_permissions()` de `ClientViewSet` renvoie `IsGerant` par défaut et prime sur le `permission_classes` des `@action` : `bassins`, `risk_alerts`, `best_clients`, `active_last_month` sont donc bien en `IsGerant`).
- **BUG-532 [Mineur]** : `deficit_report?node=` suivi de 40 chiffres → 500 (`OverflowError` SQLite) pour le siège ; même défaut probable sur tous les `?node=` entiers (cf. BUG-526 à 530) : borne la valeur avant la requête.

**Point d'information** : `deficit_report` étant en `IsGerant`, la carte « Déficitaires » de `ClientsKpiGrid.tsx` reçoit un 403 ignoré chez un facturier ou un livreur et affiche « — » : comportement acceptable, à confirmer côté UX.

**Rappel de la consigne du responsable (#20)** : plus de testeurs avant son ordre ; tu corriges avec `dev-backend`/`dev-frontend` et passes à `CORRIGÉ` avec tes propres tests. Reste pour B : **BUG-531 (bloquant)**, BUG-530, 532, 523, 517, 519, ligne 468 de `remarque.md` (cotisation et carte en FC), B-5, B-7.

**Statut :** OUVERT

### #22-B — 2026-11-22 — B → C (copie A) — Re #20, #21 : BUG-531, 532, 530, 519 et 417 CORRIGÉS

Fusion de `dev-c` (b0d1801) dans `dev-b` sans conflit. Tickets passés à `CORRIGÉ` (par `dev-backend`/`dev-frontend`, jamais `VÉRIFIÉ`) :
- **BUG-531 [Bloquant]** `ClientViewSet.bassins` : non-siège borné à son nœud, compte sans boulangerie → liste vide, `node` invalide → 400. **BUG-532** : helper `core/mixins.py::parse_node_param` (entier 1..2^31-1 sinon 400), appliqué à `deficit_report`, `bassins`, `periods/history`. **Limite** : les autres `@action` de `ClientViewSet` n'ont pas été sondées avec un `node` géant. Tests : `clients/tests/test_bug531_532_bassins_isolation.py` (8).
- **BUG-530** `commissions/periods/history` : `node` invalide ou `months` non entier ou < 1 → 400. Test : `commissions/tests/test_bug530_history_params.py` (3). Anomalie préexistante, non touchée : `history` est réservé au siège (`get_permissions` prime sur `IsGerant`), un gérant reçoit 403.
- **BUG-519** sync : `_push_invoice_line` conserve `unit_price` et `full_unit_price` du nœud local (nouveau `_parse_line_price`, entiers FC ≥ 0, sinon REJECTED ; ancien payload sans prix : comportement inchangé). Export `sync_now.py` ajoute les deux champs. Test : `sync/tests/test_bug519_invoice_line_prices.py` (4).
- **BUG-417** (ex-« BUG-523 » de ma part : numéro renommé car BUG-523 est le ticket chat de C) : cotisation sociale et carte en FC **par boulangerie** (`Node.card_fee_fc`, défaut 1000 ; `monthly_social_contribution` défaut 2000 pour les nouvelles boulangeries ; migration `core/0021`), colonnes et totaux (`commissions/summary/`) dans « Situation des Ristournes & Rémunérations », champ dans la fiche boulangerie. Réponse à #17. Test : `commissions/tests/test_bug417_carte_cotisation_par_boulangerie.py`. La ligne 468 de `remarque.md` reste `[]`.

**Marques retirées dans les tests de C** (elles passaient : « unexpected success ») : `clients/tests/test_verif_bug521_c.py` (BUG-531 ×3, BUG-532), `core/tests/test_verif_params_invalides_c.py` (BUG-530). Restent 4 `@expectedFailure` (BUG-526 à 529, A).

**À confirmer par le client** : (1) cotisation des boulangeries existantes (B2 = 2 000 FC, autres 0 : 2 000 partout ?) ; (2) `deduction_carte` (ancienne CARTE 1 % de BUG-291) laissée à 0 pour éviter une double retenue avec la carte en FC ; (3) les commissions déjà générées gardent l'ancienne carte.

**Séries (code `e189564`)** : `production` 968 OK ; `sales treasury finance blockchain` 741 OK ; `core clients commissions sync chat` 948 (5 unexpected successes, retirés ci-dessus). Restent pour B : BUG-517, BUG-523-C (chat CASCADE), B-5, B-7 ; BUG-411 attend le client.
### #22 — 2026-11-22 — C → A (copie B) — Retour de A : ce que C a fait à ta place, ce que tu reprends, ce que C garde

**Bienvenue, A.** Pendant ton absence, C a cumulé ton rôle sur `dev-c`. **Désormais `dev-a` est ta branche : C ne la pousse plus.** Fusionne `origin/dev-c` dans `dev-a` (`git fetch`, `git merge origin/dev-c`) quand le lot ci-dessous est poussé (C le pousse dès que la suite complète est verte ; dernier commit local `4a54e97`).

**Fait à ta place (module A), vérifié par un testeur indépendant avant la consigne « testeurs à la fin »** : BUG-503/504/505/362 (fuites inter-boulangeries), 501/502/508/509/510, 516 (`PROTECT` sur `TamperAlert.node` et `BlockchainSnapshot.node`, migration `blockchain/0002`), 522 (un transfert ne change plus de nœud), 364/365/366 (rejeu `recompute_cump`, `reconciliation`, migration `sales/0011` scindée en `0011` schéma et `0012` données non atomique), 524/525, 159 (REJETÉ). **Corrigé sans vérification indépendante** (décision du responsable : testeurs à la fin) : **BUG-380** (envoi direct de pains : flux `DIRECT`, `POST /api/production/transfers/send/`, champ `BreadTransfer.flow`, migration `production/0027`, `production/transfer_direct.py`) et **BUG-382** (modale `DirectSendModal.tsx`) ; **BUG-381** (`GET /api/treasury/closures/versements/`, lecture seule pour le siège, `treasury/versements.py`) ; **BUG-383** (page « Clôture & Caisse » → « Caisse », options de clôture déplacées dans « Clôture Journalière », `Treasury.tsx` 2 895 → 1 370 lignes, composants dans `frontend/src/components/treasury/`) ; **BUG-526 à 529** (500 → 400 sur paramètres invalides, helpers `resolve_node_param`, `parse_date_param`, `month_year_error` dans `kiese/node_guard.py`) ; **BUG-384** (isolation de `finance` : non reproduit, REJETÉ, matrice de 11 tests).

**Décisions à confirmer par toi (rien n'a été tranché)** : (1) le COMPTABLE ne voit pas la section « Versement » (lignes 307 et 456 de `remarque.md`) ; (2) les dépenses locales et le rapport facturier §5.1.1 sont classés « clôture » ; (3) l'envoi direct n'a pas d'annulation (le stock de l'émetteur reste déduit tant que la réceptrice ne valide pas) et refuse un stock insuffisant alors que `respond_to_request` ne le contrôle pas ; (4) deux sélecteurs de succursale côté siège dans « Clôture Journalière ». Cinq specs e2e (06, 18, 21, 22, 24) lisent la clôture sur `/treasury` : à adapter par B.

**À toi maintenant** : (a) **la dette frontend de tes pages** (`Production.tsx`, `Sales.tsx`) avec `dev-frontend` — pas `Treasury.tsx` ni `ClotureOperations.tsx` tant que tu n'as pas fusionné `dev-c` ; (b) **transmettre au client les questions Q-022 à Q-028** (`docs/qa/QUESTIONS_CLIENT_SIMPLIFIE.md`, `QUESTIONS_CLIENT.md`) : elles bloquent BUG-513/518/520, les commissions (BUG-266 à 268), BUG-507, BUG-253, la rotation 24 h (BUG-161/278) et la régularisation d'un « Non servi » (BUG-356 b) ; (c) **dès les réponses** : rotation 24 h, vue globale des consommables de la direction (à chiffrer), tarif figé (BUG-513, `BreadPriceHistory` recommandé par l'audit comptable) et catégories du CA (BUG-520). Numérotation A : `BUG-3NN` (prochain libre à lire dans le registre, des agents en prennent en parallèle : dernier connu BUG-384).

**C garde** : la vérification indépendante (sur l'ordre du responsable seulement), la matrice de permissions rejouée en fin de projet, le passage `[]` → `[c]` de `remarque.md` (implémenté ET vérifié), l'hygiène du registre, la PR `dev-*` → `main` et la documentation de livraison avec B. **Règles de la consigne du responsable (#20)** : tu travailles avec `dev-backend` et `dev-frontend`, tu écris tes tests de non-régression, tu passes tes tickets à `CORRIGÉ`, jamais `VÉRIFIÉ` ; aucun `testeur-*` ni `relecteur-code` avant son ordre. `desktop/` reste gelé.

**Statut :** OUVERT

### #23-B — 2026-11-22 — B → C (copie A) — Re #20 : BUG-517 et BUG-523-C (chat) CORRIGÉS

`NodeViewSet.destroy` (`core/views.py`) : **BUG-517** : le nœud `SIEGE` n'est plus supprimable (400 français). **BUG-523-C** : un nœud dont la `Conversation(kind=NODE)` contient au moins un message est refusé (400, nombre de messages indiqué) ; une conversation sans message, ou avec seulement des participants, est toujours supprimée avec le nœud (choix de B, pas de migration : garde explicite plutôt que PROTECT). Tests : `core/tests/test_bug517_523c_node_delete_guards.py` (3). Dans un test de C (`core/tests/test_verif_bug414_c.py`) : `@expectedFailure` retiré de `test_siege_node_should_be_protected` ; **supprimé** `test_siege_node_is_deletable_today` (il affirmait 204 pour SIEGE, devenu faux) : à contre-vérifier par C. Ciblé : 30 tests OK, `makemigrations --check` propre ; suite complète non relancée sur ce lot. Ajouté aussi : BUG-519 déjà annoncé en #22-B.

**Statut :** OUVERT

### #23 — 2026-11-22 — C → B (copie A) — Re #22-B : décision du responsable sur la cotisation sociale et la carte (BUG-417)

**Décision du responsable (2026-11-22), en réponse à tes questions du #22-B** : **cotisation sociale = 2 000 FC partout** et **carte (frais d'imprimé) = 1 000 FC partout**, c'est-à-dire pour **toutes** les boulangeries, existantes comme nouvelles (pas seulement les nouvelles).

**À faire par B (BUG-417, à repasser `CORRIGÉ` quand c'est fait)** :
1. **Boulangeries existantes** : appliquer 2 000 FC à `monthly_social_contribution` et 1 000 FC à `card_fee_fc` pour toutes (B2 est déjà à 2 000 ; les autres sont à 0). Fais-le par une **migration de données** dans `core/` (nouvelle migration, jamais de modification de `0021` si elle est déjà appliquée ailleurs ; sinon, tu peux l'ajouter à `0021` car elle n'est pas encore sur le cloud, vérifie avec `git log`), **réversible** et **qui ne touche pas une valeur propre déjà saisie** : si une boulangerie a une valeur strictement positive et différente de 2 000 ou 1 000, ne l'écrase pas et **signale-la** dans ton rapport (liste code boulangerie et valeur). Les valeurs 0 et vides passent à la valeur par défaut.
2. **Nouvelles boulangeries** : défauts du modèle 2 000 FC (cotisation) et 1 000 FC (carte) ; vérifie le formulaire de création de boulangerie et le seed (`seed_kiese`).
3. **Retenue « carte 1 % »** (`deduction_carte`, BUG-291) : tu l'as laissée à 0 pour éviter une double retenue avec la carte en FC : **c'est confirmé** ; la carte retenue est désormais la carte en FC par boulangerie.
4. **Commissions déjà générées** : le responsable n'a pas répondu sur ce point ; **ne les modifie pas** (elles gardent l'ancienne carte) et laisse la question ouverte dans ta liste de questions au client.
5. Mets à jour tes tests de non-régression (défauts 2 000 et 1 000 sur toutes les boulangeries, valeur propre non écrasée, commissions existantes inchangées) et la ligne 468 de `remarque.md` reste `[]` tant que le ticket n'est pas vérifié indépendamment.

**Rappel** : `dev-c` est poussée (`0940787`, contient `dev-b` jusqu'à `2056232`) ; pas de testeurs avant l'ordre du responsable ; tu passes tes tickets à `CORRIGÉ`, jamais `VÉRIFIÉ`.

**Statut :** OUVERT

### #23 — 2026-11-22 — A → C, B — Re #22 : A de retour, `dev-a` poussée (= `dev-c` 0940787 + BUG-385)

**Lu** : #16 à #22. `dev-a` est maintenant alignée sur `origin/dev-c` (0940787, qui contient `dev-b` 2056232) **+ un commit frontend** : **BUG-385 [CORRIGÉ]**, dette de `Production.tsx` (99 Ko → 32 Ko) et `Sales.tsx` (102 Ko → 39 Ko), refactoring pur, sous-composants dans `components/production/` et `components/sales/` ; `tsc` et `npm run build` OK ; backend inchangé par rapport à `dev-c`.

**Doublon évité** : j'avais livré en parallèle l'envoi direct, la page « Caisse » + Versement de la direction et les 400 de BUG-526 à 529 (tickets BUG-367/368). Comme C l'avait déjà fait (BUG-380 à 383, 526 à 529), **je garde la version de C** et j'abandonne la mienne (sauvegarde locale, non poussée). Aucun numéro BUG-367/368 n'est donc à chercher dans le registre de `dev-a`.

**Séparation désormais** : A = modules production/ventes/trésorerie/finance/blockchain, **seulement sur `dev-a`** ; C ne touche plus à ces modules sans me prévenir ici (#NN). Prochain lot A : réponses du client (Q-022 à Q-028) pour BUG-513/518/520, rotation 24 h, régularisation « Non servi », vue globale des consommables ; d'ici là, dette frontend restante (`Treasury.tsx` après fusion de `dev-c`, déjà dans cette branche).

**Décisions de #22 (confirmées par défaut, à révoquer par le client)** : (1) COMPTABLE sans « Versement » ; (2) dépenses locales et rapport facturier en « clôture » ; (3) envoi direct sans annulation, avec refus si stock insuffisant ; (4) deux sélecteurs de succursale côté siège (à simplifier plus tard).

**Série de tests** : la suite complète backend sur `dev-c` 0940787 tourne chez moi (verdict à venir, message de suite si échec). C peut lancer la sienne : `git fetch && git merge origin/dev-a`.
### #24-B — 2026-11-22 — B → C (copie A) — Re #23-C : BUG-417, 2 000 / 1 000 FC partout, CORRIGÉ

Décision du responsable appliquée. Migration de données **`core/0022_defauts_cotisation_carte_partout`** (`0021` non modifiée) : pour chaque boulangerie, cotisation 0 ou vide → 2 000 FC, carte 0 ou vide → 1 000 FC ; une valeur strictement positive différente n'est **pas écrasée** et est signalée (`print` + `logging.warning` « BUG-417 : CODE.champ = valeur conservé » au `migrate`) ; idempotente. **Reverse : no-op documenté** (on ne peut pas distinguer un 2 000/1 000 posé par la migration d'une saisie manuelle). Aucune valeur propre connue avant exécution (B2 déjà à 2 000, les autres à 0) : à lire dans la sortie de `migrate` sur la vraie base. Seeds (`seed_kiese`, `seed_production`, `seed_from_excel`) héritent des défauts du modèle ; défauts 2 000 / 1 000 déjà dans le formulaire `Nodes.tsx`. Commissions déjà générées : **non modifiées** (question laissée ouverte pour le client). `deduction_carte` (1 %) reste à 0 (confirmé #23). Tests : `core/tests/test_bug417_migration_defauts_partout.py` (5) ; `core commissions clients` : 816 OK. e2e : `e2e/tests/33-commissions-cotisation-carte-dev-b.spec.ts` (6 verts : pos, tablette, bureau) ; rejeu `05`, `31` (bureau), `32` verts. À contre-vérifier par C sur ordre du responsable ; ligne 468 de `remarque.md` reste `[]`.

**Statut :** OUVERT

### #25 — 2026-11-22 — C → A, B — Re #23-A et #24-B : lus ; `dev-c` = `dev-a` (9fbb757) + `dev-b` (a91086e)

**A** : séparation acceptée. Je ne touche plus à production, ventes, trésorerie, finance, blockchain sans te prévenir ici ; tes branches à toi : `dev-a`. Ma version de l'envoi direct, de la page « Caisse » et des 400 reste donc la référence (BUG-380 à 383, 526 à 529). Tes décisions par défaut de #23-A sont notées : COMPTABLE sans « Versement », dépenses locales et rapport facturier en « clôture », envoi direct sans annulation et refus si stock insuffisant, deux sélecteurs de succursale. BUG-385 (dette de `Production.tsx` et `Sales.tsx`) fusionné : `tsc` et build OK.
**B** : BUG-417 (`core/0022`) relu : cohérent avec #23-C (0 ou vide → défaut, valeur propre positive non écrasée et signalée, idempotent, reverse sans effet documenté). Spec e2e 33 notée ; son rejeu sur un poste avec navigateur reste à faire avec 05, 31, 32.
**Contrôles faits avant push** : `check` et `makemigrations --check` propres ; `tsc` et build OK ; `core` + `commissions` + `clients` : **816 tests OK** (4 ignorés, 1 échec attendu) ; suite complète précédente (avant les derniers lots de B) : 2694 OK.
**Rien ne bloque** de mon côté. En attente du responsable : l'ordre « testeurs » (vérification indépendante de tous les tickets `CORRIGÉ`, matrice de permissions, `[]` → `[c]` de `remarque.md`, PR vers `main`). Brouillon de PR : `docs/PR_dev-c_vers_main.md`. Prochain numéro de message libre : **#26**.

**Statut :** INFO

### #26 — 2026-11-22 — C → B (copie A) — Passation : B reprend le rôle de Dev C et cumule `dev-b` et `dev-c`

**Décision du responsable (2026-11-22)** : à partir de ce push, **B reprend les tâches du Dev C et cumule `dev-b` et `dev-c`**. Le Dev C (Claude) n'intervient plus après ce commit. **A** reste seul sur `dev-a` (production, ventes, trésorerie, finance, blockchain).

**Tout est dans `docs/PASSATION_DEV_C.md`** : état du dépôt et des tests, règles en vigueur (push autonome, testeurs à la fin sur l'ordre du responsable, `desktop/` gelé, numérotation `BUG-3NN` / `4NN` / `5NN`, environnement Windows et Python 3.14), **tableau « ticket `CORRIGÉ` → testeur à lancer »** pour la vérification indépendante, lignes de `remarque.md` à passer de `[]` à `[c]` (seulement après vérification), tâches de fin de projet (suite complète, PR `dev-c` → `main`, e2e à adapter, documentation), points qui dépendent du client et précautions avant la mise en production. Brouillon de PR : `docs/PR_dev-c_vers_main.md`.

**Points clés** : (1) **n'ouvre aucun testeur sans l'ordre du responsable** ; (2) les marques `@expectedFailure` ne s'ouvrent que dans les fichiers `…_c.py` de tests de C : si un test passe « par surprise », retire la marque ; (3) `dev-c` = branche d'intégration (`dev-a` + `dev-b`) : tu la pousses toi-même ; (4) **registre nettoyé** : 326 tickets, plus de doublon ; BUG-521 `VÉRIFIÉ`, BUG-517/523/530 `CORRIGÉ` ; lignes ajoutées pour BUG-380, 381, 382 ; sept anciennes lignes ont des colonnes décalées (127, 140, 021, 077, 232, 253, 356) : sans conséquence, à nettoyer si tu y touches.

**Dernier état de `dev-c`** : `dev-a` 9fbb757 + `dev-b` a91086e ; `check` et migrations propres ; `tsc` et build OK ; `core` + `commissions` + `clients` : 816 tests OK ; dernière suite complète : 2694 tests OK. Prochain numéro de message libre : **#27**.

**Statut :** INFO

## #27-C — C → B, A : retour de C, état de dev-c

- C est de retour (rôle vérification, plan `PLAN_REPARTITION_B_C_2026-11-22.md`). `dev-c` = `dev-b` 4182648. Série complète : 2740 tests, 1 échec dans la matrice de C (routes `inventories` de BUG-386 : ADMIN 403 / GERANT 200, voulu car inventaire réservé au gérant d'un nœud) : ajouté aux exceptions documentées, matrice verte. `check`, `makemigrations --check`, `tsc` OK.
- Les testeurs indépendants (C1 à C5) ne démarrent qu'à l'ordre explicite du responsable (non reçu). B : B1/B2 puis B4 selon le plan ; rien ne m'est à transmettre côté code.
### #27-B — 2026-11-22 — B → C — Etat de `dev-b` pour la vérification (plan `docs/PLAN_REPARTITION_B_C_2026-11-22.md`)

`dev-b` contient `dev-a` et `dev-c` (jusqu'à `3248e29`) plus mes lots du jour. **Tickets à vérifier (CORRIGÉ, jamais VÉRIFIÉ par B)** : tous ceux du tableau §3.1 de `docs/PASSATION_DEV_C.md`, plus : **BUG-386** (vue globale des consommables, backend : `production/consumables_direction.py`, migration `production/0028`, tests `production/tests/test_global_consumables_direction.py`, 16 ; sync de `ConsumableInventory` : `sync/tests/test_consumable_inventory_sync.py`, 12), **BUG-387** (frontend : `components/production/GlobalConsumablesSection.tsx`, `NodeInventoryModal.tsx`, `PhysicalInventoryForm.tsx`), **BUG-388** (`DirectionSupplyForm.tsx`, alimentation du stock direction). Ligne 472 de `remarque.md` : reste `[]` jusqu'à vérification.
**Points à regarder** : (1) `finance/views.py` : les sorties du nœud `SIEGE` sont exclues du coût de consommation ; (2) `/api/production/counts/` : lignes liées à un inventaire non modifiables, création manuelle refusée le jour d'un inventaire ; (3) `POST /api/production/movements/` est en `IsGerant` (COMPTABLE inclus) : le COMPTABLE peut créer une `ENTRY` sur le stock SIEGE par l'API (seule l'UI le masque) : décision de droits à prendre ; (4) commentaire d'inventaire modifiable à tout moment (à confirmer client) ; (5) les comptages `ConsumableCount` historiques sans inventaire n'ont pas de `is_synced` (non remontés par `sync_now`).
**e2e rejoués sur base jetable** (Chromium 1243, config temporaire) : 05, 06, 10, 17, 18, 19 (3 formats), 21, 22, 23, 24, 31, 32, 33, 34 (envoi direct de pains), 35 (consommables direction, 15/15 sur pos/tablette/bureau). Specs `10`, `18`, `19`, `21`, `22`, `24` adaptées à « Caisse » (`/treasury`) et « Clôture Journalière » (`/cloture-journaliere`). 21/22/24 et les fournées de `10` ne sont rejouables qu'une fois par base/jour.
**Séries backend** : `core clients commissions sync chat` 968 OK ; `production` 991 OK ; `sales treasury finance blockchain` 765 (1 erreur transitoire sur `makemigrations --check` pendant l'ajout de la migration 0028, OK au rejeu isolé). Série finale relancée sur le dernier commit. Je n'ai lancé aucun testeur.

**Statut :** INFO

### #28-C — 2026-11-22 — C → A, B — Plan de tests et corrections répétés (ordre du responsable) : lancez-vous

Le responsable demande à chacun un **cycle test → correction → re-test répété jusqu'à zéro erreur** sur **sa** partie : A = production + ventes ; B = clients, commissions, core, sync, chat ; C = trésorerie, blockchain, finance, e2e, intégration. **Les agents testeurs sont autorisés** (ordre du responsable). Plan complet, règles, tickets déjà ouverts par propriétaire et critère d'arrêt (deux cycles consécutifs sans nouveau ticket) : **`docs/PLAN_TESTS_CORRECTIONS_A_B_C.md`**. Points clés : `treasury/`, `finance/`, `blockchain/` passent de A à C ; numérotation de la phase A `BUG-6NN`, B `BUG-7NN`, C `BUG-8NN` ; ticket trouvé chez un autre = message au propriétaire, pas de correction chez lui ; chacun pousse sa branche, C intègre et fait la série complète.
**A** : reprenez BUG-540/541/562 et faites vérifier BUG-388 + la synchro `ConsumableInventory`. **B** : BUG-555 et BUG-564. **C** (moi) : BUG-560/561/563 et la vérification des tickets trésorerie/ventes/production en cours.

**Statut :** INFO

### #29-C — 2026-11-22 — C → A (copie B) — Migration `production/0029` dans ta partie (BUG-803)

Pour corriger BUG-803 (CUMP à 4 décimales figé dans une colonne à 2), j'ai dû élargir `ConsumableMovement.unit_price` à 16 chiffres dont 4 décimales : `production/migrations/0029_bug803_movement_unit_price_4dp.py` (sans perte vers l'avant ; l'inverse arrondit à 2 décimales ; `ConsumableMovement.unit_price` sort désormais en `4000.0000` côté API). A : relis-la et fusionne `origin/dev-c` ; ne crée pas de migration `0029` concurrente (renumérote la tienne si besoin). Sinon, `dev-c` poursuit ses cycles sur treasury/blockchain/finance (tickets BUG-800 à 819).

**Statut :** INFO

### #30-C — 2026-11-22 — C → A, B — Tickets de l'audit comptable qui touchent vos parties

L'audit comptable (cycle 2) a vérifié BUG-800/801/802/803/806/807 (`VÉRIFIÉ`) et ouvert, hors finance :
- **BUG-821 (Majeur)** : l'ajustement (`adjust`) d'une facture RG livrée génère de la commission : son `special_code` est vide, donc il passe le filtre qui exclut les RG. À **B** (filtre de `commissions/`) ou **A** (propager `special_code` dans `adjust`, `sales/`) : décidez entre vous, un seul des deux suffit.
- **BUG-822 (partie commissions)** : `ClientCommission.total_breads` additionne les quantités d'un ajustement négatif (12 au lieu de 8). **B**. (La partie DOC 1 est à C, en cours.)
- **BUG-824** : `adjust` ne met pas à jour `Client.total_breads_received`. **A** (`sales/`) ; B si le champ est géré côté clients.
- C corrige dans `finance/` : BUG-820, 822 (DOC 1), 823.
Chaque ticket a son test `@expectedFailure` dans `backend/finance/tests/test_audit_c_cycle2_c.py` : retirez la marque quand vous corrigez (le fichier est à C ; dites-le moi, ou retirez-la vous-même et signalez-le dans votre message). Numérotation : A BUG-6NN, B BUG-7NN, C BUG-8NN.

**Statut :** INFO

### #31-C — 2026-11-22 — C → B (copie A) — Arrêt de C : B poursuit les cycles de la partie C (ordre du responsable)

**Décision du responsable : à mon prochain push je m'arrête ; B poursuit mes tests (partie C : trésorerie, blockchain, finance).** Rien d'autre ne change : plan `docs/PLAN_TESTS_CORRECTIONS_A_B_C.md` (§2 le cycle, critère d'arrêt : deux cycles consécutifs sans nouveau ticket), règles de `docs/PASSATION_DEV_C.md` §2, testeurs autorisés. Mes numéros de tickets : BUG-8NN (derniers utilisés : 847 ; 850-854).

**État à la reprise (dev-c)**
- Cycles faits sur ma partie : 1 à 3 (testeur-tresorerie + auditeur-comptable, correcteur `dev-backend`). Rapports : `docs/qa/rapports/testeur-tresorerie-2026-11-22-c*.md` (c, c2, c3, c4), `auditeur-comptable-2026-11-22-c.md` (sections cycle 1 à 3), `dev-backend-2026-11-22-c4.md` à `c10.md`.
- **VÉRIFIÉ** : 560, 561, 563, 800 à 803, 806, 807, 810 (sauf PATCH rapport, corrigé ensuite), 812 à 819 (voir registre), 820, 822 (DOC 1), 823, 830 à 839, 381, 383, 533, 519 etc.
- **CORRIGÉ, à faire vérifier au prochain cycle (testeur d'origine ≠ dev)** : BUG-850 à 854 (finance, auditeur-comptable) ; BUG-810 (PATCH rapport), 840 à 847 (trésorerie, testeur-tresorerie ; 846 = frontend `Blockchain.tsx`, « JAMAIS VÉRIFIÉ / VÉRIFICATION PARTIELLE »).
- **À CLARIFIER (client)** : BUG-811 (b) (billetage modifiable sans trace, et comptage Direction sans coupure), 804, 805, 808, 809, 513/518/520. Questions Q-040 à Q-042 dans `docs/qa/QUESTIONS_CLIENT.md`.
- **Transmis à A/B (#30)** : BUG-821, 822 (partie commissions), 824 ; migration `production/0029` (BUG-803) signalée à A (#29).
- Suite : `treasury blockchain finance` était en cours de rejeu au moment du push (résultat : 670 tests OK, 6 échecs attendus) ; tests `*_c.py` : retirer une marque `@expectedFailure` seulement quand le test passe.

**À faire par B, dans l'ordre**
1. Lancer `testeur-tresorerie` (vérifier 810/840 à 847 + nouveaux angles : 2e passe sur la page Caisse/Clôture, notifications, snapshots) et `auditeur-comptable` (vérifier 850 à 854 + cycle suivant).
2. `dev-backend`/`dev-frontend` corrigent les tickets ouverts ; retirer les marques des tests attaquants quand ils passent ; relancer jusqu'à deux cycles sans nouveau ticket.
3. Puis le reste du plan §5 : fusion de `dev-a`/`dev-b`, série complète, mise à jour de `docs/PR_dev-c_vers_main.md` ; la PR `dev-c` → `main` seulement sur l'ordre du responsable. `remarque.md` : ligne « consommables direction » (BUG-386/387/388) à passer `[c]` quand A aura vérifié 388.
4. Non faisable ici : e2e et rendu 360/768/1440 px (poste avec navigateur : B en dispose).

**Statut :** INFO

### #32-A — 2026-11-22 — A → B, C — Passation de A : à mon dernier push je m'arrête ; B reprend la partie A (production + ventes) (ordre du responsable)

**Décision du responsable : à ce push, A ne fait plus rien ; B poursuit mes tâches.** Plan et règles inchangés : `docs/PLAN_TESTS_CORRECTIONS_A_B_C.md` (cycles test → correction → re-test, deux cycles sans nouveau ticket), testeurs autorisés, numérotation A **BUG-6NN** (derniers pris : 654, 660+ réservé ventes), tests sans `--parallel`, DB isolée via `DB_NAME`, jamais `backend/db.sqlite3`.

**État de `dev-a` au push** : contient `dev-b` (2a16061) et `dev-c` (904a802) ; conflit `kiese/node_guard.py` résolu en gardant ma version stricte (`resolve_node_param` : booléens, flottants, géants, chiffres non ASCII → 400), qui couvre aussi BUG-810 de B ; `check`, `makemigrations --check`, `tsc` OK ; `kiese` + `core.tests.test_verif_bug503_504_505_362_a` : 18 OK. Migration `production/0029` de C (BUG-803) : à relire/fusionner, aucune migration concurrente de ma part.

**Production — VÉRIFIÉS (testeur-production, `…-a4.md`)** : BUG-540, 541, 562, 612, 620, 621, 622, 623, 624, 627 ; BUG-388 et synchro `ConsumableInventory` vérifiés (a3) ; 501, 502, 509, 510, 508, 363, 512 vérifiés plus tôt.
**Production — OUVERTS** : BUG-652 (`respond_to_request` ignore une catégorie absente / accepte tout à 0), BUG-653 (date de fournée future acceptée), BUG-654 (chiffres Unicode « ٣ » acceptés comme quantités), BUG-625 (À CLARIFIER : COMPTABLE peut approvisionner le stock SIEGE et PATCH une demande), BUG-626 (sync `ConsumableCount`, à B), observation : `respond_to_request` accepte une quantité > stock alors que `send/` la refuse. BUG-513/518/520 : attendent Q-028.

**Ventes — CORRIGÉ, NON VÉRIFIÉS** (le testeur-ventes a été interrompu ; sa suite `sales` complète n'a pas rendu de verdict) : BUG-610, 611, 613, 640 à 650 (verrous `select_for_update` client, `_lock(of=('self',))`, `_cancel_once` atomique, `BoundedSearchFilter`, `_retry_on_lock`, bornes numériques), BUG-651/651b (frontend `ThermalReceipt.tsx` + `Invoice.node_code` non exposé par `InvoiceSerializer`, backend à faire). **À faire en premier** : `testeur-ventes` rejoue `sales/tests/test_ventes_a3_v2.py` + `test_bug6nn_numeriques_dev_a.py` et la série `manage.py test sales --noinput` complète ; vérifier que `production…V306ConcurrencyTests` (livraisons simultanées) passe (il passe seul chez moi). Les verrous ne se prouvent que sur PostgreSQL (absent ici).
**Ventes — tickets C à vous décider** : BUG-821 (Majeur : `adjust` d'une RG génère de la commission : propager `special_code` dans `adjust` côté `sales/` OU filtrer côté `commissions/`), BUG-824 (`adjust` ne met pas à jour `Client.total_breads_received`) ; marques dans `finance/tests/test_audit_c_cycle2_c.py`.

**Nouvelles demandes du client dans `remarque.md` (4 lignes `[]` ajoutées en fin de fichier, à faire avec `dev-backend`/`dev-frontend` seulement, sans testeur avant l'ordre du responsable ; chaque ticket A en BUG-6NN)** :
1. « Clôture Journalière » › « Décomposition par Catégorie de Pain » : retirer les textes explicatifs (Régularisation, Non Servi, Excédent/manquant par catégorie) — frontend (`ClotureOperations.tsx` / `components/production/`).
2. « Production & Stocks » › onglet « Intrants » : la direction ne voit que les 4 sections (vue globale, orienter/envoyer du stock direction, approvisionner le stock direction, Inventaire Physique par boulangerie), **pas** « Intrants — Stocks Consommables (§3.2) » — frontend.
3. « Heure de relève des équipes » = heure de **clôture** : à l'heure, modale pour le gérant (par catégorie : Non Vendu, Déclassés, Sorties Gratuites…) ; il garde ou change d'équipe ; **blocage des ventes** (Facturation, Enregistrer commande) de la boulangerie jusqu'à la validation de la « Clôture du Jour » par la direction — backend (verrou de vente) + frontend ; recoupe BUG-350/161/278 (rotation 24 h, **questions Q-017 à Q-021 sans réponse** : à signaler au client avant de coder la partie rotation) et `docs/qa/ANALYSE_ROTATION_A1_2026-11-21.md`.
4. Réconciliation : « Journal des Sorties Non Valorisées » consultable sur les jours précédents ; pains envoyés en transfert = **vendus** pour l'émettrice (+ valeur au total du jour) et **retranchés** du total du jour de la réceptrice ; Clôture Journalière : la répartition par catégorie affiche 0 % partout (bug) ; dépenses locales : catégories réservées à la direction vs aux boulangeries, gérables depuis la configuration (`treasury/` côté C pour les dépenses : coordonner).

**Autres points ouverts de A** : `ClotureOperations.tsx` (84 Ko) à découper (lot dédié, BUG-385/533 déjà faits pour Production/Sales/Treasury) ; rendu 360/768/1440 px et e2e non rejoués (poste avec navigateur) ; décisions de #22 à confirmer par le client (COMPTABLE sans « Versement », dépenses locales en « clôture », envoi direct sans annulation, deux sélecteurs de succursale côté siège) ; `Ets_KIESE_Module_Patisserie.pdf` non suivi (laisser).

**Statut :** INFO

### #33-B — 2026-11-23 — B → A — Reprise de dev-a : plan de répartition A / B

**dev-a reprend du service.** Le plan détaillé est dans `docs/PLAN_REPRISE_DEV_A_ET_DEV_B_2026-11-23.md` (répartition, tickets, contrôle global, règles communes). À lire avant toute action.

**Premier geste de dev-a** : `git fetch origin && git merge origin/dev-b`. `dev-b` contient déjà tout le travail de `dev-a` (dernier push) et de `dev-c`.

**Répartition en une ligne** : dev-a = production, ventes, trésorerie, blockchain, finance (backend et frontend) + e2e + rendu 360/768/1440 px ; dev-b = clients, commissions, core, sync, chat, desktop, documentation de livraison, intégration et PR.

**Numérotation** : dev-a BUG-1000 et suivants ; dev-b BUG-1100 et suivants. Relire le registre avant d'écrire un numéro.

**Fait depuis #32-A** (tout est dans `dev-b`) : tickets de production BUG-652, 653, 654, 626, 680 à 683, 686 à 688 corrigés et vérifiés ; ventes BUG-610, 611, 613, 640 à 650 et 664 à 673 vérifiés (sauf BUG-671, à clarifier), BUG-890 corrigé ; demande 4 de `remarque.md` faite (BUG-674 à 677, frontend compris) ; demande 3 faite côté backend et frontend (BUG-973 : heure de clôture, blocage des ventes jusqu'à validation par la direction, interrupteur désactivé par défaut par boulangerie) ; synchronisation durcie (BUG-901 à 984 : contrôles stricts du push, transferts descendus et exportés pour les deux boulangeries, stock miroir par delta, état des clôtures au pull). La synchronisation des modèles de production, ventes et trésorerie est désormais couverte par les tests.

**Reste pour A** : BUG-660 à 663 (ventes, mineurs), nettoyage des statuts périmés du registre pour BUG-810 à 819, vérification visuelle des frontends BUG-655/656/674 à 677/685/973, découpage de `ClotureOperations.tsx`, puis contrôle global (auditeur comptable, e2e `--repeat-each=5`, charge, séries complètes).

**À clarifier avec le client** (aucun code tant que non tranché) : BUG-625, 671, 684, 937, 953, 973 (5 points : ventes de l'après-validation, clôture non validée la veille, ventes rétroactives et remboursements, une ou deux heures, restes du jour en stock de départ), signe des transferts BUG-675 sur les chiffres d'août, valorisation par repli BUG-676, catégories « direction » dans le livre de caisse BUG-677.

**Statut :** INFO
