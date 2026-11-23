# dev-backend d24 (2026-11-23)

Tickets CORRIGÉ : BUG-897, BUG-898, BUG-899.

- BUG-897 : `core/mixins.py::AsciiDigitsMixin` accepte `ascii_digit_fields = '__numeric__'` (tous les champs numériques inscriptibles). Appliqué à `treasury/serializers.py` (dépense, rapport facturier, clôture, journal, épargne, bordereau, comptage direction), `commissions/serializers.py` (order_value + 4 retenues), `core/serializers.py` (Node : monthly_social_contribution, card_fee_fc), `sales/serializers.py` (payment_amount création et ajustement seulement). `commissions/views.py::set_manuel` refuse aussi les chiffres non ASCII.
- BUG-898 / BUG-899 : `sync/services.py::_push_local_expense` : montant ASCII fini > 0 obligatoire ; catégorie scope=DIRECTION refusée hors SIEGE ; catégorie désactivée toujours acceptée.
- Tests : marques `@expectedFailure` retirées dans `core/tests/test_verif_permissions_b7_v7.py` (5 tests passent). Lot demandé (100 tests) : seuls les 5 "unexpected successes" avant retrait, aucun échec ; `makemigrations --check` : aucun changement. Suite complète non lancée.
- Impact API : aucun changement de contrat hors 400 sur chiffres non ASCII. Docstrings de `InvoiceCreateSerializer`/`InvoiceAdjustSerializer` déplacées par l'insertion de l'attribut (cosmétique).
- Risque : push avec montant non ASCII/≤0 renvoie désormais un échec par enregistrement (message français).
