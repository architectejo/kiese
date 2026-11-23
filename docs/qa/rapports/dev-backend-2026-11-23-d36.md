# dev-backend d36 (2026-11-23)

BUG-971 CORRIGÉ : `sync/services.py::_push_cash_closure` crée toujours la clôture non confirmée (is_validated=False) ; seule la voie REST IsHeadquarters confirme. Rejeu idempotent. Versement par rejeu d'une clôture confirmée via REST conservé.

Tests : c13_v12 (décorateur retiré), 7 tests adaptés (voir registre BUG-971). Suite ciblée (299 tests) : voir risques.

Risques : 3 échecs hors périmètre dans les suites lancées, non liés aux clôtures (non confirmés comme préexistants, pas de stash) : sync.test_hostile_payloads_v2 `test_meme_uuid_plusieurs_fois...` ('Autre' != 'Fictif'), c10_v9 `test_bordereau_zero_et_negatifs_refuses` (bills_1000 '2.0' accepté), sync.test_verif_charge_v3 `test_course_generate_deux_boulangeries_double_retenue`.
