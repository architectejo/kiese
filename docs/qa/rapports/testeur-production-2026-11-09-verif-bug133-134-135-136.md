# Rapport testeur-production — 2026-11-09 — Vérification BUG-133/134/135/136

## Mandat
Vérifier (relecture de code, pas seulement des rapports + tests d'intégration bout-en-bout
indépendants) les 4 tickets liés actuellement au statut `CORRIGÉ` :
BUG-133 (backend, boîte modale « stock de départ »), BUG-134 (frontend, la boîte modale),
BUG-135 (signe de `reste_du_hier` pour les jours confirmés) et BUG-136 (synchronisation de
`BreadStock.qty_adjusted`).

## Résumé de la décision

**Aucun des 4 tickets n'est passé à `VÉRIFIÉ`.** Le comportement technique livré (signe BUG-135,
synchronisation de stock BUG-136, non-régression BUG-118/120, permissions anti-cross-node
BUG-022/025/056) est correct et entièrement couvert par des tests qui passent — voir détail
ci-dessous. Mais en relisant intégralement `remarque.md` autour de la ligne citée par les fiches
BUG-133/134 (l.396), j'ai trouvé la phrase suivante, **non traitée par l'implémentation livrée**,
à la ligne 398 :

> « Après confirmation des restes d'hier, les valeurs renseignées doivent remplacer les valeurs
> [...] dans "Production & Stocks" et non additionner, on le fait une fois le matin, [pas] pour
> l'équipe A ou B, juste une fois au créneau d'ouverture (premier créneau), **le facturier peut
> aussi faire ça**. »

Deux points de cette phrase ne sont pas couverts par BUG-133/134 :
1. **« le facturier peut aussi faire ça »** — `DailyOpeningConfirmationView` (`IsGerant`) et le
   montage de la boîte modale (`DashboardLayout.tsx`, garde `role === 'GERANT'`) excluent
   totalement FACTURIER (403, modale jamais montée). → **BUG-138** (OUVERT).
2. **« une fois le matin, [pas] pour l'équipe A ou B, juste une fois »** — l'implémentation exige
   au contraire deux confirmations distinctes (une par équipe, `unique_together=[node, team,
   date]`), et la boîte modale reste ouverte tant que les deux équipes ne sont pas confirmées
   (demande explicite de la fiche BUG-134). C'est en contradiction apparente avec la lecture
   littérale du client. Aucune trace écrite d'une clarification contraire n'a été retrouvée
   (`docs/qa/QUESTIONS_CLIENT.md` ne mentionne rien à ce sujet) ; les lignes l.396/398 de
   `remarque.md` restent non cochées `[]`, contrairement aux lignes déjà traitées et cochées
   `[c]` juste au-dessus dans le même fichier (convention du dépôt). → **BUG-139** (À CLARIFIER,
   ambiguïté métier réelle, pas tranchée par le testeur, CLAUDE.md §7 règle 6).

Conformément à la mission (« s'ils sont fonctionnellement liés, ne valide AUCUN des 4 si un seul
échoue »), et puisque BUG-133/134 ne couvrent pas entièrement remarque.md l.398, **BUG-133,
BUG-134, BUG-135 et BUG-136 restent au statut `CORRIGÉ`**. Le travail technique sous-jacent
(BUG-135/136 en particulier) est très probablement réutilisable sans réécriture une fois BUG-138/
139 résolus — ce ne sont pas des bugs de calcul mais des manques de périmètre/une ambiguïté de
conception non confirmée avec le client.

J'ai également remarqué, en cours de vérification, qu'un **BUG-137** (sous-ticket frontend,
affichage du bandeau `stock_adjustments`) a été ouvert et corrigé par `dev-frontend` en parallèle
de cette session (voir `docs/qa/rapports/dev-frontend-2026-11-09-bug137-affichage-ajustement-
stock.md`). Il n'était pas dans mon périmètre de mandat explicite (BUG-133/134/135/136 uniquement)
et n'a donc pas été vérifié ici — à prendre en compte dans une prochaine session de vérification,
idéalement en même temps que BUG-138/139 puisqu'il touche le même composant
(`OpeningStockConfirmationModal.tsx`).

## Relecture de code (pas seulement des rapports)

Code relu intégralement et confirmé conforme aux rapports de clôture des 4 tickets :
- `backend/production/models.py` : `BreadStock.qty_adjusted`, `qty_available` (propriété),
  `_adjust_bread_stock(..., adjusted=0)`, modèles `DailyOpeningConfirmation`/
  `DailyOpeningConfirmationLine` (docstrings à jour, convention de signe BUG-135 bien documentée).
- `backend/production/views.py` : `_build_daily_closure_report` (négation `-confirmed_reste_du_
  hier_by_team_bp[...]`, ligne ~1172), `_opening_confirmation_resolve_node`,
  `DailyOpeningConfirmationView.get()`/`.post()` (verrouillage `select_for_update()` avant lecture
  du solde, delta recalculé sur l'état courant à chaque soumission — jamais cumulatif, conforme
  CLAUDE.md §4).
- `backend/production/serializers.py` : `BreadStockSerializer` expose `qty_adjusted` en lecture
  seule.
- `backend/production/urls.py` : route `opening-confirmation/` présente.
- `frontend/src/components/production/OpeningStockConfirmationModal.tsx` et
  `frontend/src/components/layout/DashboardLayout.tsx` : montage conditionné à
  `role === 'GERANT' && !can_access_all_nodes`, `routeKey` alimenté par `location.pathname`,
  réaffichage à chaque navigation si une équipe n'est pas confirmée, fermeture temporaire
  « Plus tard » qui ne dure que jusqu'au prochain changement de route — conforme à BUG-134.

## Tests backend

### Déjà écrits par dev-backend (relus, jugés corrects)
`backend/production/tests/test_daily_opening_confirmation.py` — 30 tests, rejoués : **OK**.

### Nouveaux, écrits pour cette vérification indépendante
`backend/production/tests/test_opening_confirmation_verification.py` (7 tests) :
- `OpeningConfirmationEndToEndScenarioTests` :
  - `test_gerant_corrects_proposed_value_full_scenario` — parcours complet demandé par la
    mission : GET (proposition = stock courant) → correction → POST équipe A → vérifie en une
    seule fois `BreadStock.qty_available` exact (BUG-136), `reste_du_hier['A']` négatif de la
    bonne grandeur dans `_build_daily_closure_report` (BUG-135), et que ce calcul ne dépend que de
    `qty_confirmed` (une vente intervenant APRÈS la confirmation ne change pas le résultat déjà
    produit pour ce jour).
  - `test_gerant_validates_proposed_value_as_is_is_exact_noop_on_stock` — no-op exact : `qty_
    adjusted` lui-même reste à 0 (pas seulement `qty_available` inchangé), et `reste_du_hier`
    reste correctement négatif même en no-op.
  - `test_team_b_get_reflects_team_a_adjustment_independent_check` — revérification indépendante
    (pas de confiance aveugle au rapport dev-backend) que le `GET` de l'équipe B reflète bien
    l'ajustement fait par A, et que le rapport de clôture reflète ensuite les deux équipes.
- `OpeningConfirmationPermissionBoundaryTests` :
  - `test_facturier_post_refused_entirely_no_side_effect` / `test_livreur_post_refused_entirely` —
    confirment le 403 actuel (base du constat BUG-138).
  - `test_hq_role_comptable_is_treated_as_headquarters_not_refused_but_cannot_act_implicitly` —
    clarifie un point non explicité par la mission : COMPTABLE est un rôle HQ accepté par
    `IsGerant` (comme ADMIN/DIRECTION), pas refusé comme FACTURIER/LIVREUR — comportement voulu et
    cohérent avec `DailyClosureReportView` (BUG-120), documenté explicitement pour ne pas être
    redécouvert comme une anomalie.
  - `test_gerant_cannot_make_other_node_adjust_stock_via_forged_node_on_post` — revérification
    indépendante de l'effet de bord sur le STOCK (pas seulement sur la confirmation) quand un
    GERANT non-HQ tente de forger `node` : aucun ajustement sur le nœud étranger.

**Résultat** : `production.tests.test_opening_confirmation_verification` +
`production.tests.test_daily_opening_confirmation` → **37/37 OK**.

`backend/.venv/Scripts/python.exe manage.py test production sales finance -v 1` → **199/199 OK**
(609,1 s, ralenti par la contention CPU déjà documentée pour les sessions précédentes, 0 échec,
`System check identified no issues`).

`backend/.venv/Scripts/python.exe npm run build` (frontend, vérifié en parallèle car des
modifications concurrentes de `OpeningStockConfirmationModal.tsx`/`services.ts` étaient en cours
sous BUG-137 pendant cette session) → succès, exit code 0, seul avertissement préexistant sur la
taille du chunk legacy (> 500 kB, sans rapport avec ce module).

`backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → « No changes
detected ».

## Tests E2E Playwright

Fichier écrit : `e2e/tests/11-stock-depart-confirmation.spec.ts` — couvre :
1. Réaffichage de la boîte modale à chaque navigation (Tableau de bord → Clients → Production)
   tant qu'aucune équipe n'est confirmée pour `demo_gerant_k1_e2e` (BUG-134), y compris après un
   « Plus tard » (fermeture temporaire, jamais définitive).
2. Correction d'une quantité et validation ; vérification que le stock affiché par
   « Production & Stocks » reflète la valeur validée, pas la valeur proposée (BUG-136).
3. Un compte DIRECTION et un compte ADMIN (HQ) ne voient jamais la boîte modale.

**Décision : non exécuté contre le serveur de dev partagé pendant cette session.** Deux raisons
cumulatives :
1. `backend` (port 8000) et `frontend` (port 5173) étaient déjà occupés par un processus actif au
   moment de cette vérification (vraisemblablement une autre session d'agent en cours — le rapport
   `dev-frontend-2026-11-09-bug137-...md` a été produit PENDANT cette session, preuve d'une
   activité concurrente réelle sur le même dépôt/la même base). Lancer une suite E2E qui se
   connecte, navigue et soumet des POST réels contre ce serveur partagé en même temps qu'un autre
   agent y travaille activement risquait une collision (données, quota de connexion BUG-006,
   confusion sur l'origine d'un échec).
2. La découverte de BUG-138/139 invalide de toute façon la vérification des 4 tickets
   indépendamment du résultat d'un parcours E2E — exécuter maintenant un scénario qui écrit des
   données réelles sur `BreadStock` de K1 (nœud réel, base de dev partagée avec le client en test
   direct selon la consigne de mission) n'apportait pas une valeur justifiant ce risque tout de
   suite.

**Recommandation** : exécuter `e2e/tests/11-stock-depart-confirmation.spec.ts` dans une fenêtre
dédiée (aucun autre agent actif sur le même backend/`db.sqlite3`), idéalement après résolution de
BUG-138/139 pour éviter de devoir le réécrire si la conception change (sélecteur d'équipe,
condition d'ouverture).

## Tickets ouverts par cette vérification

- **BUG-138** (OUVERT, Majeur) : FACTURIER doit pouvoir confirmer le stock de départ
  (remarque.md l.398), actuellement bloqué à 403 côté API et jamais monté côté frontend.
- **BUG-139** (À CLARIFIER, Majeur) : contradiction apparente entre la conception « confirmation
  séparée par équipe A **et** B » (BUG-133/134) et la demande littérale du client (« une fois,
  pas par équipe, au premier créneau »). Ambiguïté réelle à trancher par le coordinateur/client,
  pas par le testeur.

## Statuts finaux

| Ticket | Statut avant | Statut après | Décision |
|---|---|---|---|
| BUG-133 | CORRIGÉ | **CORRIGÉ** (non vérifié) | Technique correct, périmètre incomplet (BUG-138/139) |
| BUG-134 | CORRIGÉ | **CORRIGÉ** (non vérifié) | Idem |
| BUG-135 | CORRIGÉ | **CORRIGÉ** (non vérifié) | Correct isolément, lié fonctionnellement aux 3 autres |
| BUG-136 | CORRIGÉ | **CORRIGÉ** (non vérifié) | Correct isolément, lié fonctionnellement aux 3 autres |
| BUG-138 | — | **OUVERT** | Nouveau, cette session |
| BUG-139 | — | **À CLARIFIER** | Nouveau, cette session |

Aucun fichier applicatif modifié par le testeur (CLAUDE.md §7 règle 2). Fichiers ajoutés :
`backend/production/tests/test_opening_confirmation_verification.py`,
`e2e/tests/11-stock-depart-confirmation.spec.ts`, et les entrées BUG-138/139 dans
`docs/qa/REGISTRE_BUGS.md`.
