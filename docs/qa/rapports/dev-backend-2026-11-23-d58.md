# Rapport dev-backend d58 (2026-11-23) - ticket BUG-1022

## Verdicts (8 anomalies, reproduites isolément avant correction : 98 tests, 8 FAIL + 1 ERROR)
Traitées ici (3), tests périmés, aucun code applicatif modifié :
1. commissions `test_commission_deja_creee_garde_son_montant_apres_changement_boulangerie` : TEST PÉRIMÉ (BUG-1013/1014 : un zéro jamais décidé n'est pas figé, report sur la plus ancienne ligne non payée). Le test pose d'abord une cotisation 1000, change la boulangerie à 2000, vérifie que 1000 est conservé. Intention conservée.
2. production `a11_v11::test_bornes_farine_sur_fournee_existante` : TEST PÉRIMÉ (parseur partagé BUG-1015 : `1e2` refusé). Attendu REJECTED ; toutes les autres bornes inchangées.
3. production `a9_v9::test_just_above_boundaries_refused` : TEST PÉRIMÉ (BUG-1020 : ENTRY `-0.001` accepté comme en REST ; `1E+3` refusé). Aucune borne n'a sauté.

Traitées par dev-a (6 tests BUG-083, commit 6f80915 sur origin/dev-a) : la cause est BUG-988 (création API antidatée sur jour confirmé = 403, voulu). Mes modifications sur ces 3 fichiers de tests ont été annulées (`git checkout`) à la demande du coordinateur. Aucun défaut de code trouvé (la livraison rétroactive n'est pas bloquée par BUG-988).

Fichiers modifiés (non commités) : backend/commissions/tests/test_bug289_292_293_2026_11_14.py, backend/production/tests/test_verif_production_a11_v11.py, backend/production/tests/test_verif_production_a9_v9.py, docs/qa/REGISTRE_BUGS.md (BUG-1022).

## Résultats réels
Lot unique `$TEMP/d58.log` : 269 tests, 675 s, OK (commissions bug289 + commissions_v7, production a9/a11/a19, treasury bug083 x2 + b3 + c15 + c16 + d38, sales a6 + a7). `makemigrations --check --dry-run` : No changes detected.
Réserve : ce lot a démarré avant l'annulation des modifs sur les 3 fichiers treasury ; il a donc exécuté mes versions adaptées de ces 6 tests (verts). Après annulation, ils échouent à nouveau tant que le commit de dev-a n'est pas fusionné (attendu).

## Risques
Aucun changement de contrat d'API ni de code applicatif. Instabilité : aucune constatée.
