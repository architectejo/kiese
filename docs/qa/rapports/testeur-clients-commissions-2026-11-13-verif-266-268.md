# Vérification BUG-266 / 267 / 268 (2026-11-13)
`manage.py test commissions` (base de test isolée, db.sqlite3 non touchée) : 66 tests OK.
Nouveaux tests : `backend/commissions/tests/test_verif_bug266_267_268_2026_11_13.py` (7 cas, valeurs à la main en Decimal).
- 266 VÉRIFIÉ : net négatif -> 400, non payé, même après régénération ; net = 0 payable ; net positif inchangé (9 275 FC pour CM 12 500, dette 100).
- 267 VÉRIFIÉ : épargne pure exclue ; client mixte garde la CM sur ses ventes, sans crédit BP.
- 268 VÉRIFIÉ : report 3 périodes exact ; dette > report -> excès seul.
Tests 263/264/265 réécrits : seul ajout `sans_cotisation()` (cotisation 0) pour obtenir un net positif, désormais nécessaire à mark_paid ; assertions de fond inchangées (non affaiblies). Test 268 d'origine à borne large (>= -16 000) : complété par les valeurs exactes.
