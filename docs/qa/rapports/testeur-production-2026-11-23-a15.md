# testeur-production a15 (cycle 16 partie A) - 2026-11-23

Fichier : `backend/production/tests/test_verif_production_a15_v15.py` (14 tests, banc K1/K2/K3 + cloud de A14Base). Lot avec a14 + d43 : 51 tests OK (1 echec attendu). Log `%TEMP%/a15.log`.

## Verdicts
- BUG-989, 990, 991, 992 : VERIFIE. Somme du groupe nulle (100) apres chaque scenario ET apres : K2 reinstalle en cours de transfert puis validation (+100 une seule fois), K1 reinstalle apres reponse ajustee (pas de re-debit), transferts croises K1->K2 / K2->K1 avec litige resolu par le siege, reponses de push/pull perdues et lot rejoue dans les deux sens, annulation de K1 apres reponse du siege (un seul conflit TRANSFER_STATE_CONFLICT), quantite ajustee 80/100 puis litige 78 puis ALIGN_ON_SENT / ALIGN_ON_RECEIVED, stock negatif par resolution (K1 -5, groupe 100).
- Test modifie `A14Migration0003` : le `migrate(latest)` ajoute avant `node.delete()` est justifie (la cascade vise `sync_transfermirror`, absente a la 0003) ; les assertions (0002 -> 0003 additive, aucune donnee inventee, lot conserve, cascade NodeOpenTransfers) sont inchangees : meme objet teste.
- `mirrors` hostiles (non-dict, types, flottants, booleens, negatifs, 1e30, listes de 3, cles geantes, 700 transferts, noeud tiers) : HTTP 200, aucun marqueur parasite pour un noeud non partie, groupe inchange.
- Cloud ancien sans `mirrors` + poste recent : envoi en cours reste coherent (somme 100) ; envoi deja confirme par le siege inconnu du poste : 100 pains perdus (limite annoncee, deployer le cloud d'abord ; test de documentation).

## Invariant « somme nulle »
Aucun scenario realiste ne le casse. Seule une valeur forgee/boguee par un poste le casse (BUG-997).

## Nouveau ticket : 1
- BUG-997 (Mineur, OUVERT) : marqueur `mirrors` non borne a la quantite de la ligne ; un poste partie qui pousse [0, 1000] pour un envoi de 100, puis reinstalle, tombe a -1000 pains. `@expectedFailure` dans a15.
