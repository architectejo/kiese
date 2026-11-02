# Rapport testeur-tresorerie — Vérification indépendante BUG-086

Date : 2026-10-29
Agent : testeur-tresorerie

## Mandat

Vérification indépendante complète de BUG-086 (tous volets : backend « Clôture & Caisse »,
backend « Rapports Journaliers des Facturiers » §5.1.1, frontend `Treasury.tsx`), corrigé par
`dev-backend` (2 sessions) et `dev-frontend`, en attente de passage à `VÉRIFIÉ`.

## Résultat

**BUG-086 passé à VÉRIFIÉ** dans `docs/qa/REGISTRE_BUGS.md` (ligne récapitulative + 3 sections
« Vérification » de la fiche détaillée mises à jour).

## Méthode et constats

### 1. Relecture de code

- `backend/treasury/views.py` : `CashClosureViewSet.perform_create`/`perform_update` et
  `FacturierReportViewSet.generate` appellent bien `core.utils.validate_requested_date` avec la
  même règle (date future toujours refusée ; date passée exige `Config.allow_backdated_sales=True`),
  appliquée à tout rôle `IsGerant` y compris Siège (`can_access_all_nodes`) choisissant le nœud.
  Erreurs renvoyées en `400 {"detail": "..."}`, conforme CLAUDE.md §4.
- `backend/core/utils.py::validate_requested_date` : logique conforme à la description, déplacée
  proprement depuis `sales/views.py` (réimportée sous alias `_validate_requested_date`, non-régression
  BUG-083 confirmée par les tests existants).
- `frontend/src/pages/dashboard/Treasury.tsx` : `allowBackdatedSales` (lu depuis `coreApi.config.get()`),
  champs `reportDate`/`closureDate` (`<input type="date" max={today}>`), handlers
  `handleGenerateReport`/`handleCreateClosure` envoyant la date choisie uniquement si différente
  d'aujourd'hui (comportement par défaut strictement inchangé sinon), messages d'information pour
  les listes filtrées sur « aujourd'hui ». Cohérent avec le rapport dev-frontend ; aucun nouveau `any`.

### 2. Tests existants relus et rejoués

- `treasury/tests/test_bug086_closure_date_validation.py` (6 tests) → `OK`.
- `treasury/tests/test_bug086_reports_date_validation.py` (5 tests) → `OK`.
- Ajustements de setUp dans 5 fichiers préexistants (`test_bug083_verification_2026_10_29.py`,
  `test_scope_gaps.py`, `test_cashbook_level3.py`, `test_transfers.py`, `test_reports_closures.py`)
  relus ligne à ligne : **avis explicite — légitimes dans tous les cas**. Chaque activation
  temporaire de `Config.allow_backdated_sales` sert uniquement à atteindre, dans le scénario, un
  contrôle métier différent (BUG-036/BUG-037) que la nouvelle validation de date aurait sinon
  intercepté plus tôt et masqué — aucune assertion n'a été retirée ni affaiblie ; quand le test porte
  justement sur le réglage désactivé, celui-ci est restauré à `False` avant les assertions réelles.

### 3. Tests indépendants ajoutés par ce testeur

Nouveau fichier `backend/treasury/tests/test_bug086_independent_verification.py` (8 tests, tous
`OK`) :

- `HqCannotBypassDisabledSettingByPickingNodeTests` (3 tests) — (a) un rôle Siège
  (`can_access_all_nodes=True`) choisissant explicitement le nœud ne peut contourner ni le refus
  d'une date passée (réglage désactivé) ni le refus d'une date future (réglage activé), pour les
  deux volets (clôture ET génération de rapport).
- `RetroactiveReportFeedsRetroactiveClosureOfSameDayTests` (1 test) — (b) scénario intégré :
  génération du rapport Niveau 1 d'un jour passé puis clôture de CE MÊME jour passé, avec un second
  jour passé distinct piégé (montants très différents en facture ET en dépense locale) ne
  contaminant ni le rapport ni la clôture du premier jour. Confirme explicitement que le rapport
  généré pour un jour alimente bien la clôture de ce même jour, sans confusion.
- `NoRegressionOnBug034_035_036_037WithDateValidationInPlaceTests` (4 tests) — (c) non-régression
  explicite, avec la validation de date active (réglage désactivé, cas de production courant) : clôture
  confirmée reste figée (BUG-034), double clôture même jour/nœud refusée en 400 propre (BUG-035),
  régénération idempotente du rapport du jour (comportement par défaut, pas affecté par BUG-086)
  (angle BUG-036), blocage par écart de transfert entrant non résolu (BUG-037).

```
python manage.py test treasury.tests.test_bug086_independent_verification
→ Ran 8 tests ... OK
```

### 4. Suite complète

```
python manage.py test treasury sales core production commissions sync
→ Ran 241 tests in 799.701s
FAILED (failures=2)
```

Les 2 échecs (`test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario`,
`test_reports_closures.CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses`)
sont confirmés, par relecture directe du code, être exactement BUG-068/084 (date calendaire codée
en dur `'2026-10-22'` vs `Invoice.invoice_date`/`delivered_at` suivant l'horloge système réelle) —
sans rapport avec BUG-086 (aucun appel `generate`/`closures` relatif à `date.today()` dans ces
deux tests). Conforme aux rapports dev-backend.

### 5. Vérification base réelle `backend/db.sqlite3`

```
python manage.py showmigrations   → aucune ligne "[ ]" (aucune migration en attente)
PRAGMA integrity_check             → ok
```

### 6. Frontend — vérification manuelle

**Non exécutée dans cette session.** Au moment de la vérification, plusieurs processus
`python`/`node` étaient actifs sur la machine sans que je puisse confirmer avec certitude qu'aucun
n'opérait en parallèle sur `backend/db.sqlite3` dans le cadre d'une autre session. Par prudence
(risque de perturber un autre agent ou de corrompre la base réelle partagée), je n'ai pas démarré de
serveur local pour ce test manuel. À la place, j'ai fait une revue de code complète de
`Treasury.tsx` (voir §1 ci-dessus), cohérente avec le rapport dev-frontend et avec le contrat
backend vérifié indépendamment. `npx tsc --noEmit` et `npm run build` avaient déjà été confirmés par
dev-frontend dans sa session.

Recommandation (non bloquante) : un passage manuel ou E2E (activation du réglage, génération d'un
rapport rétroactif, clôture rétroactive, vérification de l'absence d'erreur console) reste utile
avant mise en production, mais ne bloque pas le passage à `VÉRIFIÉ` compte tenu de la cohérence du
code relu et de la couverture de test backend déjà très complète.

## Fichiers

- `backend/treasury/tests/test_bug086_independent_verification.py` (nouveau — 8 tests)
- `docs/qa/REGISTRE_BUGS.md` (ligne récapitulative BUG-086 passée à `VÉRIFIÉ` ; 3 sections
  « Vérification » complétées : volet Clôture, volet Rapports Journaliers des Facturiers,
  vérification d'ensemble tous volets)

## Risques résiduels (non bloquants pour ce ticket)

- BUG-068/084 : date codée en dur dans 2 tests trésorerie, toujours ouverts, sans rapport avec
  BUG-086.
- BUG-085 : `is_correction` non couvert par le hash du livre de caisse, toujours ouvert, sans
  rapport avec BUG-086.
- BUG-057 : dérive `makemigrations --check --dry-run` préexistante, inchangée, sans rapport avec
  BUG-086.
- Vérification manuelle de l'écran Trésorerie non exécutée dans cette session (voir §6) — à faire
  dans une session où l'état des processus locaux peut être confirmé sans ambiguïté.
