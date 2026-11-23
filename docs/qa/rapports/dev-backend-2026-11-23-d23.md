# dev-backend (Dev B) d23 - 2026-11-23

Tickets CORRIGÉ : BUG-891 à BUG-896. Tests : `core.tests.test_verif_permissions_b6_v6` (marques `@expectedFailure` retirées, assertions inchangées), `test_verif_permissions_b5_v5`, `sync.tests.test_verif_sync_v5` : 96 OK. `makemigrations --check` : aucun changement. Log : `$TEMP/d23.log`.

- BUG-891 : `sync/services.py::_push_bread_transfer` refuse à la création tout statut autre que PENDING.
- BUG-894 : helper `_sync_bounded_qty` (entier ASCII 0..2e9) sur `quantity_received` (mise à jour et création).
- BUG-892 : `treasury/views.py::generate` appelle `get_json_object` (400).
- BUG-893 : `commissions/views.py::CommissionPeriodViewSet.update` (PUT/PATCH) refuse un changement de month/year/node si période clôturée ou portant des commissions (400 français).
- BUG-895 : `core.mixins.AsciiDigitsMixin` (validateur partagé) appliqué à Node, Config, BreadPrice et `ClientBoundsMixin` (credit_limit, commission_rate, cotisation_sociale).
- BUG-896 : `production/views.py` opening-confirmation : `qty` chaîne doit être `-?[0-9]+(.0+)?` (refus non-ASCII et notation exponentielle).

Impact API : uniquement des 400 supplémentaires ; aucun changement de format. Risque : un client hors ligne qui poussait un transfert créé directement à un autre statut que PENDING sera désormais refusé (conforme à BUG-888).
