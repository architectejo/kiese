# Rapport — dev-backend, 2026-11-09 — BUG-133 : confirmation du RESTE DU HIER (stock de départ)

## Mission

Suite de la demande client remarque.md l.396 (BUG-130/131, déjà livrés). Pièce manquante : à sa
première connexion de la journée, le gérant doit voir une boîte modale qui propose automatiquement,
par catégorie de pain, le nombre de pains restants = stock disponible actuel. Il peut modifier ces
nombres ou les valider directement. Cette validation devient la valeur officielle du « RESTE DU
HIER » utilisée pour démarrer la journée (et donc pour le rapport de Clôture Journalière, BUG-120).

Précision ajoutée par le coordinateur en cours de mission (remarque.md l.396) : la boîte modale
n'est pas un prompt ponctuel au login — elle doit se réafficher à chaque changement de page du
dashboard tant qu'aucune confirmation n'existe pour (nœud, équipe, aujourd'hui). Intégrée dans le
contrat d'API (`GET` volontairement léger) et explicitement décrite dans le sous-ticket frontend
BUG-134.

## Ticket traité

- **BUG-133** (nouveau — numéro vérifié libre avant attribution, dernier ticket existant au moment
  de l'ouverture : BUG-132) : CORRIGÉ.
- **BUG-134** (sous-ticket lié, ouvert pour `dev-frontend`) : OUVERT — pas de code frontend touché.

## Analyse préalable (lecture demandée avant de commencer)

- `docs/qa/REGISTRE_BUGS.md` fiches BUG-130/BUG-131 (créneaux horaires équipe A/B, `Node.
  active_team_at()`) et BUG-118 (`DailyBreadStockSnapshot`, mécanisme RESTE DU JOUR/RESTE DU HIER
  existant, formule confirmée par le client : `reste_du_hier(jour N, équipe T) = −reste_du_jour`
  du dernier jour antérieur où T a clôturé, 0 si jamais clôturé) et BUG-120 (`_build_daily_closure_
  report`, rapport de clôture journalier consolidé, VÉRIFIÉ, qui consomme déjà `reste_du_hier` par
  équipe).
- `backend/core/models.py::Node.active_team_at()` : confirmé qu'il sert un usage différent
  (déterminer l'équipe active à une heure donnée), pas la confirmation explicite demandée ici — pas
  réutilisé pour déduire l'équipe de la boîte modale (voir point de conception 1 ci-dessous).
- `backend/core/models.py::User.team` : confirmé vide par défaut pour le rôle GERANT (seuls
  FACTURIER/LIVREUR l'utilisent) — confirme qu'un seul compte GERANT couvre A et B, donc l'équipe
  ne peut pas être déduite du compte connecté.
- `backend/sales/views.py` : confirmé 4 points d'appel à `_adjust_bread_stock(..., sent=...)` qui
  décrémentent `BreadStock.qty_available` à la livraison/annulation/régularisation/suppression d'une
  facture — `qty_available` est donc bien « ce qui reste après les ventes déjà déduites » (point de
  conception 3 de la mission, confirmé avant implémentation, pas supposé).

## Points de conception tranchés (documentés, pas reposés au coordinateur)

1. **Détection de « première connexion du jour » sans login par équipe** : l'équipe est choisie
   EXPLICITEMENT par le gérant dans la boîte modale (paramètre `team` du `POST`), jamais déduite
   côté serveur (ni de l'heure, ni de `Node.active_team_at()`, pensé pour un autre usage). La
   détection elle-même n'est pas un évènement de login : c'est l'absence d'une ligne
   `DailyOpeningConfirmation(node, team, date=aujourd'hui)` qui signale au frontend qu'il doit
   encore proposer la modale pour CETTE équipe — persistant côté serveur, donc naturellement
   compatible avec la précision « réaffiché à chaque changement de page » (le frontend réinterroge
   simplement le `GET`, léger par construction, à chaque changement de route).
2. **Ne jamais corrompre l'historique** : nouveau modèle `DailyOpeningConfirmation` +
   `DailyOpeningConfirmationLine`, strictement distinct de `DailyBreadStockSnapshot` (BUG-118,
   VÉRIFIÉ) — ce dernier n'est ni modifié ni relu en écriture par ce ticket. L'intégration avec
   BUG-120 se fait uniquement en SURCOUCHE dans `_build_daily_closure_report()` : une confirmation
   existante pour (node, team, report_date) devient prioritaire sur l'appel à
   `DailyBreadStockSnapshot.reste_du_hier()` pour cette équipe/catégorie/jour ; l'absence de
   confirmation laisse le calcul auto-dérivé strictement inchangé (testé explicitement : un
   scénario avec clôture réelle BUG-118 sans confirmation BUG-133 donne exactement le même résultat
   qu'avant ce ticket).
3. **Calcul proposé** : `qty_proposed` = `BreadStock.qty_available` courant par catégorie — confirmé
   net des ventes avant implémentation (voir analyse ci-dessus), pas supposé. Test dédié
   (`test_get_reflects_sales_deduction_in_proposed_stock`) prouve qu'une vente confirmée réduit
   bien la proposition.
4. **Choix de signe — à confirmer avec le client lors de la livraison frontend, non bloquant ici**
   (demande explicite de la mission, pas une ambiguïté inventée) : `DailyBreadStockSnapshot.
   reste_du_hier()` est négatif par construction (formule confirmée pour BUG-118). La mission
   demande que la validation devienne « la valeur officielle du reste du hier » — la quantité
   confirmée (positive, stock physique réel) est donc utilisée telle que saisie, SANS négation. Les
   jours confirmés afficheront donc un `reste_du_hier` positif dans le rapport BUG-120, par
   construction différent en signe des jours sans confirmation. Documenté dans le docstring du
   modèle et dans le ticket lié BUG-134 pour que ce ne soit jamais redécouvert comme un bug de
   signe plus tard — le coordinateur peut trancher définitivement avec le client au moment de la
   recette frontend si un signe unique est finalement préféré.
5. **Endpoints** : un seul `APIView` (`DailyOpeningConfirmationView`), même raisonnement que
   `DailyClosureReportView` (BUG-120) — pas rattaché à une ressource CRUD précise.

## Reproduction

Fonctionnalité neuve (jamais implémentée avant ce ticket) — pas de test préexistant à reproduire,
conformément à la procédure (« pas de reproduction possible sur du neuf, test écrit directement sans
`@expectedFailure` »).

## Correctif

### Fichiers modifiés/ajoutés

- `backend/production/models.py` :
  - `DailyOpeningConfirmation` (node, team, date, confirmed_by, confirmed_at `auto_now`,
    `unique_together=[node, team, date]`).
  - `DailyOpeningConfirmationLine` (confirmation FK CASCADE, bread_price FK PROTECT, qty_confirmed
    `IntegerField`, `unique_together=[confirmation, bread_price]`).
  - Docstrings détaillant les 5 points de conception ci-dessus.
- `backend/production/migrations/0019_dailyopeningconfirmation_and_more.py` : migration standard,
  deux nouveaux modèles, aucune donnée existante à migrer.
- `backend/production/views.py` :
  - Import de `DailyOpeningConfirmation`, `DailyOpeningConfirmationLine`.
  - `_build_daily_closure_report()` : nouvelle étape (avant la boucle par catégorie) qui résout les
    confirmations existantes pour (node, report_date) dans un dict `(team, bread_price_id) → qty`.
    `reste_du_hier_by_team` utilise cette valeur quand elle existe pour (team, bp_id), sinon l'appel
    inchangé à `DailyBreadStockSnapshot.reste_du_hier(...)`. Aucune autre ligne de cette fonction
    modifiée (diff minimal).
  - `_opening_confirmation_resolve_node()` (nouvelle fonction utilitaire, même règle que
    `_resolve_node()`/`DailyClosureReportView.get()` — non-HQ limité à son nœud, `node` fourni par
    un non-HQ ignoré silencieusement, HQ doit préciser `node`, même motif que BUG-022/025/056).
  - `DailyOpeningConfirmationView` (nouvelle `APIView`, `permission_classes = [IsGerant]`) :
    - `GET` : propose `qty_proposed` par catégorie active + état `confirmed`/`lines` pour les deux
      équipes A et B. Volontairement léger (deux requêtes filtrées simples, aucune agrégation
      lourde comme `_build_daily_closure_report`) pour être interrogé à chaque changement de route
      du dashboard sans ralentir la navigation (demande explicite ajoutée en cours de mission).
    - `POST` : valide `team` (A/B), `date` (optionnelle, défaut aujourd'hui), `lines` (liste non
      vide de `{bread_price, qty}`, `qty` entier ≥ 0, pas de doublon de catégorie, catégorie
      existante) ; upsert atomique (`transaction.atomic()`) de l'en-tête et de toutes les lignes
      ensemble (`update_or_create`, même idiome que `DailyBreadStockSnapshot.record_snapshot`,
      BUG-118) ; une resoumission remplace intégralement les lignes précédentes (catégorie retirée
      entre deux soumissions = ligne supprimée, pas laissée obsolète) ; `log_activity` sur succès.
- `backend/production/urls.py` : route littérale `opening-confirmation/`, avant le routeur DRF
  (même pattern que `daily-closure/`).
- `backend/production/tests/test_daily_opening_confirmation.py` (nouveau, 22 tests, sans
  `@expectedFailure`) :
  - `GET` : proposition = stock disponible net des ventes, détection « non confirmé » par équipe,
    défaut à aujourd'hui, date invalide → 400.
  - `POST` : confirmation telle que proposée, confirmation MODIFIÉE (valeur saisie retenue, pas la
    proposition), idempotence (resoumission remplace, catégorie retirée supprimée), rejets
    (quantité négative, équipe invalide, `lines` vide, catégorie inconnue).
  - Intégration BUG-120 : confirmation prioritaire sur le calcul auto-dérivé pour l'équipe/jour
    confirmés ; jour/équipe NON confirmé garde exactement l'ancien calcul (non-régression) ;
    `DailyBreadStockSnapshot` jamais modifié par une confirmation.
  - Permissions : GERANT non-HQ ne peut jamais forger `node` (GET et POST), HQ doit préciser
    `node`, FACTURIER refusé (403), requête non authentifiée refusée.
- `docs/qa/REGISTRE_BUGS.md` : lignes BUG-133/BUG-134 (tableau de suivi) + fiches détaillées.

### Test de non-régression

`backend/production/tests/test_daily_opening_confirmation.py` (nouveau, n'existait pas avant ce
ticket — pas de `@expectedFailure` à retirer, fonctionnalité neuve). `test_daily_closure_report.py`
et `test_daily_stock_snapshot.py` rejoués sans aucune modification de leur côté (aucune assertion
changée), pour confirmer que l'intégration BUG-133 n'affecte aucun scénario déjà couvert sans
confirmation explicite.

## Résultats

- `python manage.py test production.tests.test_daily_opening_confirmation -v 2` → **22/22 OK**
  (146 s).
- `python manage.py test production sales` (toutes les apps directement concernées/dépendantes de
  ce correctif, même périmètre que la vérification BUG-120) → **158/158 OK** (613,8 s), confirmé
  indépendamment après la fin de l'exécution.
- `python manage.py test` (suite complète) : terminée après la rédaction initiale de ce rapport,
  ralentie par la même contention CPU que documentée pour BUG-118/119/120 (plusieurs exécutions de
  tests simultanées dans cette session) — **526/526 tests OK, 0 échec** (1688,4 s). Confirmation
  finale obtenue, aucune régression détectée sur l'ensemble du dépôt.
- `python manage.py makemigrations --check --dry-run` → « No changes detected ».
- `python manage.py check` → « System check identified no issues (0 silenced) ».

## Impact API

**Nouvel endpoint uniquement** (`GET`/`POST /api/production/opening-confirmation/`), aucun contrat
d'API existant modifié au sens strict. Point à signaler explicitement (documenté dans BUG-133/134) :
`reste_du_hier` dans `GET /api/production/daily-closure/` (BUG-120) peut désormais afficher une
valeur POSITIVE pour un jour/équipe confirmé via ce nouveau mécanisme (au lieu de toujours négative)
— comportement voulu (point de conception 4), pas une régression, mais le frontend qui consomme déjà
ce rapport (écran « Clôture Journalière ») ne doit pas le traiter comme une anomalie d'affichage.

## Ticket lié ouvert pour dev-frontend

**BUG-134** — boîte modale frontend, à implémenter dans `frontend/src/components/layout/
DashboardLayout.tsx` (pas page par page), interrogeant le `GET` à chaque changement de route et
réaffichant la modale tant qu'une confirmation n'existe pas pour l'équipe concernée/aujourd'hui.
Contrat d'API exact, exemples de réponse et contraintes ergonomiques détaillés dans la fiche
BUG-134 du registre.

## Risques / points en attente pour la suite

- BUG-134 (frontend) reste `OUVERT` — aucune boîte modale visible pour le gérant jusqu'à son
  implémentation ; le mécanisme backend est prêt mais invisible sans lui.
- Le choix de signe (point de conception 4) est documenté comme une décision assumée mais pas
  formellement validée par le client — à confirmer au plus tard lors de la recette de BUG-134.
