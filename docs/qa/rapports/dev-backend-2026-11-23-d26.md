# Rapport dev-backend (Dev B) - 2026-11-23 - d26

Tickets traites (passes a CORRIGE) : BUG-910, 911, 912, 913, 914 (push sync tresorerie).

## Corrections (backend/sync/services.py)
- Nouveaux controles dans `_STRICT_CHECKS` (helpers d25 reutilises) : `_check_facturier_report`, `_check_cash_closure`, `_check_disbursement_voucher`.
  - 910 : totaux rapport >= 0, ASCII, 2 decimales (`sacks_value_gap` peut etre negatif).
  - 911 : equipe A/B obligatoire (a la creation) ; `_push_facturier_report` rejette un 2e rapport de meme (boulangerie, equipe, date) : le champ `facturier` est NULL au push, donc l'unique_together du modele ne protege pas (REST applique le controle par code). Pas de migration.
  - 912 : dates futures refusees (rapport, cloture, bordereau).
  - 913 : `total_entries`/`total_expenses` >= 0 ASCII 2 decimales ; billets entiers ASCII >= 0 (cloture et bordereau).
  - 914 : bordereau de 0 FC refuse ; creation du bon + ecriture au livre dans une meme `transaction.atomic()`, rollback si solde insuffisant (aucun bon orphelin).
- Tests : marques `@expectedFailure` BUG-910..914 retirees (assertions inchangees) dans `treasury/tests/test_verif_tresorerie_c9_v8.py` (le testeur confirmera).

## Resultats
Lot demande (c9_v8, production a8_v8, sync v5, charge v4, test_sync, bug004_extension, hostile_payloads_v2, charge v3, finale_bug004, volume, 213 tests) : tout vert sauf `test_imbrication_a_trois_une_seule_retenue` (v4) et `test_course_generate_deux_boulangeries_double_retenue` (v3), tests de course (commissions) : passent en isolation, avec et sans ma modification, et au 2e lancement ; flaky, sans lien avec la tresorerie (a verifier par le testeur concerne). `makemigrations --check` : aucun changement. Log : $TEMP/d26.log.

## Risques / notes
- Un rapport deja pousse par un autre facturier de la meme equipe/jour est desormais rejete au push (REST autorise 2 facturiers distincts) ; coherent avec la regle « une vacation = une equipe ».
- Un bon orphelin herite d'avant ce correctif (sans ecriture au livre) serait encore debite au rejeu (comportement inchange) : a nettoyer a la main si present.
- Aucun contrat d'API modifie (rejets REJECTED supplementaires), pas de ticket frontend. Rien commite.
