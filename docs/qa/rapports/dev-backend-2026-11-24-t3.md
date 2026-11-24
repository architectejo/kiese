# dev-backend (Dev B) - 2026-11-24 - tache B-2 / BUG-1116 (client neuf « SUSPENDU », remarque.md l.508)

## Cause (deux defauts)
1. **Statut SUSPENDU = `is_active=False`** : `frontend/src/components/clients/ClientsTable.tsx` l.174-175 affiche `client.active ? 'ACTIF' : 'SUSPENDU'` (`active` = `is_active`, `clientItem.ts` l.48). A la creation AVEC PHOTO, `Clients.tsx` l.392-397 envoie un `FormData` (multipart). DRF lit un booleen ABSENT comme FAUX en multipart : `ClientCreateSerializer.is_active` ecrivait donc False, le client neuf etait inactif donc « SUSPENDU ». (En JSON, sans photo, le defaut True s'appliquait.)
2. `Client.refresh_category` : `dette >= plafond` classait « a risque » un client a dette 0 et plafond 0 (BUG-742).

## Correction (backend uniquement)
- `backend/clients/serializers.py` : `DefaultTrueBooleanField` (champ absent = valeur par defaut, `is_active=False` explicite toujours respecte) sur `ClientCreateSerializer` et `ClientSerializer` (un PUT multipart ne desactive plus non plus).
- `backend/clients/models.py::refresh_category` : RISK seulement si `dette > 0` ET `dette >= plafond`. Plafond 0 + dette > 0 reste RISK (comportement conserve) ; dette = plafond > 0 reste RISK.
- Import Excel et push sync : creent deja `is_active=True` (defaut du modele) et passent par `refresh_category` (corrige par le modele) ; `backend/sync/` non touche.
- Pas de migration ; contrat d'API inchange.

## Frontend (NON touche) : a faire / optionnel pour dev-frontend
- `frontend/src/components/clients/ClientsTable.tsx` l.174-175 : le libelle « SUSPENDU » est affiche pour tout `active=false`. Apres la correction, un client neuf est actif. Proposition : remplacer « SUSPENDU » par « INACTIF » (un client desactive n'est pas suspendu pour credit) ; aucun autre changement requis.
- Donnees existantes : les clients deja crees inactifs par le defaut multipart restent « SUSPENDU » en base ; a reactiver par le gerant, ou migration de donnees a decider par le coordinateur (non faite).

## Tests
- Nouveau `backend/clients/tests/test_dev_b2_client_suspendu.py` (6 tests : creation par gerant, facturier, livreur, direction x JSON/multipart avec photo x plafond absent/50 000/0, verifiant API detail ET liste ; multipart sans photo ; `is_active=false` explicite respecte ; plafond 0 dette 0 NORMAL / dette 1 RISK ; dette = plafond RISK ; PATCH plafond 0). **Avant correction : 4 echecs sur 6** (is_active False, RISK) ; **apres : 6/6 OK** (71 s).
- Suite `python manage.py test clients commissions.tests --noinput` (inclut test_api, v2 a v18, test_dev_b1/b3, test_clients_v10/v13/v17/v18, test_dev_b3_livreur_en_ligne) : **977 tests en 6104 s, 1 echec, 5 echecs attendus, 1 succes inattendu** (log `$TEMP/t3.log`). `makemigrations --check --dry-run` : « No changes detected ».
  - **ECHEC** `clients.tests.test_clients_v6.RegressionFluxLegitimes.test_bug737_client_facture_dans_deux_boulangeries_retenu_une_fois` (K3 net 5000 attendu, 4500 obtenu : carte d'imprime, BUG-1104). **Sans rapport avec mon changement** (aucune categorie en jeu) : le fichier `test_clients_v6.py` porte une modification NON COMMITEE d'un autre agent (13 lignes, attente passee de 4500 a 5000 pour BUG-1104) alors que le code commissions correspondant ne la satisfait pas encore / pas le meme etat. A traiter par l'agent commissions (je n'ai pas le droit de toucher `commissions/` ni de faire de git stash pour comparer).
  - **SUCCES INATTENDU** `test_clients_v2.CategorieTests.test_plafond_zero_avec_dette_zero_n_est_pas_a_risque` : c'est le test `@expectedFailure` de BUG-742, desormais PASSANT grace a ma correction. Le testeur doit retirer le `@expectedFailure` (l.338) et passer BUG-742 a VERIFIE ; je ne l'ai pas modifie (interdit). Tant que ce n'est pas fait, la suite clients sort en rouge a cause de ce succes inattendu.

## Registre
BUG-1116 ajoute (apres BUG-1113) : « CORRIGE backend ; frontend optionnel ». Pas de modification de BUG-742 (a faire par le testeur).

## Risques
- Les clients deja inactifs en base le restent. - Un client a plafond 0 devient « NORMAL » a dette 0 : le blocage de facturation (BP >= plafond) est independant de la categorie et inchange.
