# Rapport dev-backend — 2026-11-10

## Ticket traité : BUG-155

**Titre** : Calcul/clôture automatique du reste du jour à l'heure de fin de créneau d'une équipe
(remarque.md l.414).

**Statut** : `OUVERT` → `CORRIGÉ` (mis à jour dans `docs/qa/REGISTRE_BUGS.md`, fiche détaillée
complétée ; seul le testeur d'origine ou le coordinateur peut passer ce ticket à `VÉRIFIÉ`).

### Cause

Aucune détection/clôture automatique n'existait pour le cas où une fournée reste ouverte après
l'heure de fin de créneau configurée sur `Node.team_a_end_time`/`team_b_end_time` (BUG-130/131). La
saisie manuelle intégrée à la clôture (`ProductionSessionViewSet.close()`, BUG-093/BUG-152) reste la
seule voie de clôture, sans jamais être déclenchée si personne ne clôture manuellement.

### Correction

Fichier modifié : `backend/production/views.py` (uniquement). Aucune migration — `Node.team_a_end_time`/
`team_b_end_time` existaient déjà.

1. **Extraction** de `_close_production_session(session, remaining_entries, request_user)` : reprend
   mot pour mot le corps de `ProductionSessionViewSet.close()` (transaction atomique, recoupement via
   `_build_reconciliation_querysets`/`_compute_reconciliation`, upsert idempotent des `BreadDisposal`
   REMAINING, `DailyBreadStockSnapshot.record_snapshot()`, notification DANGER si anomalie,
   `log_activity`). `close()` ne fait plus que parser/valider le payload `remaining` optionnel puis
   délègue à cette fonction unique — comportement de `close()` strictement inchangé.
2. Constante `SHIFT_END_GRACE_MINUTES = 30` (délai de grâce documenté dans le code, décision déjà
   actée par le client dans la fiche BUG-155).
3. Helper `_current_bread_stocks(node)` : lignes `BreadStock` courantes du nœud, triées par
   `bread_price__unit_price` (même convention que `BreadStockByDateView`), source unique du reste
   physique.
4. Nouvelle action `GET /api/production/sessions/shift-end-status/?node=<code ou pk>` (routée
   automatiquement via le `DefaultRouter` existant sous `basename='production-session'`, sans
   modification de `production/urls.py`). Permission `IsAuthenticated` (`get_permissions()` étendu),
   contrairement à `close()` qui reste `IsGerant` — un facturier seul après l'heure de fin de créneau
   doit aussi déclencher/consulter l'endpoint. Isolation par nœud identique au reste du module
   (`_resolve_node`, non-HQ jamais sur un autre nœud que le sien).
   - Itère les équipes A puis B (une seule traitée par appel — créneaux non chevauchants,
     CLAUDE.md §5.2). Pour la première équipe dont l'heure de fin est dépassée aujourd'hui et dont la
     session n'est ni absente ni close :
     - `elapsed >= 30 min` → clôture forcée via `_close_production_session` avec
       `remaining_entries` = quantités physiques actuelles (`BreadStock.qty_available`) → réponse
       `{"pending_validation": false, "auto_closed": true, "team": "A"|"B"}`.
     - `elapsed < 30 min` → pas de clôture → réponse `{"team", "session", "pending_validation": true,
       "remaining": [{"bread_price", "label", "quantity_suggested"}], "auto_closed": false}`.
   - Aucune équipe concernée → `{"pending_validation": false}`.

### Test de non-régression

Nouveau fichier `backend/production/tests/test_bug155_shift_end_auto_closure.py` (7 tests, tous
nouveaux — aucun `@expectedFailure` à retirer, ce ticket n'avait pas de test préexistant) :
- dépassement < 30 min → `pending_validation=true`, aucune clôture ;
- dépassement > 30 min → clôture automatique effective, `BreadDisposal REMAINING` créé avec les
  quantités physiques du moment ;
- limite exacte à 30 min → clôture (`>=`) ;
- session déjà close manuellement → aucune action, même largement après l'heure de fin ;
- aucune session déclarée pour l'équipe/jour → rien de `pending` ;
- heure de fin pas encore atteinte → rien de `pending` ;
- non-régression explicite : l'appel volontaire `close()` avec `remaining` fourni dans le corps de la
  requête (BUG-152) produit un résultat identique à avant ce ticket, et n'est jamais retouché par
  l'appel « fin de créneau » une fois la session close.

Le temps est maîtrisé par `unittest.mock.patch('django.utils.timezone.now', return_value=...)`
(pas de dépendance `freezegun` dans `requirements.txt` — confirmé absente, pas ajoutée).

Résultat local avant la correction : `test_bug155_...` n'existait pas (endpoint 404). Après
correction : 7/7 verts.

### Suite complète

- `python manage.py test` : **611 tests, OK** (suite complète, aucune régression — y compris
  `production/tests/test_closure.py`, BUG-093/BUG-152, inchangé).
- `python manage.py makemigrations --check --dry-run` : `No changes detected`.

### Impact contrat API

Nouvel endpoint uniquement (`GET /api/production/sessions/shift-end-status/`) — aucun contrat
existant modifié (`close()` conserve exactement son contrat d'entrée/sortie). Le ticket lié
`BUG-156` (déjà ouvert, assigné `dev-frontend`) couvre la consommation de ce nouvel endpoint côté
frontend ; aucun ticket supplémentaire n'a été nécessaire.

## Tickets en attente

Aucun autre ticket backend n'a été traité dans cette session (périmètre limité à BUG-155 par la
consigne reçue).

## Risques / points d'attention pour la suite

- `SHIFT_END_GRACE_MINUTES` (30 min) est une valeur documentée dans le ticket par le coordinateur,
  pas une réponse du client à une question explicite sur ce chiffre précis — à reconfirmer si le
  client la juge trop courte/longue en usage réel.
- L'endpoint ne traite qu'une équipe par appel (la première en retard, A avant B) : si les deux
  équipes d'un même nœud sont simultanément en attente de validation/clôture forcée (cas rare —
  suppose un créneau A très en retard ET un créneau B déjà terminé le même jour), un seul appel ne
  renverra que l'équipe A ; un appel ultérieur (après résolution de A) renverra B. Cohérent avec le
  contrat demandé par le ticket (une équipe par réponse) mais à garder en tête côté frontend
  (BUG-156) : il faudra probablement re-sonder immédiatement après une clôture/validation réussie
  plutôt que d'attendre le prochain intervalle de polling, pour ne pas retarder la détection de la
  seconde équipe.
- Pas d'infra de tâches planifiées (confirmé absent de `requirements.txt`/`settings.py`) : la
  clôture forcée automatique ne se déclenche QUE si quelqu'un (n'importe quel utilisateur du nœud,
  grâce à la permission `IsAuthenticated`) consulte l'endpoint après le délai de grâce. Si personne ne
  se connecte du tout ce jour-là à cette boulangerie après la fin de créneau, la session restera
  ouverte indéfiniment jusqu'à la prochaine connexion — comportement voulu et documenté (évaluation
  paresseuse), mais à rappeler si le client s'attend à une clôture "au plus tard à telle heure" même
  sans connexion.

## Fichiers modifiés/créés

- `d:\Projects\kiesse\backend\production\views.py` (extraction `_close_production_session`,
  `_current_bread_stocks`, constante `SHIFT_END_GRACE_MINUTES`, nouvelle action
  `shift_end_status`, permission étendue).
- `d:\Projects\kiesse\backend\production\tests\test_bug155_shift_end_auto_closure.py` (nouveau).
- `d:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (statut BUG-155 → `CORRIGÉ`, fiche détaillée
  complétée).

---

## Ticket traité (seconde session, reprise d'un travail interrompu) : BUG-158

**Titre** : `shift_end_status()` plante (HTTP 500) en clôture forcée si le stock physique d'une
catégorie est négatif.

**Statut** : `EN COURS (dev-backend)` → `CORRIGÉ` (ligne du tableau + fiche). À vérifier par
`testeur-production`.

### Cause

`shift_end_status()` (BUG-155) transmettait `BreadStock.qty_available` négatif à
`_close_production_session()` ; `BreadDisposal.quantity` était un `PositiveIntegerField` ->
`IntegrityError` (CHECK), 500 répété à chaque polling.

### Correction (décision FINALE du client : « enregistre le stock même s'il est négatif »)

Remplace le clamp à 0 décidé d'abord par le coordinateur.

- `models.py` : `quantity` en `IntegerField` + `CheckConstraint` (négatif permis seulement pour
  `REMAINING`) ; migration `0022_bug158_breaddisposal_negative_remaining.py`.
- `serializers.py` : `BreadDisposalSerializer.validate()` refuse le négatif hors REMAINING.
- `views.py` : clôture forcée enregistre le reste tel quel + notification `WARNING` (catégorie et
  valeur), même transaction ; `quantity_suggested` négatif en mode pending ; `close()` accepte un
  `remaining` négatif ; `BreadStock` jamais modifié.
- `requirements.txt` : `django>=5.1,<6.0` ; lancer le serveur avec `backend\.venv`.

### Tests

- `test_bug158_auto_closure_negative_stock.py` (nouveau), `test_daily_stock_snapshot.py` (test
  « négatif -> 400 » converti en « accepté » + test « non entier -> 400 »).
- Test du testeur `NegativePhysicalStockAutoClosureTests` : `@unittest.expectedFailure` retiré, logique
  inchangée (ses assertions attendaient déjà -20).

### Suite complète

`python manage.py test` (suite complète, venv `backend.venv`) : 629 tests, OK. `makemigrations --check --dry-run` : aucun changement.

### Impact contrat API

`close()` n'a plus de 400 pour un `remaining` négatif ; `quantity_suggested` peut être négatif. Voir
BUG-159 côté frontend (déjà CORRIGÉ).

### Risques / points d'attention

- `opening-confirmation` (BUG-133) refuse toujours une `qty` négative (400) alors que la modale propose
  le stock physique, négatif le cas échéant : décision métier requise (non modifié, test existant).
- Cause amont non traitée : `BreadDisposalViewSet.perform_create` laisse le stock de pain devenir
  négatif sans alerte (cf. BUG-143).

### Fichiers modifiés (BUG-158)

- `d:\Projects\kiesse\backend\production\views.py`
- `d:\Projects\kiesse\backend\production\tests\test_bug158_auto_closure_negative_stock.py`
- `d:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md` (ligne et fiche BUG-158 uniquement)


## BUG-162 (volet backend) — confirmation du stock de départ avec quantité négative

- Statut : CORRIGÉ (jamais VÉRIFIÉ par dev-backend).
- `DailyOpeningConfirmationView.post` n'émet plus de 400 pour `qty < 0` (décision client 2026-11-10) ; flottants non entiers/booléens refusés (400). Modèles déjà `IntegerField` : aucune migration. Propagation vérifiée : pas de ligne CARRYOVER négative, `qty_adjusted` correct, rapport de clôture (`reste_du_hier` = -qty_confirmed) sans double comptage, snapshot de la veille inchangé.
- Tests : nouveau `test_bug162_opening_confirmation_negative.py` (7) ; `test_post_rejects_negative_quantity` remplacé par `test_post_accepts_negative_quantity` (changement de règle client, documenté dans la fiche).
- Résout le point « opening-confirmation refuse toujours une qty négative » listé plus haut dans les risques de BUG-158.
- Fichiers : `backend/production/views.py`, `backend/production/tests/test_daily_opening_confirmation.py`, `backend/production/tests/test_bug162_opening_confirmation_negative.py`, `docs/qa/REGISTRE_BUGS.md` (ligne et fiche BUG-162).


## BUG-165 — double clôture/notification sur requêtes `shift-end-status` entrelacées

- Statut : CORRIGÉ (jamais VÉRIFIÉ par dev-backend).
- Cause : `shift_end_status` lisait `session.is_closed` sans verrou et la transaction de clôture forcée ne revérifiait pas l'état.
- Correction (`backend/production/views.py`) : dans le `transaction.atomic()` de la clôture forcée, relecture de la session par `select_for_update()` ; si elle est déjà close, on ne fait rien (ni clôture, ni notification, ni `log_activity`) et on passe (`continue`) ; la réponse est alors `{"pending_validation": false}` sans `auto_closed`. Seule la requête qui a réellement clôturé renvoie `auto_closed: true` (pas de doublon d'annonce BUG-157). `close()` volontaire et règle du stock négatif inchangés.
- Test : `test_verif_bug155_162_testeur_production.py::ShiftEndIdempotenceTests::test_interleaved_requests_create_a_single_notification_BUG_165` (décorateur `@expectedFailure` retiré, passe ; logique intacte).
- Impact contrat API : aucun. Limite : sous SQLite `select_for_update` est sans effet, mais l'écriture est de toute façon sérialisée ; sous PostgreSQL le verrou de ligne assure l'exclusion.
- Fichiers : `backend/production/views.py`, `backend/production/tests/test_verif_bug155_162_testeur_production.py`, `docs/qa/REGISTRE_BUGS.md` (fiche BUG-165).
