# Rapport dev-backend, 2026-11-22 (lot c5) : BUG-800 à 803, 806, 807

## Tickets passés à CORRIGÉ
- BUG-800 : bilan arrêté au 31/12 de l'exercice (caisse = dernier solde du livre daté <= 31/12 ; créances d'un exercice clos = dernier `debt_after` non annulé par client actif ; exercice en cours = `current_debt` actuel ; exercice vide = 0).
- BUG-801 : CA signé selon `adjustment_sign` (ajustement négatif soustrait).
- BUG-802 : lignes des factures RG (et ajustements d'une RG) exclues du CA.
- BUG-803 : migration `production/0029_bug803_movement_unit_price_4dp` (`ConsumableMovement.unit_price` en `max_digits=16, decimal_places=4`, AlterField sans perte, réversible). Impact API : `unit_price` des mouvements sérialisé à 4 décimales.
- BUG-806 : coûts matière arrondis (`quantize(0.01, ROUND_HALF_UP)`), marge brute et résultat calculés sur les lignes arrondies.
- BUG-807 : `_money_json` rend les `Decimal` en chaînes à 2 décimales (income_statement, cashflow, balance_sheet, comparative). Frontend déjà typé `string` et lu via `parseFloat` (`Finance.tsx`) : aucun changement frontend, donc ni `tsc` ni `build` requis.

Fichiers : `backend/finance/views.py`, `backend/production/models.py`, `backend/production/migrations/0029_bug803_movement_unit_price_4dp.py`, `backend/finance/tests/test_bug800_807.py` (9 tests, verts), `docs/qa/REGISTRE_BUGS.md` (lignes et fiches).

## Résultats
- `manage.py test finance treasury blockchain --noinput` : 480 tests, 3 échecs (voir ci-dessous), 7 succès inattendus, 15 échecs attendus.
- `check` OK ; `makemigrations --check --dry-run` : aucun changement.

## Marques `@expectedFailure` à retirer (test_audit_c_cycle1_c.py), par le testeur
test_13_BUG_800_*, test_14_BUG_800_*, test_18a_BUG_807_*, test_18b_BUG_806_*, test_negative_adjustment_reduces_revenue_BUG_801, test_regularisation_is_not_revenue_BUG_802, test_exit_unit_price_column_keeps_the_cump_precision_BUG_803 (les 7 « unexpected successes »).

## Conflit à trancher par le testeur / coordinateur
`test_03_cogs_...` et `test_04_expenses_and_net_result_chain` (non modifiés) attendent des montants NON arrondis (cost_flour 21006.8965 ; net_result 793.1035), ce qui contredit BUG-806 (`test_18b` exige 2 décimales). Ils échouent désormais ; valeurs à adopter : cost_flour 21006.90, gross_profit 8043.10, net_result 793.10.

## Risques
- Bilan d'un exercice clos reconstitué à partir des factures : les mouvements de BP hors facture (import, régularisation directe de `current_debt`) ne sont pas vus ; BUG-804 (À CLARIFIER) reste entier.
- Le test `ReceivablesRulesTests` / test_12 suppose que l'exercice du scénario est l'année en cours (en janvier, la bascule en « exercice clos » changerait le chemin de calcul).
- DOC 1 (`invoice_total`) a probablement le même défaut de signe que BUG-801 : à ouvrir en ticket séparé.
- `treasury/views.py` et `treasury/tests/test_bug810_819.py` modifiés par un autre agent : non touchés.
