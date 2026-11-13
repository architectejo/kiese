# Vérification BUG-273 et BUG-275 (testeur-ventes, 2026-11-13)

Base de test Django isolée ; `backend/db.sqlite3` non touchée ; `manage.py test` limité aux modules `sales.tests.*` cités ci-dessous.

Exécution : `test_verif_bug273_275_2026_11_13`, `test_vague4_calendaire_ventes_2026_11_12`, `test_bug161_b3_invoice_dates` : 36 tests, OK.

Nouveau test : `backend/sales/tests/test_verif_bug273_275_2026_11_13.py`. Scénario : vente de 1 000 FC créée à 23:55 le 11/11 (400 cash) et livrée à 00:10 le 12/11, vente cash 2 000, NS, RG, remboursement de 300.
- Au jour de facturation (11/11) : `daily_summary` count 0.
- Au 12/11 : cash 2 700, crédit 800, count 4 (NS exclue). Rapports facturier : cash 2 700. Clôture : `total_entries` 2 700.

Résultats :
- BUG-273 : VÉRIFIÉ (un rapport par facturier, clôture unique, somme cohérente).
- BUG-275 : VÉRIFIÉ (jour de livraison, décote VENTE SOLDE hors CREDIT).

Note : les rapports du scénario sont tous deux libellés équipe « A » (deux lignes, deux facturiers) ; comportement attendu, sans impact sur les totaux.
