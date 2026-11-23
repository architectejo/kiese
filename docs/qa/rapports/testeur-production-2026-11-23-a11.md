# Testeur production a11 - 2026-11-23

Fichier : `backend/production/tests/test_verif_production_a11_v11.py` (25 tests, 4 `@expectedFailure`). Log : `$TEMP/a11.log`.

## Verifies
- BUG-938, BUG-939, BUG-940 : VERIFIES. Chaine a 3 postes, 6 ordres d'arrivee, rejeu x3, modification ciblee apres collision, categories differentes sur une meme facture, deux prix d'une meme categorie, ids hostiles (absent, texte, negatif, arabe-indien, 10**30, bool, liste) sans 500 ni doublon, fournee ouverte (farine, valeur du sac, notes, totaux recalcules, totaux du poste ignores), fournee close intacte, cloture + modification dans un meme envoi, bornes, autre noeud, node_origin forge.
- Cycle 3 postes (outbound, push, apply_push_response, pull, 2e cycle de correction) : factures (total = somme des lignes), fournees, transferts, comptages, stock de pains du cloud inchange par le push : OK.

## Nouveaux tickets : 4 (BUG-955 a 958 ; 951-954 pris par un autre testeur)
- BUG-955 (Mineur) : `invoice` malforme + id existant ecrase la quantite d'une ligne.
- BUG-956 (Mineur) : `sac_value_fc_used` '150000.0' -> erreur serveur (update et creation).
- BUG-957 (Mineur) : sac 0 devient 200000 a la creation, 0 accepte a la mise a jour.
- BUG-958 (Majeur) : transfert d'envoi direct (cree RESPONDED) rejete a la creation cloud (regle BUG-891), lignes en dependance manquante : jamais synchronise.

## Revue des choix d25/d28
- Borne 2e9 des dispositions/transferts : alignee sur `_strict_int` REST (entier 0..2e9) ; quantite de disposition bornee a 1 000 000 comme REST : OK, note.
- `consumable_type` controle en forme seulement (regex 1-10 car.) : acceptable tant que des codes metier non seedes sont poussees ; note, pas de ticket.
- Rejeu perime avec nouveau batch_id : ecrase une fournee ouverte (dernier ecrivain). Ne survient pas dans le cycle normal (etat courant reconstruit, meme batch_id idempotent) : note (test documentaire).
- Id d'ligne 10**30 : rejet generique « erreur serveur » (OverflowError SQLite), sans 500 : note.
