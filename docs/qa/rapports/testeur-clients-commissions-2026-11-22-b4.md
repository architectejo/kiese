# Testeur Clients et Commissions - 2026-11-22, ronde b4

Périmètre : vérification indépendante de BUG-745, 747, 749, 750 (D8) et BUG-821, 822 (commissions), 824 (D7), puis recherche de nouveaux défauts.
Nouveaux fichiers de tests (aucun code applicatif modifié, données fictives) :
- `backend/commissions/tests/test_commissions_v4.py` (35 tests : ajustements 821/822, compteur 824, set_manuel)
- `backend/clients/tests/test_clients_v4.py` (17 tests : bornes de la remise annuelle et du total à recevoir, recalculs, distribution clôturée, corps non-objet)

## Verdicts

| Ticket | Verdict | Preuve |
|---|---|---|
| BUG-745 | VÉRIFIÉ | `1E999999999`, `-1E999999999`, `1E+99999999999` = 400, aucune valeur écrite ; 25 chiffres, 10^12, -10^12 = 400 ; `999999999999.99` accepté ; `1e-999999999` accepté (0,00) ; la liste des commissions reste lisible après chaque tentative |
| BUG-747 | VÉRIFIÉ (ligne et tarif) | somme exacte 99 999 999,99 acceptée, 100 000 000,00 refusée (total_social + mérite, ou 12 x 8 333 333,33 + mérite 0,03/0,04) ; PATCH de ligne ; PATCH du tarif refusé si une ligne existante déborde (12 x 8 333 250 + 1 000 = 10^8 refusé, 8 333 249 accepté, remise 99 998 988 et total 99 999 988 exacts) ; tarif hors colonne, NaN, Infinity, négatif = 400. Chemins voisins non couverts : BUG-753 |
| BUG-749 | VÉRIFIÉ | notes seules conservent l'ajustement et le net ; `null` explicite efface ; `0` distinct de `null` (net 0,00) ; corps vide = 400 « detail » sans effet (ajustement 700 conservé) ; champs inconnus seuls = 400 ; commission payée = 400 pour notes seules, ajustement et effacement ; gérant, facturier, livreur, comptable = 403 ; id inconnu = 404 |
| BUG-750 | VÉRIFIÉ | `manuel_notes=null` devient chaîne vide, ajustement conservé ; notes 123, liste, dict, booléen : jamais 500 ; 100 000 caractères acceptés |
| BUG-821 | VÉRIFIÉ (déjà VÉRIFIÉ par l'audit, contrôle indépendant concordant) | RG + ajustement +2 ou -3 : aucune ligne de CM ; RG ajustée + vente normale de 20 pains : seule la vente compte (10 000 FC, CM 2 500) ; vente normale ajustée +2 : 6 000 FC, CM 1 500 ; vente soldée ajustée : exclue |
| BUG-822 (commissions) | VÉRIFIÉ | 10 pains - 3 = 7 pains, 3 500 FC, CM 875 ; chaîne -4/+1/-2 = 5 pains, 2 500 FC ; ajustement à deux catégories : 15 - 7 = 8 pains, 6 000 - 2 000 = 4 000 FC ; net négatif sur le mois (original le mois précédent) : aucune ligne, jamais de pains négatifs |
| BUG-824 | VÉRIFIÉ | -3 : 10 devient 7 ; +5 : 15 ; plusieurs lignes sommées ; plancher 0 ; NS inchangé ; facture sans client sans erreur ; catégorie : 99 NORMAL, 100 MEILLEUR (seuil >=), retour à 99 NORMAL ; « À risque » prime sur « Meilleur client » ; ajustement refusé (400 quantité excessive, 403 facturier) : compteur inchangé |

Le 400 « aucun champ » de `set_manuel` (corps `{}` ou champs inconnus seuls) est maintenant testé : conforme. Les bornes exactes de set_manuel (±999 999 999 999,99 acceptés, ±10^12 refusés) sont testées : conformes.

## Nouveaux tickets (3)

- **BUG-751** (Mineur) : un corps JSON non-objet (`[]`, `[1]`, `"x"`, `5`) sur `set_manuel`, `mark_paid`, `periods/generate`, `bulk_create_month`, `bulk_move`, `bulk_delete` donne 500 (`request.data.get` sur une liste) au lieu de 400.
- **BUG-752** (Majeur) : une distribution de caisse sociale clôturée reste modifiable par ses lignes (PATCH de `merite` = 200 et total recalculé ; création et suppression de ligne acceptées) alors que tarif, année, réouverture et recalculs sont verrouillés.
- **BUG-753** (Mineur) : `refresh_indices` et `auto_populate_lines` donnent 500 quand la somme des cotisations payées d'un client dépasse la colonne `total_social` (2 x 99 999 999,99), même classe que BUG-747.

Tests des trois tickets : `@expectedFailure` avec la référence du ticket (6 tests marqués, verts dans la suite).

## Observations sans ticket
- Les anciens tickets 738, 742, 748, 783 n'ont pas été retouchés.
- `annual_bonus` est toujours 0 par construction (BUG-295) : la « remise annuelle » est désormais `indice x tarif + mérite` côté caisse sociale ; ses bornes sont couvertes par BUG-747/752/753 ci-dessus.
- Les tests sont lents sur cette machine (environ 9 s par test d'API, plusieurs agents en parallèle) ; la suite complète prend plusieurs milliers de secondes.
- Un fichier de log partagé `$TEMP/x.log` a été écrasé par un autre agent pendant la session : j'ai utilisé des journaux nommés `ccb4_*.log`.

## Résultats
- Fichiers v4 seuls : 52 tests, 6 expectedFailure (BUG-751 x3, 752 x2, 753 x2 selon test), 0 échec après marquage.
- `manage.py test clients commissions` : **514 tests, OK, 14 expected failures** (7 de cette ronde : BUG-751 x3, 752 x2, 753 x2 ; 7 antérieurs : 738, 742, 748, 783 et autres), 0 échec, 0 succès inattendu, 2676 s.
