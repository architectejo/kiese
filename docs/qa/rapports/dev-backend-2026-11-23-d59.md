# dev-backend d59 (2026-11-23)

## BUG-1027 : CORRIGÉ
Cause : `ClientViewSet.perform_create` (clients/views.py) forçait `commission_rate` au défaut du champ (0,25) pour les rôles hors ADMIN/DIRECTION/COMPTABLE/GERANT. Correction : `core.models.effective_commission_rate(node)` (nœud du client). BUG-250 conservé : facturier/livreur ne choisissent ni plafond ni taux. Gérant/direction : taux fourni prioritaire (0 valide), sinon défaut de la boulangerie (déjà OK, non modifié). Import Excel et plafond 50 000 FC non touchés.
Tests : test_clients_v17 (facturier, livreur) sans @expectedFailure.

## BUG-1028 : CORRIGÉ
`card_applied` ajouté à `ClientCommissionSerializer.Meta.fields` et `read_only_fields` (commissions/serializers.py). Test test_commissions_v8 sans @expectedFailure.

## BUG-1029 : non traité (À CLARIFIER).

## Résultats réels ($TEMP/d59.log)
146 tests en 864 s : 145 OK, 1 FAIL ; `makemigrations --check` : No changes detected.
FAIL : clients.tests.test_clients_v13.Confidentialite.test_aucune_facture_mouvement_commission_cotisation_d_un_autre_noeud, `/api/sync/pull/` renvoie une clé `node_settings` hors TOP_KEYS. Sans rapport avec mes fichiers : probablement le travail en cours d'architecte-sync dans backend/sync/ (non touché). Test ni modifié ni affaibli ; à traiter par architecte-sync (ajouter la clé à TOP_KEYS ou la retirer).

## Risques
Non vérifié : import Excel (aucun changement de code). Rien commité.
