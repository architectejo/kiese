# Rapport dev-backend — 2026-10-30 — BUG-087

## Ticket traité

**BUG-087** — Throttle de connexion (`ScopedRateThrottle`, `5/min`, BUG-006) comptabilisé
globalement par adresse IP, pour toute tentative (y compris les connexions réussies), sans
distinction par compte visé → plusieurs employés d'une même boulangerie connectés depuis la même
IP locale en début de vacation se bloquaient mutuellement (reproduit par testeur-e2e avec
`e2e/tests/02-connexion-roles.spec.ts`, 6 rôles séquentiels, le 6e échouant en `429`).

Décision du coordinateur : corriger immédiatement, pas de backlog.

Statut final du ticket : **CORRIGÉ** (dans `docs/qa/REGISTRE_BUGS.md`, fiche détaillée + tableau
récapitulatif). Comme toujours, dev-backend ne passe jamais un ticket à `VÉRIFIÉ` — c'est
testeur-e2e ou le coordinateur qui fera la vérification.

## Cause

`core/views.py::login_view` appliquait `ScopedRateThrottle` (DRF), qui hérite de
`SimpleRateThrottle`. Pour une requête non authentifiée (toujours le cas sur un endpoint `AllowAny`
de login, puisque l'identité n'est pas encore établie), `SimpleRateThrottle` utilise
`self.get_ident(request)` — c'est-à-dire **l'adresse IP du client** — comme unique clé de cache, et
décompte **toute** requête vers la vue (succès `200` et échec `401` confondus). Résultat : le quota
de 5 tentatives/minute était partagé par tous les comptes se connectant depuis la même IP, et non
par compte.

## Correction

Remplacement de `ScopedRateThrottle` par deux throttles dédiés (nouveau module
`backend/core/throttling.py`) :

- **`LoginAccountRateThrottle`** (scope `login`, `5/min` par défaut — inchangé) : clé de cache =
  `username` soumis dans le payload de login (normalisé en minuscules). Repli sur l'IP uniquement
  si le payload ne contient aucun `username` exploitable, pour que l'endpoint reste toujours
  protégé même en cas de requête malformée. C'est la vraie protection anti-brute-force : marteler
  un seul compte reste limité, quelle que soit l'IP source (protection même renforcée sur ce point,
  puisqu'elle ne dépend plus de l'adresse d'origine).
- **`LoginIPRateThrottle`** (nouveau scope `login_ip`, `30/min` par défaut, variable d'environnement
  `DJANGO_LOGIN_IP_THROTTLE_RATE`) : conservée en complément, avec un plafond plus large, comme
  garde-fou anti credential-stuffing / énumération de comptes distincts depuis une même source.

Les deux throttles sont appliquées ensemble sur `login_view`
(`@throttle_classes([LoginAccountRateThrottle, LoginIPRateThrottle])`). Le décompte des connexions
**réussies** est conservé par prudence (le ticket demandait de ne plus bloquer les comptes
*différents* entre eux, pas d'exempter les succès du quota d'un même compte) — affaiblir ce point
aurait réduit la protection anti brute-force sur un compte ciblé.

## Fichiers modifiés

- `backend/core/throttling.py` (nouveau) — `LoginAccountRateThrottle`, `LoginIPRateThrottle`.
- `backend/core/views.py` — `login_view` utilise les deux nouvelles classes ; suppression de la
  ligne `login_view.cls.throttle_scope = 'login'` (devenue inutile, `scope` est fixé en dur sur
  chaque classe de throttle désormais).
- `backend/kiese/settings.py` — ajout de `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login_ip']`
  (lu depuis `DJANGO_LOGIN_IP_THROTTLE_RATE`, défaut `30/min`) ; `'login'` inchangé.
- `backend/.env.example`, `backend/.env` — documentation et valeur par défaut de
  `DJANGO_LOGIN_IP_THROTTLE_RATE=30/min`.
- `backend/core/tests/test_permissions.py` — nouvelle classe `LoginThrottlePerAccountTests`
  (test qui échouait avant la correction, passe après) ; `LoginThrottleTests` existante sert de
  test de non-régression (martèlement du même compte reste `429` à la 6e tentative).

Aucune migration nécessaire (changement de classe de throttle DRF uniquement, aucun modèle touché).
Aucun changement de contrat d'API (mêmes codes HTTP, même format d'erreur `{"detail": "..."}` sur
`429`, comportement par défaut de DRF) — pas de ticket lié `dev-frontend` à ouvrir.

## Tests

- **Test ajouté** (échouait avant — 6e requête `429` au lieu de `200` — passe après) :
  `core.tests.test_permissions.LoginThrottlePerAccountTests.test_six_different_accounts_same_ip_all_succeed`
  — 6 connexions légitimes à 6 comptes différents (ADMIN, DIRECTION, COMPTABLE, GERANT K1, GERANT K2,
  FACTURIER K1) depuis la même IP (même `APIClient`) en moins d'une minute → les 6 renvoient `200`.
- **Test de non-régression** (déjà présent, toujours vert après correction) :
  `core.tests.test_permissions.LoginThrottleTests.test_sixth_bad_login_attempt_is_throttled` — 6
  tentatives erronées sur le même compte inexistant → 5× `401` puis `429`.
- `python manage.py test core` → **58 tests, OK**.
- `python manage.py test` (suite complète) → **320 tests, 3 échecs** :
  - `clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests...` :
    flakiness **connue (BUG-017)**, `database table is locked` — aucun rapport nécessaire, conforme
    à la mission.
  - `treasury.tests.test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario` et
    `treasury.tests.test_reports_closures.CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses` :
    **pré-existants et déjà documentés** dans le registre (BUG-068/BUG-084, date codée en dur
    `'2026-10-22'` vs horloge système réelle qui a avancé). Réexécutés isolément
    (`python manage.py test treasury.tests.test_cashbook_level3.FullDayIntegrationTests.test_full_day_scenario treasury.tests.test_reports_closures.CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses`)
    → même échec, confirmant l'absence de lien avec ce ticket (ni l'un ni l'autre test ne touche
    à l'authentification/au throttle).
  - Aucune régression imputable à BUG-087.
- `python manage.py makemigrations --check --dry-run` → dérive détectée sur `production`,
  `clients`, `treasury` (champs `id`, contraintes `unique_together`) — **dérive connue BUG-057**,
  sans rapport avec cette correction (aucun modèle concerné par le changement de throttle).
- `backend/db.sqlite3` : `PRAGMA integrity_check` → `ok`. Base réelle non touchée : tous les tests
  passent par la base de test éphémère de `manage.py test`.

## Risques / points d'attention pour la suite

- Aucun nouveau risque introduit. Le throttle `login_ip` (30/min) reste un filet de sécurité large ;
  si le client souhaite un seuil différent en production, ajuster uniquement
  `DJANGO_LOGIN_IP_THROTTLE_RATE` (variable d'environnement, pas de code à toucher).
- Rappel (hors périmètre de ce ticket, déjà noté ailleurs dans le registre) : BUG-068/BUG-084
  (dates codées en dur dans des tests trésorerie) redeviendront visibles à chaque test complet tant
  qu'ils ne sont pas corrigés — sans impact sur le comportement applicatif réel.
- BUG-017 (verrouillage SQLite sous concurrence dans les tests) reste flaky, conformément à ce qui
  était attendu dans la mission.
