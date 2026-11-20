# Rapport dev-backend — 2026-11-20

## Tickets traités (CORRIGÉ, en attente de vérification par testeur-permissions)
- BUG-313 (bloquant) : `node` forgeable en PUT/PATCH.
  - Cause : serializers avec `node` modifiable, `perform_update` sans neutralisation.
  - Correctif : `backend/core/mixins.py::NodeImmutableForNonHQMixin` (node en lecture seule en update pour tout utilisateur sans `can_access_all_nodes`, ignoré silencieusement). Appliqué à : clients (SocialContribution, SocialDistribution), commissions (CommissionPeriod, ClientCommission), production (ProductionSession, ConsumableStock, ConsumableMovement, ConsumableCount, BreadDisposal), treasury (LocalExpense, FacturierReport, CashClosure, DisbursementVoucher, JournalEntry, DailySavings), core (ColisDistribution). Année d'une distribution clôturée figée (400 {"detail"}).
  - Audit : ClientViewSet (BUG-025) et ProductionSession (BUG-056) avaient déjà leur garde ; BreadTransfer/Sales/Invoice non concernés (pas de champ `node` modifiable ou liste blanche).
- BUG-314 (mineur) : `NodeSerializer.validate_monthly_social_contribution` (+ `validate_sac_value_fc`) refusent les négatifs. NaN/inf/1e99/texte étaient déjà refusés par DRF (max_digits). Pas de migration.

## Tests
- 3 `@expectedFailure` retirés (aucun test supprimé) ; nouveaux : `backend/core/tests/test_bug313_314.py` (PUT node, PATCH contribution, année distribution clôturée, siège inchangé, sac négatif, zéro accepté).
- Apps touchées : 46 tests OK sur base isolée (DB_NAME).
- `makemigrations --check --dry-run` : No changes detected.
- Suite complète (base isolée DB_NAME) : `Ran 1499 tests in 9231.886s — FAILED (failures=1, skipped=2, expected failures=1)`. Seul échec : `production.tests.test_verif_bug303_304_306_testeur_production.V306IncrementTests.test_rotation_targets_service_team_only` (403 TEAM_NOT_ASSIGNED). Il échoue aussi à l'identique SANS mes modifications (vérifié par git stash des vues) : sans lien avec BUG-313/314, probablement dépendant de l'heure/du jour d'exécution. À ouvrir en ticket par le coordinateur/testeur-production.

## Décisions / risques
- Politique choisie : « non-siège » = `not can_access_all_nodes` (le siège peut toujours déplacer une ligne, cohérent avec BUG-025/056). Si le coordinateur veut figer aussi pour DIRECTION, à trancher.
- Format d'erreur BUG-314 : clé de champ DRF (`{"monthly_social_contribution": [...]}`), pas `{"detail"}`, comme les autres validations de champ.
- Hors périmètre, à ouvrir si souhaité : `SocialDistributionSerializer.is_closed` est modifiable par un gérant (réouverture d'une distribution clôturée).
- Aucun impact frontend.
