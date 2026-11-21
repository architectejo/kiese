# Rapport dev-backend (dev B) — 2026-11-21e

Tickets traités (statut CORRIGÉ, à vérifier par les testeurs) : BUG-331, BUG-332, BUG-333, BUG-401.

- BUG-331/332 : `backend/sync/services.py` — nouvelle `_parse_line_quantity` (entier 0..1 000 000 ; refuse booléen, float non entier/NaN/inf, chaîne non entière, négatif, énorme), utilisée pour l'update de ligne existante et la création. Tests : `backend/sync/tests/test_bug331_332_invoice_line_quantity.py`.
- BUG-333 : `backend/kiese/pagination.py` (`page_size_query_param='page_size'`, `max_page_size=500`) ; clés invalides retirées de `settings.py`. Tests : `backend/core/tests/test_bug333_page_size.py` ; `_walk` de `commissions/tests/test_bug172_deterministic_ordering.py` renforcé.
- BUG-401 : test BUG-255 indépendant de `.env` (skip si SERVE_PERMISSIONS importé = AllowAny).

Tests : `manage.py test sync core commissions clients` : Ran 624, OK (skipped=1). Ciblés avec DJANGO_DEBUG=True : OK. `makemigrations --check` : aucun changement.

Actions pour A (hors périmètre B) : retirer les `@expectedFailure` BUG-331/332 dans `sales/tests/test_verif_bug323_324_testeur_ventes.py` et celui de `test_bug331_page_size_param_is_honored` dans `treasury/tests/test_verif_bug179_176_testeur_tresorerie.py`.

Risques : borne de quantité fixée à 1 000 000 (choix technique, line_total Decimal(14,2)) ; `page_size` peut désormais monter à 500 sur tous les endpoints paginés.
