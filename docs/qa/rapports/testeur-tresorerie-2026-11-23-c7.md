# testeur-tresorerie, 2026-11-23, cycle 6 partie C (c7)
Fichier : backend/treasury/tests/test_verif_tresorerie_c7_v6.py (25 tests, OK, 1 expectedFailure). Log : $TEMP/c7.log.

- BUG-863 : VÉRIFIÉ (7 tests : WARNING/DANGER, exact, écart inchangé, double validation, node_origin).
- BUG-677 (dépenses locales, scope) : VÉRIFIÉ (13 tests : POST/PATCH/PUT refusés pour DIRECTION, liste et détail masqués au gérant, HQ autorisé, scope non modifiable par le gérant, scope invalide 400, dépense existante intacte après changement de portée, filtre ?scope).
- BUG-860/861/862 : déjà VÉRIFIÉS (c6), non rouverts.
- Interactions transferts / BUG-675 : la clôture de caisse n'est pas affectée par les transferts conformes ; écart entrant bloque seulement la réceptrice, annulé ignoré, bloque le versement ; chaîne et soldes sur 2 boulangeries corrects.
- Nouveau ticket : BUG-871 (catégorie de dépense inactive acceptée), Mineur, `@expectedFailure`.
