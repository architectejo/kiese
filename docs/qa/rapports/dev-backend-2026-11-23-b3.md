# Rapport dev-backend (Dev B) - B-3 : livreur et clients des autres boulangeries (Q-025 / BUG-507 / BUG-1106 / BUG-1203)

## Definition de « en ligne » (`backend/sync/connectivity.py::node_is_online(node)`)
- CLOUD (pas de `KIESE_CLOUD_URL` dans les settings ; c'est le cas du mode de test) : toujours en ligne.
- POSTE LOCAL (`settings_desktop`, `KIESE_CLOUD_URL` renseigne) : en ligne si le dernier echange de synchronisation reussi (push ou pull de `sync.desktop_client`, memorise en memoire, ou `Node.last_sync`) date de moins de `KIESE_ONLINE_WINDOW_MINUTES` minutes (defaut 15, variable d'environnement lue par `settings_desktop`). Jamais synchronise, echange perime ou valeur de fenetre invalide (retombe sur 15) : hors ligne ou defaut sur.
- Limite connue : l'etat en memoire repart a zero au redemarrage du poste ; le poste est « hors ligne » jusqu'au premier cycle reussi (30 s) ou jusqu'a `Node.last_sync`.

## Code
- `backend/sync/connectivity.py` (nouveau) ; `backend/kiese/settings_desktop.py` (+ `KIESE_ONLINE_WINDOW_MINUTES`).
- `backend/clients/views.py` : `get_queryset` : LIVREUR hors ligne limite a `user.node` (detail d'un autre client : 404, jamais 500) ; FACTURIER inchange ; autres roles inchanges. `create` : `IsFacturierOrLivreur` (BUG-1203) ; `perform_create` impose deja la boulangerie de l'utilisateur et les valeurs par defaut (plafond/taux). Modification, suppression, bulk, import : toujours fermes au livreur (403, teste).
- Aucun contrat d'API modifie. Ticket BUG-1106 ajoute au registre (CORRIGE backend ; frontend : indicateur « hors ligne » optionnel).

## Tests
- Nouveau `backend/clients/tests/test_dev_b3_livreur_en_ligne.py` : 19 tests (helper cloud / local recent / perime / jamais synchronise / fenetre configurable et invalide / `Node.last_sync` ; livreur en ligne voit K2 ; hors ligne non ; recherche par code et nom ; detail 404 ; facturier, gerant, direction, comptable inchanges ; etat corrompu sans 500 ; creation dans sa boulangerie, `node` force ignore, plafond/taux imposes ; actions fermees). Resultat reel : 19 tests OK.
- Test existant modifie : `clients/tests/test_clients_v2.py::CreationTests::test_livreur_ne_cree_pas_de_client` affirmait l'ancienne regle (403) ; remplace par `test_livreur_cree_client_dans_sa_boulangerie_seulement` (decision Q-027 / BUG-1203). Relance de `CreationTests` : 13 tests OK. A faire valider par le testeur d'origine.
- Passe complete (log `$TEMP/b3.log`) : clients v10, v13, v14, v15, v16, v3, v2, `core.tests.test_verif_permissions_b4_v4`, `sync.tests.test_verif_sync_v5` : 269 tests, 1 echec (le test v2 ci-dessus, obsolete, corrige ensuite et relance OK), 1 echec attendu (`expectedFailure` existant). Les 19 tests B-3 sont a part (premiere passe : OK en 415 s). `makemigrations --check --dry-run` : « No changes detected ».
- Non relances apres la correction du test v2 : le reste de la liste (aucun autre fichier touche).

## Risques
- Un poste local dont la synchronisation est coupee plus de 15 min cache les clients des autres boulangeries au livreur : c'est la regle voulue.
- Le facturier garde l'acces inter-boulangeries meme hors ligne (inchange).
