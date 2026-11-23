# Rapport dev-backend d27 (2026-11-23)

Tickets CORRIGÉ : BUG-915, 916, 917, 918 (+ régression BUG-911 affinée).

- 915 : `clients/serializers.py` (3 serializers en `AsciiDigitsMixin` `__numeric__`), `clients/views.py::bulk_create_month`, `commissions/views.py::generate` (refus non ASCII).
- 916/917/918 : `sync/services.py` : `_check_client`, `_check_social_contribution`, `_check_social_distribution`, `_check_social_distribution_line` (table `_STRICT_CHECKS`) ; handler ligne : `compute()` à la création et à la modification (remise/total_payer jamais pris tels que poussés).
- BUG-911 (régression d26) : `_push_facturier_report` rejette le doublon seulement pour le même facturier (champ `facturier` du record, stocké s'il existe ; indéterminé des deux côtés = doublon). Test : `treasury/tests/test_dev_d27_facturier_multi.py`.
- Tests : marques `@expectedFailure` BUG-915..918 retirées de `test_clients_v6.py` (assertions intactes ; l'import inutilisé reste). 66 tests OK (test_clients_v6, c9_v8, d27, sync v5), `makemigrations --check` propre. Suite complète non lancée.

Risques : `_check_client` rejette un nouveau client poussé sans nom/prénom (REST les exige) ; un push `Client` ancien sans noms serait refusé. Pas de changement de contrat API REST hormis 400 sur chiffres non ASCII. Rien commité.
