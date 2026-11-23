# dev-backend d17 (2026-11-23)
- BUG-872 : `SocialDistributionViewSet.destroy` refuse (400, français) une distribution clôturée (clients/views.py).
- BUG-873 : `me_view` utilise `get_json_object` ; `new_password`/`old_password` non texte -> 400 (core/views.py).
- BUG-874 : sync/services.py : CONFIRMED sur transfert existant, création avec CONFIRMED ou quantity_received, création de ligne avec quantity_received, réservés à la réceptrice ; sinon rejet de l'enregistrement (« seule la boulangerie réceptrice ... »).
- Tests : marques @expectedFailure retirées (assertions inchangées) dans test_clients_v5.py et test_verif_sync_v5.py. Le testeur confirmera. Résultat : voir $TEMP/d17.log.
- Risque : aucun changement de contrat d'API hors 400 au lieu de 500/204. Rien commité.
