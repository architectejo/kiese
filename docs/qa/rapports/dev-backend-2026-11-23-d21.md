# dev-backend d21 (2026-11-23)

Tickets CORRIGÉ : BUG-886, 887, 888, 889. Tests : core.tests.test_verif_permissions_b5_v5 + sync v5 + charge v4 = 76 OK ; makemigrations --check propre. Marques @expectedFailure retirées des 7 tests (assertions inchangées) ; le testeur les validera.

- BUG-886 : core/views.py::reset_data_view et chat/views.py::DirectConversationView utilisent get_json_object ; champs confirm_phrase/password non textuels -> 400 français.
- BUG-887 : sync/services.py::_push_social_distribution_line refuse création et modification si la distribution est clôturée.
- BUG-888 : sync/services.py::_push_bread_transfer, machine d'états par rôle. Émettrice : PENDING->RESPONDED/CANCELLED. Réceptrice : RESPONDED->CONFIRMED/DISPUTED. Autre combinaison refusée. Choix strict : PENDING->CANCELLED réservé à l'émettrice (c'est elle qui rejette dans respond_to_request) ; une annulation par la demandeuse n'existe pas dans le code.
- BUG-889 : commissions/views.py::ClientCommissionViewSet.perform_create -> 400 si période clôturée.

Pas de changement de contrat hors nouveaux 400. Risque : un push de lignes de distribution dans le même lot que la clôture, après elle, serait refusé.
