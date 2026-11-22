# Rapport dev-backend 2026-11-22 (D3, commissions)

Tickets traités : BUG-735 (CORRIGÉ), BUG-736 (CORRIGÉ). BUG-734 laissé OUVERT (note : pagination/plafond à définir avec le frontend).

- BUG-735 : `mark_paid` et `set_manuel` dans `transaction.atomic()` avec `select_for_update(of=('self',))` + écriture conditionnelle `is_paid=False` (SQLite ignore le verrou ; la condition protège aussi les tests).
- BUG-736 : `generate` valide node (`parse_node_param`), month 1..12, year 2000..2100, entiers stricts ; 400 `{"detail": ...}` en français.
- Fichiers : `backend/commissions/views.py`, `backend/commissions/tests/test_concurrence_volumetrie_v2.py` (3 @expectedFailure retirés), `backend/commissions/tests/test_bug735_736_v2_b.py` (nouveau).
- Résultats : tests ciblés 14 OK (1 expected failure = BUG-734). Suite `commissions` : 153 tests, 14 échecs, tous dans `test_commissions_v2.py` (fichier du testeur, hors périmètre : formats '700' vs '700.00', filtres booléens, NaN en set_manuel, etc.) ; non liés à ces correctifs. makemigrations --check : aucun changement ; manage.py check : OK.
- Risque : à recontrôler sous PostgreSQL (verrou de ligne réel).
