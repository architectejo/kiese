# Testeur clients/commissions, cycle 16 partie B (2026-11-23)

Log : `$TEMP/b16.log`. Commande : `manage.py test clients.tests.test_clients_v12 clients.tests.test_clients_v11 clients.tests.test_clients_v10` : 93 tests, OK (1 échec attendu : BUG-998).

## Tests réparés (tests uniquement)
- `test_clients_v11.py::test_BUG_994_*` : plafond attendu 80 000 pour K1-P00007 (i % 7 == 0), 50 000 pour K1-P00008. Le code était correct.
- `test_clients_v10.py::Migration0011` : migration en deux appels (clients 0010 puis feuille core, graphe reconstruit) et routeur temporaire vers la base jetable. Cause réelle : les `RunPython` (ex. core 0021) appellent `Model.objects` sans `using` ; avec le nouveau plan ils s'exécutaient sur la base `default`. Vérification inchangée (identity_updated_at NULL, dette/plafond intacts).
- Hors périmètre : `test_verif_bug289_295_2026_11_15::Migration0010` (autre agent) donne encore 1 erreur dans mon essai de non-régression ; non investigué.

## Vérifications indépendantes
- BUG-993 VÉRIFIÉ : facture de la veille poussée le lendemain gardée à sa date ; période de commission close = un seul avertissement (rejeu x3 sans doublon) ; 8 dates invalides rejetées (futur, 2019, mois 13, format FR, chiffres pleine chasse, entier) ; absente/None/'' = jour du push ; rejeu avec autre date ne déplace pas ; aller-retour export/import exact.
- BUG-994 VÉRIFIÉ : poste neuf 5 000 clients créés en 1,2 s ; rejeu 5 000 en 14,7 s (mises à jour une à une) ; aucun DebtMovement ni notification ; aucun doublon de code (collision locale : le client cloud est ignoré et journalisé) ; lignes invalides ignorées ; dette négative (épargne) conservée ; rien de renvoyé au cloud ; ancien cloud sans `node` : rien créé, connus mis à jour.
- BUG-995 VÉRIFIÉ.

## Nouveau ticket : 1
- BUG-998 (Majeur) : le pull ne descend pas les clients des autres boulangeries jamais facturés ; contredit CLAUDE.md 5.1 hors ligne. Test `@expectedFailure`.

## Observation
Un code client local déjà pris par un client cloud différent (création hors ligne concurrente) fait ignorer définitivement le client cloud sur ce poste (journal seulement, pas de notification) : à surveiller, non ticketé.
