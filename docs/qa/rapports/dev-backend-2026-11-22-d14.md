# Rapport dev-backend d14 (2026-11-22) : ventes BUG-664 a 673

Perimetre : `backend/sales/` uniquement. Tickets passes a CORRIGE (a verifier par testeur-ventes). `@expectedFailure` retires dans `test_verif_ventes_a5_v5.py` (assertions inchangees), sauf BUG-671.

| Ticket | Cause | Correction |
|---|---|---|
| 664 | `bread_summary` sommait la magnitude des lignes d'ajustement | quantites et montants multiplies par `adjustment_sign` (Case/When) |
| 665 | `cancel` ne recalculait pas la categorie client | `refresh_category()` apres retablissement de la BP |
| 666 | `adjust` sur facture EN ATTENTE modifiait le compteur de pains | compteur modifie par `adjust` seulement si la facture est LIVREE ; `Invoice.deliver` ajoute le net (lignes + ajustements signes) |
| 667 | `deliver` : lecture-modification-ecriture du compteur | mise a jour `F()` + `Greatest(...,0)`, client reverrouille ensuite pour la categorie (`sales/models.py`) |
| 668 | `delivered_at` anterieur a `invoice_date` accepte | 400 en francais |
| 669 | vente sans client : versement non plafonne | versement plafonne a la valeur de la commande (comme la livraison partielle) |
| 670 | `daily_summary` ignorait le versement conserve d'une facture Non servi | inclut les NOT_SERVED avec versement > 0 a la date `not_served_at` (CASH = versement, CREDIT negatif) ; `count` ne compte que les livrees |
| 671 | A CLARIFIER | non code |
| 672 | PATCH `commission_exempt` sans avertissement | `_warn_if_commission_period_locked` apres modification (facture livree avec client) |
| 673 | `special_code` stocke sur un remboursement BP | code ignore (vide) |

Fichiers : `backend/sales/views.py`, `backend/sales/models.py`, `backend/sales/tests/test_verif_ventes_a5_v5.py`, `docs/qa/REGISTRE_BUGS.md`.

Impact API : `daily_summary` peut maintenant contenir une ligne pour un noeud n'ayant que des Non servi avec versement ; `bread_summary` peut renvoyer des totaux nets plus petits ; vente sans client : `payment_amount` renvoye plafonne. Pas de changement de schema. Aucun ticket frontend necessaire.

Risques : le compteur `total_breads_received` d'une facture en attente deja ajustee avant ce correctif reste celui de l'ancien comportement (donnees de demonstration seulement).
