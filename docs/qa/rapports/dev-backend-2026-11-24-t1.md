# dev-backend (Dev B) - 2026-11-24 - t1 : alignement des tests livreur = facturier (BUG-1118)

Ticket : BUG-1118 (CORRIGE). Aucun code applicatif modifie (tests uniquement).

## Verdicts
| Test | Verdict |
|---|---|
| core Matrix.test_matrix | test perime corrige (POST invoices : FACT_UP + LIVREUR) |
| core SalesIsolation.test_deliver_cancel_adjust_foreign_invoice | test perime corrige (cancel facture etrangere par livreur = 404 comme le facturier) |
| core SalesIsolation.test_livreur_cannot_create_negative_payment | reecrit : meme regle que le facturier (motif inconnu = 400 pour les deux ; autres cas meme statut pour les deux roles) |
| core Vague3 test_write_matrix (POST clients, BUG-250) | LIVREUR ajoute aux roles autorises |
| core b8_v8 MatriceLivreur.test_matrice_livreur_vs_facturier | KNOWN_FACT_ONLY vide, exige LIVREUR == FACTURIER sans ecart |
| clients test_api test_livreur_still_cannot_create_client | remplace par test_livreur_can_create_client_in_own_node_like_facturier |
| clients Bug250.test_livreur_cannot_create | 201 dans sa boulangerie, champs forges ignores, PATCH client reste 403 |
| core b8_v8 EcartsLivreurFacturier test_bug1023..1026 | @expectedFailure retire (assertions inchangees) |
| clients test_clients_v6 test_bug737_... | TEST PERIME, pas un defaut (voir ci-dessous) |

## test_bug737 : analyse
Depuis BUG-1104 la carte est retenue une seule fois par client et par mois, sur la ligne non payee la plus ancienne (commissions/views.py l.289-305). Dette (2500) et cotisation (2000) restent portees une seule fois par la meme ligne (BUG-1013/1014). Valeurs recalculees a la main : K1 = 5000 - 2500 - 2000 - 1000 = -500 ; K3 = 5000 - 0 - 0 - 0 = 5000 (l'ancien test attendait 4500 car il supposait une carte de 500 sur K3). Total des retenues des deux lignes = 5500 : rien perdu, rien double. Assertions ajoutees sur card_applied et sur le total.

## Resultats reels (log $TEMP/t1.log, passes core / clients / commissions)
- Modules touches isoles (permissions, vague3, b8_v8, clients test_api, bug249_250) : 108 OK + 1 echec corrige (negative payment, premier jet trop strict : le facturier accepte un paiement negatif sans motif), puis SalesIsolation 5 OK ; clients.tests.test_clients_v6 : 24 OK.
- core : 959 tests, OK (skipped=2, expected failures=1). Les 2 echecs Bug407RouteGuardsTests (/clients, /production) de la serie full3 ne se reproduisent plus.
- commissions : 302 tests, OK (expected failures=3).
- clients : 675 tests, FAILED (expected failures=2, unexpected successes=1) : test_clients_v2.CategorieTests.test_plafond_zero_avec_dette_zero_n_est_pas_a_risque est passe en succes inattendu pendant la passe car BUG-1116 (autre agent) a ete corrige en parallele ; le fichier test_clients_v2.py a depuis ete modifie par cet agent (marque deja retiree dans la copie de travail). Non touche par moi, a rejouer.
- Non lance : sync, chat, serie complete (consigne). makemigrations non requis (aucune modification de schema).

## Risques / reste
- Le facturier (et donc le livreur) peut creer un paiement negatif sans motif (201) : comportement preexistant, a trancher par le coordinateur si le motif doit etre obligatoire (non traite).
- Le livreur n'a pas plus que le facturier : verifie par la matrice (liv_only == []) et test_livreur_ferme_sur_clients_modification_suppression_bulk_import.
- Les modifications de test_clients_v2.py, clients/models.py, serializers.py ne sont pas de moi.
