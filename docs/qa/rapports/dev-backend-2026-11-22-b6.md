# dev-backend Dev B - 2026-11-22-b6 - BUG-417 (cotisation 2 000 / carte 1 000 partout)

Decision du responsable (message #23) : cotisation sociale 2 000 FC, carte 1 000 FC, toutes boulangeries.

- Migration de donnees `core/0022_defauts_cotisation_carte_partout` (0021 intacte) : 0 -> defaut ; valeur propre > 0 differente non ecrasee, signalee (print + logging) ; idempotente ; reverse no-op (indiscernable d'une saisie manuelle).
- Seeds (`seed_kiese`, `seed_production`, `seed_from_excel.py`) : aucun forcage de 0, ils heritent des defauts du modele (2000/1000) : inchanges. `Nodes.tsx` : defauts 2000/1000 deja en place, inchange.
- Commissions deja generees : non modifiees (question ouverte au client). `deduction_carte` 1 % reste 0.
- Tests : `core/tests/test_bug417_migration_defauts_partout.py` (5). `core/testing.make_node` inchange (defauts neutres 0).
- Valeurs propres a signaler : la migration les liste a l'execution sur la base reelle (code, champ, valeur) ; aucune connue avant execution (B2 = 2000 deja, autres 0).
- Risque : le reverse ne restaure pas les anciens 0.
