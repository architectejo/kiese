# dev-backend d51 (2026-11-23)

- BUG-1008 CORRIGÉ : `sync/views.py::PullView`, `Q(is_active=False)` appliqué à toutes les pages d'un pull à curseur (plus de condition sur `client_after_id`), exclu du pull initial.
- BUG-1009 CORRIGÉ : `commissions/views.py::generate`, « déjà retenu » = une autre ligne du mois porte dette/cotisation non nulle ; filet anti-doublon limité aux lignes porteuses.
- Tests : `@expectedFailure` retirés (test_clients_v14, test_commissions_v5) ; assertions inchangées.
- Risques : page 2+ d'une marche initiale peut livrer un inactif inconnu (ignoré par le poste) ; régénération des seules lignes restantes ne reporte pas la retenue.
- Complément 1008 : `_parse_cursor(allow_future)` tolère 1 h de futur pour un curseur de page (sinon boucle infinie sur la page 1).
- Décorateur `@expectedFailure # BUG-783` retiré de `sync/tests/test_verif_charge_v3.py::test_suppression_de_la_ligne_retenante_puis_regeneration` (succès inattendu : même défaut que 1009).
- Tests : passe 1 (219 tests) puis relances ciblées v14+v13 (60 OK), v12/v3/v5 OK avant le dernier ajustement ; makemigrations : aucun changement.
