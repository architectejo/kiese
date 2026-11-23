# Rapport dev-backend (Dev B d15) - 2026-11-23

Source : remarque.md, demande client 4 (fin du fichier). Backend seulement, `backend/sales/` non touche.

## Tickets traites (CORRIGE)
| Ticket | Point | Correctif |
|---|---|---|
| BUG-674 | Journal des Sorties Non Valorisees par jour | `disposals/?date=` ou `?date_from=&date_to=` (date invalide -> 400) |
| BUG-675 | Transferts : envoyes = vendus (emettrice), recus retranches (receptrice) | `facture_mvm_interne` : `+ appro_effectue - appro_recu` |
| BUG-676 | Repartition par categorie a 0 % | cause : base = `produit` vide sur journee par sacs non cloturee ; repli `vendu_jour` puis facture ; champ `totals.repartition_base` |
| BUG-677 | Categories de depenses direction vs boulangeries | `ExpenseCategory.scope` (BOTH/BAKERY/DIRECTION), migration `core/0023_expensecategory_scope` (additive) |

Tests : `backend/production/tests/test_dev_d15_demande4.py` (5 tests). Trois tests existants ont ete realignes (+ `test_verif_rotation_prod_c.py::Bug193Tests`) sur le nouveau signe de BUG-675 (`test_daily_closure_report.py`, `test_verif_bug177_rapport_testeur_production.py`) : changement de specification (remarque.md prioritaire), pas un affaiblissement.

## Points a surveiller
- BUG-675 contredit la formule de classeur Q-006 (K6!L21 additionnait appro recu) : a faire confirmer par le client / auditeur-comptable sur les Excel d'aout.
- BUG-676 : repli sur les ventes du jour = choix de conception, a valider.
- BUG-677 : non tranche : usage des categories "direction" dans le livre de caisse (imputation) ; seule la depense locale est controlee.

## Frontend a faire
1. Journal des Sorties Non Valorisees : selecteur de date -> `GET /api/production/disposals/?date=AAAA-MM-JJ`.
2. Cloture Journaliere : afficher `totals.repartition_base` ; afficher « Appro recu » en negatif si le libelle le suggere.
3. Configuration : champ « Portee » (`scope`) sur les categories de depenses ; formulaire de depense locale : lister uniquement ce que renvoie l'API.

## Tests lances
Suite ciblee (production : cloture/transferts/disposals/rotation, core complet, treasury.test_reports_closures, nouveaux tests) : 945 tests, 1 echec (realigne, BUG-675), 1 erreur = nom de module errone dans ma commande (sans rapport), 2 `unexpected success` preexistants (BUG-540/562, marques du testeur). `makemigrations --check` : aucun changement. Suite complete non lancee (duree). Verification "echoue avant" : par construction (champ `scope` absent, filtre date absent, signe inverse) ; non rejoue sur l'ancien code.
