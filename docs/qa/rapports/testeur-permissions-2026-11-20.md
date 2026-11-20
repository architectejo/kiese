# Rapport testeur-permissions — 2026-11-20 (vérification BUG-313 / BUG-314)

Base isolée : `DB_NAME` dans le répertoire temporaire (jamais `backend/db.sqlite3`). Données fictives.

## Verdicts
- BUG-313 (bloquant) : **VÉRIFIÉ**.
- BUG-314 (mineur) : **VÉRIFIÉ**.
- Nouveau BUG-316 (majeur) : un gérant peut fixer le `tarif` d'une distribution sociale (« fixé par la direction », adaptes.md [4.2]) puis la clôturer (irréversible). OUVERT.

## Tests ajoutés
`backend/core/tests/test_verif_bug313_314_testeur_permissions.py` (13 tests, 2 `@expectedFailure` BUG-316) :
- Fabrique générique d'objets K1/K2 pour les 16 viewsets du mixin : SocialContribution, SocialDistribution, CommissionPeriod, ClientCommission, ProductionSession, ConsumableStock/Movement/Count, BreadDisposal, LocalExpense, FacturierReport, CashClosure, DisbursementVoucher, JournalEntry, DailySavings, ColisDistribution.
- Gérant K1 : PATCH et PUT (représentation GET avec `node=K2`) -> `node` inchangé, aucun 5xx ; GET d'un objet K2 = 403/404 ; PATCH/DELETE d'un objet K2 refusés et sans effet.
- DisbursementVoucher : réservé au siège, le gérant reçoit 403 en lecture (pas de vecteur).
- Siège (DIRECTION) : PATCH `node` sans 5xx, déplacement toujours permis (comportement inchangé).
- POST avec `node` K2 forgé (distributions, cotisations) : rien n'est créé en K2.
- Distribution clôturée : réouverture refusée en PATCH et PUT (BUG-260), tarif et année figés.
- BUG-314 : `-1`, `-0.01`, `abc`, `NaN`, `Infinity`, `1e99`, 30 chiffres -> 400 sur `monthly_social_contribution` et `sac_value_fc` (PATCH), négatif refusé aussi en POST ; valeurs valides (2500, 200000) et 0 acceptées ; gérant refusé (403/405) sur `nodes`.

## Rejeu des scénarios d'origine
Les 3 tests ex-`@expectedFailure` (`test_permissions_regression_2026_11_19`) passent désormais ; `test_bug313_314` OK.

## Suites lancées (base isolée)
- core permissions (`test_verif_bug313_314_testeur_permissions`, `test_bug313_314`, `test_permissions`, `test_permissions_regression_2026_11_19`, `test_permissions_verif_2026_10_22`, `test_vague2_corrections_permissions`, `test_vague2_db_permissions`, `test_vague3_db_permissions`) : **148 tests OK (1 skipped)**, 1374 s (avant ajout des 3 tests BUG-316, relancés ensuite : 13/13 OK, 2 échecs attendus).
- Suites complètes (base isolée) : `production` 461 tests OK (1 ignoré, 4015 s) ; `clients commissions treasury` 400 tests OK (1 échec attendu préexistant, 4375 s). Le test `V306IncrementTests.test_rotation_targets_service_team_only` signalé par dev-backend passe, ce qui confirme sa dépendance à l'heure d'exécution. Les tests de vérification des viewsets de ces apps (fabrique générique) sont aussi verts.

## Constat BUG-316 (détail)
`SocialDistributionSerializer.is_closed` : la réouverture est bien bloquée (BUG-260), donc le point soulevé par dev-backend est sans risque. En revanche, la **clôture** et le **tarif** sont modifiables par un gérant (`IsGerant`) : un gérant peut imposer un tarif arbitraire puis verrouiller la distribution de façon irréversible, sans correction possible par la direction. Gravité majeure (contournement d'un droit réservé à la direction, impact financier sur les remises). À confirmer avec le client si le gérant doit pouvoir clôturer.

## Observations
- Sur 16 viewsets, la neutralisation de `node` est silencieuse (200 avec valeur ignorée), cohérent avec BUG-025/056 ; un 403/400 explicite serait plus lisible mais n'est pas requis.
- Test hors périmètre signalé par dev-backend : `production...V306IncrementTests.test_rotation_targets_service_team_only` (403 TEAM_NOT_ASSIGNED, dépendant de l'heure) : à rouvrir côté testeur-production.
