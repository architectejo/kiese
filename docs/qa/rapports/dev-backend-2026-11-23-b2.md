# dev-backend (Dev B), B-2 : Carte = un montant fixe par client et par mois (BUG-1104)

Statut : CORRIGÉ. Montant à confirmer avec le client : « 1 000 FC ? » (défaut `Node.card_fee_fc`, propre à chaque boulangerie, Q-026).

## Constat
- Facture : pas de retenue par facture (les factures du mois sont agrégées par client dans `generate`). Conforme.
- `deduction_carte` / `deduction_prints` : `deduction_carte` reste 0 (BUG-291), la carte est dans `deduction_prints` ; `carte_fc` (serializer), `total_carte` (summary, history) lisent `deduction_prints`. Pas de double comptage. Conforme.
- **Non conforme** : la carte était posée à la création de chaque ligne de commission (`card_fee_fc` de la boulangerie). Un client facturé dans 3 boulangeries payait 3 cartes, alors que dette et cotisation suivaient déjà la porteuse unique (BUG-737/1013/1014).

## Correction
- `commissions/models.py` : champ `card_applied` (porte la carte du mois). Migration `0007_bug1104_card_applied.py` : toutes les lignes existantes marquées True (une régénération ne modifie jamais l'existant ; changer `card_fee_fc` ne touche pas les commissions déjà générées). Réversible.
- `commissions/views.py` (`generate`) : lignes créées à `deduction_prints = 0` ; si aucune ligne du (client, mois) ne porte la carte, elle est ajoutée sur la ligne non payée, période ouverte, la plus ancienne (created_at, pk), avec le `card_fee_fc` de la boulangerie de cette ligne. Dans le verrou client existant. Porteuse payée : la carte reste, les autres à 0. Porteuse supprimée : reportée à la régénération. `card_fee_fc` = 0 : aucune retenue.
- `commissions/serializers.py` : `card_applied` en lecture seule (contrat API : nouveau champ, aucune action frontend requise ; colonne « Carte » = `carte_fc`).
- Net à payer = (CM brute + remise incorporée) − total retenues inchangé (formule de `compute`, la carte reste dans `deduction_prints`).

## Tests
Nouveau `commissions/tests/test_dev_b2_carte.py` (11 tests, valeurs à la main) : 1 boulangerie (net 10 000), 3 factures du mois, 3 boulangeries (carte 1 000 une fois, nets 37 500 − 1 500 − 1 000), ordre de génération inversé (porteuse Y3 = 600), régénération, porteuse payée, porteuse supprimée, `card_fee_fc` = 0, changement de `card_fee_fc` sans effet sur l'existant, deux clients (1 000 + 800, summary 1 800), net avec dette 4 000 (31 000).

Tests existants dont l'attente « une carte par ligne » était l'ancienne règle, adaptés (assertions déplacées sur « une seule carte », rien supprimé) : v2 `ClientMultiBoulangerieTests.test_chaque_boulangerie_a_sa_ligne_avec_sa_carte`, v3 `Retenue737Tests.test_trois_boulangeries_une_seule_retenue_dette_et_cotisation`, v5 `RetenueUniqueHorlogeGrossiere` (3 tests via `assert_une_seule_retenue`), v6 `Multi.test_net_a_payer_exact_de_chaque_ligne`.

## Résultats réels
- Série 1 (`test_dev_b2_carte`, v7, v6, v5, v4, v3, d49, `sync.tests.test_verif_charge_v3`) : 161 tests, 5 FAIL = les 5 tests de l'ancienne règle ci-dessus (aucun autre).
- Après adaptation : v6.Multi + v5.RetenueUniqueHorlogeGrossiere + v3.Retenue737Tests : 28 tests OK.
- `test_commissions_v2` + `test_bug417_carte_cotisation_par_boulangerie` + `test_bug289_292_293_2026_11_14` : 59 tests, 1 FAIL (v2 ancienne règle, adapté) ; `ClientMultiBoulangerieTests` après adaptation : 3 tests OK. Les 2 expected failures sont préexistants.
- `makemigrations --check --dry-run` : No changes detected.
- Non relancé après adaptation : v7, v4, d49, verif_charge_v3 (passés dans la série 1), et le reste de la suite complète.

## Risques / limites
- Les mois déjà générés avant la migration gardent leurs cartes multiples éventuelles (pas de rattrapage automatique, pour ne pas modifier des paies existantes).
- Un POST manuel de commission (`perform_create`) n'ajoute pas de carte.
- `deduction_prints` mélange carte et imprimés : une saisie manuelle sur la porteuse écrase l'ensemble (comportement inchangé).
- Non touché : `backend/core/`, `backend/clients/views.py`, frontend.
