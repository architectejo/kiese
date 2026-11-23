# dev-backend d57 (Dev B) - 2026-11-23 : triage de la serie complete (BUG-1021)

Serie d'origine : 7 FAIL, 3 ERROR, 4 UNEXPECTED SUCCESS. Tous reproduits isolement (log $TEMP/d57_iso.log : 7 FAIL, 3 ERROR, 3 US ; le 4e US, Retenue737, etait deja retire).
Resultat final du lot (log $TEMP/d57.log) : 591 tests (modules concernes + `sync` + production a12/a13), OK (expected failures=2). `makemigrations --check` : aucun changement.

| # | Test | Verdict |
|---|---|---|
| 1 | core.test_verif_bug417_c MigrationReelleTests.test_commissions_deja_generees_inchangees | test perime corrige (migrer jusqu'a la feuille avant d'utiliser les modeles courants) |
| 2 | clients.test_migration_social_uuid | test perime corrige (routeur temporaire + migration en deux temps) |
| 3 | clients.test_migration_social_uuid_volume | idem |
| 4-6 | core.test_verif_permissions_b4_v4 SyncPull (3 tests) | tests perimes (BUG-998/999) reecrits, intention de securite conservee et renforcee ; aucune fuite reelle, aucun 500 |
| 7 | V888.test_matrice_complete... | VRAI DEFAUT code corrige |
| 8 | V891.test_BUG_891_creation_par_push... | test perime (BUG-958) |
| 9 | V891.test_litige_disputed_vers_confirmed_impossible... | VRAI DEFAUT code corrige (meme cause que 7) |
| 10 | sync test_verif_bug331_332 Creation.test_creation_bornes | test perime (BUG-919/938/940 : cle naturelle facture+categorie) |
| 11-13 | UNEXPECTED SUCCESS BUG-540, BUG-562, BUG-748/950 | comportement conforme aux tickets, `@expectedFailure` retires (import inutilise conserve) |
| 14 | Retenue737 test_suppression_de_la_ligne... (BUG-1011) | instabilite/serie perimee : decorateur deja absent, passe isolement |
| + | V896.test_BUG_896... (decouvert en lot) | test perime : `+3` accepte par le parseur partage (d55) |

## Vrai defaut (code) : sync/services.py, _push_transfer
Depuis BUG-966, DISPUTED -> CONFIRMED par push etait refuse si une ligne presentait un ecart, mais `any()` sur liste vide est faux : un transfert en litige SANS ligne (historique) se levait par un simple push de statut, meme avec recu != envoye ou recu absent, sans passer par resolve_dispute (stock non realigne). Correctif : sans ligne, l'ecart se juge sur l'entete (`quantity_received != quantity_sent` -> refus « litige non resolu »). Avec lignes : inchange. Les tests V888/V891 existants passent sans modification.

## Fichiers
Code : backend/sync/services.py. Tests : core/tests/test_verif_bug417_c.py, test_verif_permissions_b4_v4.py, b7_v7.py (V891, V896), test_verif_c5_routes_noeuds_c.py, clients/tests/test_migration_social_uuid.py, test_migration_social_uuid_volume.py, test_clients_v3.py, sync/tests/test_verif_bug331_332_testeur_charge.py. Registre : BUG-1021 (CORRIGE).

## Risques
- Le registre/tests ne touchent ni commissions/views.py ni production/. 
- Les 3 tests de migration dependent de l'ordre du graphe : a re-verifier a chaque nouvelle migration core.
- Serie complete 2052 tests non relancee en entier (module concerne + sync + production a12/a13 seulement).
- Ticket a faire VERIFIER par un testeur (je ne passe pas a VERIFIE).
