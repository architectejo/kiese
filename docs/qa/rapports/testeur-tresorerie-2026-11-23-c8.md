# testeur-tresorerie c8 (2026-11-23)

Tests : `backend/treasury/tests/test_verif_tresorerie_c8_v7.py` (35 tests, OK, 1 échec attendu).

## Verdicts
- BUG-897 VÉRIFIÉ (zone trésorerie) : chiffres « ٣ » / « １２ » refusés (400) sur dépense (POST, PATCH), billetage de clôture (POST, PATCH), journal (entrée, sortie), épargne (revenu, sacs, taux), bordereau, comptage direction. Aucun refus à tort : décimaux (12500.50, 0.01), entiers JSON, chaînes ASCII, multipart, libellés accentués, billetage 8 coupures (écart nul, positif, négatif).
- BUG-898 VÉRIFIÉ : push dépense, montants légitimes acceptés ; −500, 0, absent, texte, NaN, Infinity, booléens, listes, non ASCII, ≥ 1E12 refusés ; lot mixte : les valides passent.
- BUG-899 VÉRIFIÉ : catégorie DIRECTION refusée pour jeton boulangerie, acceptée pour jeton SIEGE (node=SIEGE) ; catégorie désactivée et BAKERY acceptées.

## Angles complémentaires (verts)
- Journée complète : 2 rapports (A/B), dépense décimale, billetage, validation, versement (VC-C1-AAAAMMJJ, entrée = caisse nette), bordereau (sortie, solde), chaîne valide, finance cashflow/income_statement cohérents.
- Double versement refusé ; bordereau > solde refusé sans bon créé, = solde accepté ; bordereau PUT/PATCH/DELETE 405 ; journal 405 ; épargne upsert, taux 0, sans effet sur le livre ; comptage direction sans effet sur la chaîne.
- Journal des écarts : cash_gap/net_cash/physical_cash_total non modifiables, clôture validée non supprimable.
- Finance N / N-1 : dépenses et résultat séparés par exercice, accès réservé au siège.
- BUG-675 : un transfert inter-boulangeries confirmé ne modifie pas la caisse nette ni l'écart de clôture (le signe de l'appro reçu ne concerne que le total du jour de production).

## Nouveau ticket
- BUG-900 (Mineur) : push LocalExpense `0.001` accepté puis stocké à 0.00 FC (REST refuse). Test `@expectedFailure`.

## Observation sans ticket
- Clé étrangère (catégorie) en chiffres pleine largeur résolue comme l'id ASCII (aucun montant concerné).
