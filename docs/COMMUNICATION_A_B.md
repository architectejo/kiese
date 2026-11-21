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
