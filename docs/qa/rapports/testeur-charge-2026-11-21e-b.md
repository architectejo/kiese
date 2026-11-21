# Rapport testeur-charge (dev B) — 2026-11-21e

Vérification adversariale de BUG-331, BUG-332, BUG-333, BUG-401 (code non commité, aucun code applicatif modifié).

## Verdicts
| Ticket | Verdict |
|---|---|
| BUG-331 | VÉRIFIÉ |
| BUG-332 | VÉRIFIÉ |
| BUG-333 | VÉRIFIÉ |
| BUG-401 | VÉRIFIÉ |

## Nouveaux tests (19, tous verts)
- `backend/sync/tests/test_verif_bug331_332_testeur_charge.py` (9) : 21 valeurs invalides (-1, "-1", 2.5, "2.5", "3.0", " 3.5 ", True, False, NaN, inf, -inf, 1e30, 10**30, 1000001, "1000001", liste, dict, tuple, "", "abc", "1e3") x `quantity`/`ordered_quantity`, sur ligne existante PENDING et DELIVERED, et à la création : toujours REJECTED, aucune exception, aucun changement de ligne, de dette client (BP), de total facture ni de BreadStock. Valeurs valides (0, 1, "3", 3.0, 1 000 000) acceptées ; None ignoré ; rejeu idempotent ; line_total correct à la borne.
  Remarque : "3.0" est rejeté (chaîne non entière), 3.0 float entier est accepté : comportement documenté du correctif.
- `backend/core/tests/test_verif_bug333_401_testeur_charge.py` (10) : page_size 1, 2, 500, 501, 10000 (plafond 500) ; 0, -1, "abc", "", "1.5", "1e2", " ", entier géant -> 200 avec taille par défaut (25) ou plafonnée, jamais 500 ; page hors limite -> 404 ; 130 objets parcourus avec page_size 7/10/25/50 sans doublon ni trou et même ordre que page_size=500 ; treasury/expenses (60 lignes de même date) et sales/invoices (55) parcourus sur plusieurs pages ; 17 listes treasury/production/sales/core sans 500 avec 5 variantes de page_size ; BUG-401 : le test BUG-255 est exécuté en sous-processus avec DJANGO_DEBUG=True puis False, code retour 0 dans les deux cas.

## Suite demandée
`manage.py test sync core commissions treasury` (sans --parallel, DJANGO_DEBUG=False) : Ran 784, FAILED (failures=1, errors=1, skipped=1, unexpected successes=1). L'ERROR était une erreur de mon propre test (id UUID passé à une ligne à clé entière), test supprimé ; les 2 fichiers nouveaux repassent seuls : 19 tests OK.

## Anomalies signalées (non modifiées)
1. Unexpected success attendu : `treasury.tests.test_verif_bug179_176_testeur_tresorerie.Bug176Tests.test_bug331_page_size_param_is_honored` : `@expectedFailure` à retirer par A.
2. FAIL lié : `Bug176Tests.test_expenses_identical_date_and_timestamp_pages_no_dup_no_gap` : `assertEqual(pages, 3)` obtient 30, car son `_walk` utilise `page_size=2` désormais honoré (le test supposait le paramètre ignoré). Conséquence normale du correctif BUG-333, pas un défaut applicatif ; à adapter par A (parcours de 30 pages sans doublon ni trou, ou page_size=25 explicite).
3. Hors périmètre : un `id` non entier dans un enregistrement `InvoiceLine` fait lever ValueError dans `_push_invoice_line` (filtre pk entier) ; `process_push_batch` l'attrape en général (garde défensive), non testé de bout en bout ici. À surveiller, pas de ticket.

Aucun ticket rouvert ni ouvert. Durée de la suite : environ 21 minutes (treasury domine).
