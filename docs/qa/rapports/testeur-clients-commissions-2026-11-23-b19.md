# Testeur clients/commissions, cycle 19 partie B (2026-11-23)

- VERIFIES : BUG-1008, BUG-1009 (tests independants `clients/tests/test_clients_v15.py` 10 tests, `commissions/tests/test_commissions_v6.py` 10 tests ; 2 `@expectedFailure`).
- Curseur futur 1 h : forge (futur 30 min + after_id) = 0 ligne, equivalent a `since=maintenant`, aucune fuite de perimetre ; 59 min accepte, 61 min / 2 h traite comme absent (BUG-785 conserve). Marche avec lignes a +30 min : sans perte ni doublon.
- Inactif d'un autre noeud en page 2+ d'une marche initiale : poste neuf l'ignore (pas de creation) : OK.
- Commissions multi-boulangeries : suppression de la porteuse puis regeneration complete / de la seule boulangerie supprimee / ligne non porteuse / porteuse payee / BP creditrice / net exact par ligne : OK.
- Nouveaux tickets (2) :
  - BUG-1010 (Mineur) : lignes datees > 1 h dans le futur -> curseur de page rejete -> pagination sans fin (borne 200 pages). Proposition : ne pas appliquer la limite du futur aux curseurs de page, ou borner le curseur renvoye.
  - BUG-1011 (Mineur) : limite annoncee de BUG-1009 confirmee comme perte de retenue sans alerte (seules les lignes restantes regenerees restent a 0). Propositions : transfert a la suppression / report en regeneration / `warnings`.
- Ce cycle n'est donc pas un cycle propre de la partie B (2 nouveaux tickets).
- Note : les 20 tests passent (2 expectedFailure) ; pas de modification du code applicatif.
