# dev-backend (dev-b) - B-5 vérification croisée, 2026-11-24

| Ticket | Verdict | Preuve |
|---|---|---|
| BUG-1060 (stats intrants, sel) | VÉRIFIÉ (croisée dev-b) | `production/tests/test_verif_croisee_b_intrants.py` (6 tests indépendants, valeurs fictives) + `test_intrants_stats_a` (22) verts |
| BUG-1050 (livreur = facturier) | Déjà VÉRIFIÉ testeur ; reconfirmé | `sales/tests/test_livreur_comme_facturier_a` + `test_bug161_b2_team_assignment` verts (57 tests au total, 0 échec) |
| BUG-1061 (onglet Statistiques, frontend) | Non verdict | contrat backend confirmé ; contrôle visuel Chrome non fait (hors de ce lot) : reste CORRIGÉ |
| A-1..A-4 | Non vérifiables | aucun ticket CORRIGÉ de dev-a au 2026-11-24 dans le registre |

Points contrôlés pour BUG-1060 : initial/entrée/sortie/total/consommation/solde, indice null à 0 sac, écart = déclaré − comptable et null si non déclaré, jour passé (mouvements du jour ignorés), TOTAUX = boulangeries + D1 (écart sur lignes déclarées), D1 visible ADMIN/DIRECTION/COMPTABLE seulement, gérant borné (autre boulangerie ou SIEGE : 404), facturier/livreur 403, anonyme 401, paramètres invalides 400, sel : 20 000 g = 1,000 sac = 204,0 boîtes, 1 000 g = 0,050 sac = 10,2 boîtes, boîte = 98,0392 g, non configuré = null, pas d'équivalents hors sel.

Aucun défaut trouvé, aucun BUG-1119+ ouvert. Aucun code de dev-a modifié ; seul ajout : le fichier de test. Risques : hypothèses client Q-044 à Q-050 toujours ouvertes (huile, signe de l'écart, colonne « ok ») ; BUG-1050 : le livreur peut créer factures/remboursements (point signalé par dev-a, à confirmer avec le client).
Note d'écriture de test : `ConsumableMovement.create` ajuste lui-même le stock (fixer le stock initial avant les mouvements).
