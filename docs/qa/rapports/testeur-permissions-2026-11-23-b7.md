# testeur-permissions b7 (2026-11-23)

Fichier : `backend/core/tests/test_verif_permissions_b6_v6.py` (49 tests, OK, 8 `@expectedFailure`). SQLite. Code applicatif non modifié.

## Vérifiés
BUG-886, 887, 888, 889, 871, 686, 687, 688.
- 886 : variantes de types sur reset-data/chat (float, bool, dict, null) -> 400/404 ; reset réservé au superuser ; balayage de toutes les routes POST/PATCH/PUT avec 4 corps invalides : aucun 500 hors BUG-892.
- 887 : 7 colonnes figées sur distribution clôturée, déplacement de ligne entre distribution ouverte et clôturée refusé, jeton du mauvais nœud, REST (actions, tarif, création) ; ligne ouverte toujours modifiable.
- 888 : matrice complète (3 jetons x 5 statuts x 4 statuts = 60 cas) : seules PENDING->RESPONDED/CANCELLED (émettrice) et RESPONDED->CONFIRMED/DISPUTED (réceptrice) passent ; `quantity_received` jamais posée par l'émettrice ; statuts de type invalide sans 500.
- 889 : POST en période clôturée refusé (ADMIN, DIRECTION, COMPTABLE), POST en période ouverte OK, déplacement par PATCH/PUT vers une période clôturée refusé, set_manuel/suppression/generate refusés.
- 871 : refus pour GERANT/DIRECTION/ADMIN en POST, PUT, PATCH ; réactivation OK ; dépense existante garde sa catégorie.
- 686/687/688 : comptage, inventaire, dispatch, mouvement, disposition (POST et PATCH), respond/confirm, comptes datés futur (POST/PATCH/PUT), négatifs ; ASCII valide inchangé.

## Nouveaux tickets (6)
- BUG-891 (Mineur) : création par push d'un BreadTransfer dans n'importe quel statut (DISPUTED, CANCELLED, RESPONDED par la réceptrice).
- BUG-892 (Mineur) : `POST /api/treasury/reports/generate/` corps non objet -> 500.
- BUG-893 (Majeur) : PATCH month/year/node d'une période de commission clôturée.
- BUG-894 (Mineur) : push `quantity_received` = 10**15 accepté.
- BUG-895 (Mineur) : chiffres non ASCII sur prix de pain, valeur du sac, seuil meilleur client, plafond crédit.
- BUG-896 (Mineur) : opening-confirmation `qty` non ASCII / « 1e3 ».

## Observations sans ticket
- Push `LocalExpense` accepte une catégorie désactivée (saisie hors ligne antérieure).
- BUG-216 REJETÉ : mouvements négatifs/nuls toujours acceptés.
- `DISPUTED -> CONFIRMED` (`resolve_dispute`) non consolidée par le push (à voir par architecte-sync).
