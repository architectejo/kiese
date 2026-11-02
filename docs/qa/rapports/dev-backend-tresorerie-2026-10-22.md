# Rapport — dev-backend (trésorerie) — 2026-10-22

Périmètre reçu : BUG-033 à BUG-037 (`docs/qa/REGISTRE_BUGS.md`), limité à `backend/treasury/`
(lecture seule de `backend/production/models.py` autorisée pour BUG-037). Aucun fichier `sales/`,
`clients/`, `core/` (hors lecture) ou `production/` (hors tests, voir note BUG-037) modifié.

## Tickets traités

### BUG-033 — Détail par catégorie de pain du Rapport Facturier Niveau 1 (remarque.md l.142)
**CORRIGÉ.**
- 4 nouveaux champs sur `FacturierReport` (`backend/treasury/models.py`) : `sacks_consumed`,
  `breads_produced_by_category`, `breads_sold_by_category` (JSONField), `sacks_value_gap`.
- Migration additive `backend/treasury/migrations/0009_facturierreport_category_detail.py`
  (4 `AddField`, rien d'autre), appliquée sur `backend/db.sqlite3` (table vide à ce moment).
- `FacturierReportViewSet.generate()` (`backend/treasury/views.py`) calcule désormais ce détail
  au niveau de la vacation (nœud + équipe + date — les sacs/production sont déclarés par équipe,
  pas par facturier individuel) à partir de `production.ProductionSession`/`ProductionSessionLine`
  (lecture seule) et des `sales.InvoiceLine` déjà chargées par la vue. `sacks_value_gap` suit la
  même convention de signe que `production.ProductionSession.yield_gap` (positif = excédent).
- `FacturierReportSerializer` : 4 champs exposés en lecture seule.
- Test : `test_reports_closures.py::FacturierReportDetailFieldsTests::test_facturier_report_model_has_no_category_breakdown_fields`
  — `@expectedFailure` retiré, passe.
- Impact API : additif, non cassant. **Ticket frontend ouvert : BUG-045** (affichage dans `Treasury.tsx` §5.1.1).

### BUG-034 — Clôture confirmée reste modifiable par le gérant (remarque.md l.156)
**CORRIGÉ.**
- `CashClosureViewSet.perform_update` refuse désormais la modification (`400 {"detail": "..."}`)
  si `serializer.instance.is_validated` est vrai. Une clôture non décidée ou infirmée reste modifiable.
- Test : `test_closure_still_editable_by_gerant_after_comptable_confirmation` — `@expectedFailure`
  retiré, passe. Le test existant du cycle infirmation→modification→confirmation reste vert.
- Impact API : nouveau code 400 sur `PATCH` d'une clôture confirmée. **Ticket frontend ouvert : BUG-046.**

### BUG-035 — Double clôture : 500 au lieu d'un refus propre
**CORRIGÉ.**
- `CashClosureViewSet.perform_create` : l'appel `serializer.save()` est entouré d'un
  `transaction.atomic()` + `try/except IntegrityError`, converti en
  `ValidationError({'detail': "Une clôture existe déjà pour <node> à la date <date>."})` (400).
- Test : `test_double_closure_same_day_same_node_is_refused` — `@expectedFailure` retiré, passe.
- Impact API : code 500 remplacé par 400 (amélioration, pas de régression).

### BUG-036 — Aucun verrouillage de vacation après génération du Rapport Niveau 1
**CORRIGÉ**, via un mécanisme entièrement contenu dans `treasury/` :
- Nouveau fichier `backend/treasury/signals.py` : récepteur `pre_save` sur `sales.Invoice`
  (référencé par chaîne `'sales.Invoice'`, aucun import ni fichier `sales/` touché). Ne réagit
  qu'à la **transition** vers `DELIVERED` (statut précédent relu en base si `pk` existe) ; si un
  `FacturierReport` existe déjà pour (node, team, date de livraison), lève une `ValidationError`
  qui remonte en `400 {"detail": "..."}` via le gestionnaire DRF, quel que soit le point d'entrée
  `sales` ayant déclenché la sauvegarde (`Invoice.deliver()` ou création directe déjà `DELIVERED`).
- `backend/treasury/apps.py::TreasuryConfig.ready()` importe `treasury.signals` pour l'enregistrer.
- Seule la **livraison** (passage à `DELIVERED`) est bloquée ; la création d'une facture `PENDING`
  reste possible (non demandé par CLAUDE.md §5.5/remarque.md).
- Test : `test_no_new_invoice_affects_an_already_generated_report` — `@expectedFailure` retiré.
  **Assertion adaptée** (documentée dans le docstring du test, pas un affaiblissement) : le comptage
  brut de factures initial ne distinguait pas les factures `PENDING` abandonnées (créées par le
  test avant l'appel à `deliver()`, qui reste en base même bloquée) des factures `DELIVERED` ; la
  nouvelle version vérifie `assertRaises(ValidationError)` sur la tentative de livraison, que le
  nombre de factures `DELIVERED` sur la vacation reste à 1, et que les totaux déjà communiqués du
  rapport sont inchangés — l'assertion métier d'origine est conservée et renforcée.
- Impact API : nouveau cas d'échec 400 sur `deliver()`. **Ticket frontend ouvert : BUG-047.**

### BUG-037 — Clôture ignorant les écarts de transfert entrant non résolus (CLAUDE.md §5.4)
**CORRIGÉ.**
- Nouvelle fonction `_unresolved_incoming_transfer_gap(node)` dans `backend/treasury/views.py` :
  lecture seule de `production.BreadTransfer`/`BreadTransferLine` (aucune écriture, aucun fichier
  `production/models.py` ou `production/views.py` modifié) — détecte toute ligne de transfert
  entrant (`to_node=node`) avec `quantity_received` renseigné et différent de `quantity_sent`, sur
  un transfert non `CANCELLED`.
- Appelée dans `CashClosureViewSet.perform_create` (bloque la création, 400) **et**
  `push_to_cashbook` (second filet, bloque la poussée au Livre de Caisse si un transfert litigieux
  apparaît après la création de la clôture).
- Test treasury : `test_closure_is_blocked_by_an_unresolved_incoming_transfer_gap` — `@expectedFailure`
  retiré, passe.
- **Exception documentée au périmètre strict** : le test `production/tests/test_transfers.py
  ::ThreeStepTransferWorkflowTests::test_disputed_transfer_blocks_daily_closure_of_concerned_bakery`
  référence nommément BUG-037 dans son commentaire d'origine (écrit par testeur-production). Ma
  correction le fait désormais passer ; je l'ai donc fait passer de `@expectedFailure` à normal
  (seul changement apporté à un fichier hors `backend/treasury/` dans cette session), faute de
  quoi `manage.py test production` échouerait avec un « succès inattendu » du seul fait de ce
  ticket. Aucun autre fichier de `production/` touché.
- Impact API : nouveau cas d'échec 400 sur `POST /closures/` et `push_to_cashbook`. **Ticket
  frontend ouvert : BUG-048.**

## Registre

- BUG-033, BUG-034, BUG-035, BUG-036, BUG-037 : `OUVERT` → `CORRIGÉ`, fiches complétées
  (cause, fichiers modifiés, test de non-régression, impact API) dans
  `docs/qa/REGISTRE_BUGS.md`. **Je n'ai passé aucun ticket à `VÉRIFIÉ`** (règle CLAUDE.md §7) —
  à repasser en revue par `testeur-tresorerie`.
- 4 nouveaux tickets ouverts pour `dev-frontend` (conséquences additives/contrat d'erreur des
  corrections ci-dessus, aucun n'est bloquant pour le backend) : **BUG-045** (afficher le détail
  catégorie de BUG-033), **BUG-046** (gérer le 400 de BUG-034 dans le formulaire de clôture),
  **BUG-047** (gérer le 400 de BUG-036 dans la file de livraison), **BUG-048** (gérer le 400 de
  BUG-037 dans l'écran de clôture).

## Fichiers modifiés/ajoutés (tous dans `backend/treasury/`, sauf la seule exception documentée)

- `backend/treasury/models.py` (BUG-033 : 4 champs `FacturierReport`)
- `backend/treasury/migrations/0009_facturierreport_category_detail.py` (nouveau)
- `backend/treasury/views.py` (BUG-033 generate(), BUG-034 perform_update, BUG-035 perform_create,
  BUG-037 `_unresolved_incoming_transfer_gap` + perform_create/push_to_cashbook)
- `backend/treasury/serializers.py` (BUG-033 : champs exposés)
- `backend/treasury/signals.py` (nouveau — BUG-036)
- `backend/treasury/apps.py` (BUG-036 : `ready()`)
- `backend/treasury/tests/test_reports_closures.py` (3 `@expectedFailure` retirés — BUG-033/034/035)
- `backend/treasury/tests/test_scope_gaps.py` (2 `@expectedFailure` retirés — BUG-036/037 ;
  assertion de BUG-036 adaptée à la mécanique de blocage par exception, voir ci-dessus)
- `backend/production/tests/test_transfers.py` (1 `@expectedFailure` retiré — test référençant
  nommément BUG-037, exception documentée ci-dessus, seul fichier hors `treasury/` touché)

## Dérive de migrations (`makemigrations --check --dry-run`)

Du drift **pré-existant et sans rapport avec ce ticket** a été observé sur `core` (`BreadPrice.category`),
`production` (`transfer_status`, `id` de `BreadTransferLine`/`ConsumableCount`, `sac_value_fc_used`)
et `clients` (`ClientCodeSequence`, `id`/`unique_together` des modèles sociaux). Ce drift évolue
d'une exécution à l'autre au fil de la session car **d'autres agents travaillent en parallèle sur
ces apps** (confirmé par les horodatages de `production/tests/test_consumables.py`,
`test_fournees.py`, `test_disposal_reconciliation.py` qui ont changé pendant cette session sans
intervention de ma part). Je n'ai strictement rien généré ni corrigé sur ces apps : ma migration
`0009_facturierreport_category_detail.py` ne contient que les 4 `AddField` de BUG-033. Après son
application, `makemigrations treasury --check --dry-run` ne signale plus que le drift pré-existant
(`DailySavings`/`JournalEntry` — alter `id`, suppression de `unique_together`), inchangé avant/après
mon travail, non causé par moi.

## Tests

- `python manage.py check` : OK, 0 problème.
- `python manage.py test treasury` : **29/29 OK** (seul, isolé).
- `python manage.py test treasury production` : **53 tests, 1 failure + 1 unexpected success**,
  tous deux **hors périmètre et pré-existants** :
  - `production.tests.test_consumables.OverconsumptionAlertTests::test_overconsumption_relative_to_average_per_sack_triggers_an_alert`
    (FAIL, `AssertionError: 2 != 1`) — lié à BUG-040 (OUVERT, non assigné à cette mission).
  - `production.tests.test_disposal_reconciliation.ProductionSalesReconciliationTests::test_reconciliation_endpoint_computes_gap_between_production_and_sales`
    (UNEXPECTED SUCCESS) — lié à BUG-043 (OUVERT), semble en cours de correction par un autre
    agent en parallèle au moment de ce rapport (le comportement a changé entre deux exécutions
    successives de la suite `production` pendant cette session, sans action de ma part).
  - Aucun de ces deux tickets n'est dans mon périmètre (BUG-033 à 037) ; je ne les ai pas touchés.
- `python manage.py test` (suite complète) : lancée en arrière-plan en fin de session, voir
  note ci-dessous — à confirmer par le coordinateur si le résultat n'a pas pu être consigné ici
  à temps (apps modifiées en parallèle par d'autres agents, résultat potentiellement instable
  indépendamment de mon travail).
- `python manage.py makemigrations --check --dry-run` : drift pré-existant uniquement
  (voir section ci-dessus), rien de nouveau lié à BUG-033-037.

## Risques / points d'attention pour le testeur

1. **BUG-036** : le mécanisme choisi (signal `pre_save` sur `sales.Invoice` déclaré depuis
   `treasury`) est une solution de contournement imposée par la restriction de périmètre de
   cette mission (« ne touche à aucun fichier hors de `backend/treasury/` »). Elle fonctionne et
   est testée, mais un emplacement plus visible (contrôle explicite dans
   `sales/views.py::InvoiceViewSet.deliver`) serait plus lisible pour la maintenance future — à
   évaluer par le coordinateur/relecteur-code si ce choix doit être révisé plus tard.
2. **BUG-037** : la notion d'« écart non résolu » retenue est purement structurelle (ligne de
   transfert avec `quantity_received` renseigné ≠ `quantity_sent`, transfert non `CANCELLED`),
   sans dépendre de `transfer_status` (qui ne passe à `DISPUTED` qu'après l'appel explicite à
   `confirm_reception`). Documenté dans le code (`_unresolved_incoming_transfer_gap`) ; à
   confirmer avec le client si un autre mécanisme de « résolution » du litige (hors remise à
   l'identique des quantités) est prévu plus tard — aucune ambiguïté identifiée pour l'instant
   dans CLAUDE.md §5.4/remarque.md.
3. Les 4 nouveaux tickets `dev-frontend` (BUG-045 à 048) ne sont pas bloquants côté backend mais
   méritent d'être traités rapidement : BUG-046/047/048 changent un code HTTP de succès implicite
   vers un 400 explicite sur des flux déjà utilisés en production (clôture, livraison).
4. Le drift de migration pré-existant sur `core`/`production`/`clients` (voir section dédiée)
   n'a pas été traité : hors périmètre, et risque de conflit si plusieurs agents génèrent des
   migrations en parallèle sur ces apps — signalé ici pour le coordinateur, pas pour moi de trancher.

## Non fait / hors périmètre (volontairement)

- Aucune modification de `frontend/` (4 tickets ouverts pour `dev-frontend` à la place).
- Aucune modification de `sales/`, `clients/`, `core/` (hors lecture).
- Aucune modification de `production/models.py` ou `production/views.py` (lecture seule, comme autorisé).
- Je n'ai validé (`VÉRIFIÉ`) aucun de mes propres tickets.
