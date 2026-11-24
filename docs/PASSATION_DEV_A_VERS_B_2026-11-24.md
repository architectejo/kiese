# Passation dev-a → dev-b (2026-11-24)

Auteur : dev-a. **Décision du responsable : dev-a s'arrête à ce push ; dev-b reprend ses tâches et poursuit sans s'arrêter jusqu'à la fin du projet, en travaillant UNIQUEMENT avec les agents `dev-backend` et `dev-frontend`** (pas de `testeur-*`, `auditeur-comptable`, `relecteur-code`, `testeur-e2e`), **sans le desktop ni la documentation de livraison**. Cadre général : `docs/PLAN_FIN_PROJET_A_B_2026-11-24.md` (règles §0, critères de fin §5).

## 1. État de `dev-a` au moment de la passation

Tout est commité et poussé ; **seul ce qui est commité te parvient** (ne compte pas sur l'arbre de travail de dev-a). Dernier commit : voir `git log origin/dev-a -1`. `manage.py check`, `makemigrations --check`, `tsc` et `npm run build` passent ; les tests ciblés de chaque lot sont verts.

Livré par dev-a, **CORRIGÉ, à faire vérifier par ta vérification croisée** (un agent `dev-backend`/`dev-frontend` de ton côté : relecture, tests rejoués, contrôle Chrome sur instance jetable) :
- **BUG-1050** livreur = facturier côté `sales/` et `production/` ; **BUG-1051** tests V9/V11 alignés sur ton parseur numérique ;
- **BUG-1060** statistiques journalières des intrants + conversion du sel (1 sac = 20 kg = 204 boîtes ; migration `production/0031`) ; **BUG-1061** onglet « Statistiques » ;
- **BUG-1070 / 1071** (remarque l.510, 514) « Stock Pains du Jour » : stock de départ, « Envoyés » = transferts seulement, « Reçu » ;
- **BUG-1072** (l.512) écart de fournée Excédent / Équilibre / Manquant ;
- **BUG-1073 / BUG-1202** (l.516) restes d'hier et du jour par JOURNÉE, pas par équipe ; **BUG-1074** clôture automatique des fournées (`auto_close_day`, commande `auto_close_sessions`, déclenchée par `shift-end-status`) ;
- **BUG-1076** (pic du matin sous SQLite) et l'adaptation de 3 tests à la décision « livreur comme facturier » : voir §2 point 1 pour l'état exact.
Déjà vérifiés : BUG-655, 656 (contrôle Chrome de dev-a), 386/387/388 (testeurs). Lignes de `remarque.md` cochées par dev-a : 472, 475, 483.

## 2. Tâches qui passent à dev-b (dans cet ordre)

1. **Terminer le lot ventes en cours** : relire `docs/qa/REGISTRE_BUGS.md` (BUG-1076) et `git log origin/dev-a` : si le commit « 4 échecs ventes » est présent, vérifier seulement qu'il est vert ; sinon : trois tests de `sales/tests/` périmés par la décision du client Q-027 (« le livreur a les mêmes écrans que le facturier » : `test_vague4_calendaire_ventes_2026_11_12::BlocageEquipeTests`, `test_ventes_a3_v2::RolesEtIsolation::test_livreur_ne_cree_ni_annule_ni_ajuste`, `test_verif_ventes_a8_v8::…test_facturier_pousse_est_aujourd_hui_ignore_observation`) à adapter SANS affaiblir, et `test_charge_morning_peak` (« database table is locked » en concurrence sous SQLite) à corriger en gardant le verrou client de BUG-640 sur PostgreSQL.
2. **Vérification croisée de tout ce que dev-a a livré (§1)**, puis, si conforme : passer les tickets à `VÉRIFIÉ (vérification croisée dev-b, date)` et **cocher `[c]` dans `remarque.md` les lignes 510, 512, 514 et 516** (ajouter « — traité sous BUG-NNN ; vérifié par … » à la fin de chaque ligne). Priorité : BUG-1060/1061, 1050, 1070 à 1074.
3. **Contrôles visuels dans Chrome** (instance jetable, jamais la base réelle ; fenêtre non redimensionnable : utiliser un cadre `iframe` de 360 / 768 px sur la même origine) : « Stock Pains du Jour » (3 colonnes, jour passé), badge d'écart de fournée, onglet « Statistiques » avec de vrais mouvements (ligne D1 vue par la direction, sel en sacs et en boîtes), modale de clôture et bannière de blocage des ventes (BUG-973, jamais vues à l'écran avec des données), création d'un client (l.508), « Historique du client » dans les 3 thèmes (l.504).
4. **Ta modale de clôture (BUG-973)** : appeler `GET /api/production/sessions/shift-end-status/` (déclenche la clôture automatique) ; demander le reste de la journée (un seul par catégorie), pas celui de l'équipe ; voir #45-A.
5. **Intrants I-3, I-4, I-5** (les tiens) : réutiliser `production/intrants_stats.py::compute_rows` ; export Excel avec « reste/sac » et « reste/boîte » du sel.
6. **Série finale** de toutes les parties sur le code fusionné, **en une seule fois et SANS passer minuit** (les tests qui dépendent de la date du jour échouent si la série traverse minuit) : `core clients commissions sync chat` puis `production sales treasury finance blockchain`, un processus lourd à la fois ; `makemigrations --check` ; `tsc` ; `npm run build`. Les tests de concurrence SQLite échouent sous charge : les rejouer seuls avant de conclure.
7. **Clôture du projet** : écrire « partie A terminée » (au nom de dev-a, avec les points ci-dessous) et « partie B terminée » dans `docs/COMMUNICATION_A_B.md` ; mettre à jour `docs/PR_dev-c_vers_main.md` ; **la pull request vers `main` seulement sur ordre du responsable**.

## 3. Ce qui reste à poser au client (ne rien coder avant la réponse)

Rotation de 24 h (Q-017 à Q-021 ; l.460, 470), régularisation d'un « Non servi » (l.462), tarif figé et catégories du CA (Q-028 ; BUG-513, 518, 520), valorisation des invendus/déclassés/gratuits (Q-043 ; BUG-1200), « stock de départ compté comme vendu » (Q-051), délai et conditions de la clôture automatique (Q-053), les 5 points de BUG-973, BUG-1075 (réconciliation saisie après clôture : décision provisoire de dev-a = clôture figée), BUG-625, 671, 1002, 1101, BUG-083 contre BUG-988, l'huile et le signe de l'écart (Q-044 à Q-050), contradiction ligne 506 contre Q-026 (taux de commission par boulangerie : Q-052), montant de la carte (« 1 000 FC ? »), questions 1 et 3 et Q-022 à Q-024 de `reponses-clients.md`, création de facture et remboursement par le livreur (Q-027).

## 4. Pièges (appris en travaillant)

- **Git** : ajouter les fichiers **par chemin**, jamais `git add docs` ni `git add -A` (des captures `docs/qa/captures/*.png` modifiées par les agents de test ont fait refuser un push par le serveur : erreur HTTP 408) ; vérifier `git diff --name-only origin/<branche>..HEAD | grep -E "\.png$|\.sqlite3|backend/media"` avant de pousser ; une fusion refusée (« Merge with strategy ort failed ») signifie que des fichiers non commités gênent : commiter ou attendre la fin des agents.
- **Fichiers corrompus** : une coupure de session peut remplir un fichier d'octets nuls (3 cas) ; si un fichier modifié est vide ou illisible, le réécrire depuis `git show HEAD:<fichier>` et contrôler `git diff`.
- **Processus de test** : un `nohup` Bash ne survit pas à une coupure de session ; lancer les longues séries avec `Start-Process` (PowerShell) en sortie redirigée vers un fichier ; suivre `rej.err` (les `.` et `F` sont sur la sortie d'erreur).
- **Navigateur** : deux navigateurs Chrome sont connectés au compte : demander lequel utiliser ; la page de test devient muette si la machine est saturée par une série : attendre la fin.
- **Serveurs de test de dev-a** (ports 8001 backend, 5174 Vite, base jetable dans le scratchpad de dev-a, comptes `zz_v_*`) : à toi de les ignorer ; ne les réutilise pas.
- **Hors périmètre** : desktop (Electron, installeur), documentation de livraison, e2e Playwright (pas d'agent testeur).
