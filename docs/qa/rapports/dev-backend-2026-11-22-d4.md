# Rapport dev-backend (Dev B) - 2026-11-22 (d4)

## Tickets traités
| Ticket | Statut | Correction |
|---|---|---|
| BUG-701 | CORRIGÉ | `core/models.py::ColisDistribution.compute_total` : `Decimal(str(...))` (défauts texte '0.00' non concaténés). Pas de migration. |
| BUG-702 | CORRIGÉ | `core/throttling.py` : username non-chaîne -> `ValidationError` 400 `{"detail": ...}`. |
| BUG-703 | CORRIGÉ | `commissions/serializers.py` : `manuel_adjustment` et `manuel_notes` en lecture seule ; seul `set_manuel` (ADMIN/DIRECTION, journalisé) les écrit. |
| BUG-704 | CORRIGÉ | `core/middleware.py::AdminLoginThrottleMiddleware` (ajouté dans `MIDDLEWARE`) : 429 après 10 échecs par compte / 30 par IP sur `/admin/login/`, fenêtre 900 s (`DJANGO_ADMIN_LOGIN_MAX_ATTEMPTS`, `DJANGO_ADMIN_LOGIN_WINDOW`). Connexion réussie = remise à zéro du compte. |
| BUG-705 | REJETÉ | Décision : pages siège uniquement. Décorateurs `history` / `payroll_listing` alignés sur `IsHeadquarters` (comportement inchangé). |
| BUG-706 | CORRIGÉ | Nouvelle `core/permissions.py::IsGerantWriteNoAccountant` sur `ConsumableMovementViewSet` : COMPTABLE en lecture seule (403 français). ADMIN, DIRECTION, GERANT conservés. |
| BUG-707 | CORRIGÉ | `ConsumableMovementViewSet.perform_destroy` appelle `log_activity`. |

## Tests
- Marques `@expectedFailure` retirées sur les 6 tests validant exactement ces corrections.
- Matrice `MatrixExpected` : lignes `movements` post/patch/delete passent de GERANT_UP à GERANT_UP sans COMPTABLE (conséquence directe de BUG-706).
- `core.tests.test_verif_permissions_b2_v2` + `production.tests.test_consumables` + `core.tests.test_verif_matrice_c` : 108 tests, OK (expected failures=1, hors périmètre).
- `commissions` : 157 tests, OK (expected failures=7, autres tickets).
- Relance isolée de `test_verif_permissions_b2_v2` : 57 tests OK.
- `makemigrations --check --dry-run` : aucun changement. `manage.py check` : aucune erreur.

## Risques
- Le throttle admin repose sur le cache Django (locmem par processus) : avec plusieurs workers, le plafond effectif est multiplié.
- Derrière un proxy, `REMOTE_ADDR` est l'IP du proxy : le plafond par IP (30) est partagé ; le plafond par compte reste la vraie protection.
- Le front n'utilisait pas `manuel_adjustment` via PATCH direct (grep backend) ; non vérifié côté `frontend/`.
