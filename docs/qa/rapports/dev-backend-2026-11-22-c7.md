# dev-backend, 2026-11-22 (c7) : BUG-820, 822 (DOC 1), 823

Fichiers : `backend/finance/views.py`, `backend/finance/tests/test_bug820_823.py` (nouveau). `manage.py test finance` : OK (106 tests ; 3 succès inattendus = marques à retirer), `check` et `makemigrations --check` propres. Frontend non touché.

- BUG-820 CORRIGÉ : créances d'un exercice clos = somme des `debt_delta` des factures valides datées <= 31/12 (indépendant de l'ordre de saisie et des annulations). Limite : dette sans facture absente d'un exercice clos.
- BUG-822 : partie DOC 1 CORRIGÉE (quantités signées). Partie `ClientCommission.total_breads` à B.
- BUG-823 : `qty_other` (JSON) + « QTÉ AUTRES » (CSV). Le test attaquant additionne 4 colonnes : il reste en échec, à adapter par le testeur. Ticket frontend à ouvrir (afficher `qty_other` dans Finance.tsx / `Doc1Row`).

Marques à retirer : `test_backdated_invoice_created_later_is_in_year_end_receivables_BUG_820`, `test_cancelled_pending_invoice_leaves_stale_debt_after_BUG_820`, `test_doc1_quantities_subtract_a_negative_adjustment_BUG_822`.
Non traités (A/B) : BUG-821, BUG-824, `total_breads` de BUG-822.
Risque : le dernier DOC 1 trie encore par `invoice_date` pour `debt_after` de fin de mois (hors périmètre).
