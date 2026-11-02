# Rapport coordinateur — 2026-10-22

## Fait
- État des lieux : registre des bugs encore au stade initial (BUG-001 à BUG-011, tous OUVERT, aucun agent testeur/dev n'a tourné). `docs/qa/rapports/` créé (était inexistant).
- Relecture de `remarque.md` (355 lignes) : confirmé que seules les lignes ~216-355 portent une marque `[c]` (corrections déjà faites hors circuit agents : import Excel clients, déplacement/suppression en masse, filtre boulangerie, pagination DRF >25 éléments, UI formulaire vente, file de livraison, consommables pilotables depuis Configuration). Les lignes 1-215 restent non auditées.
- Ouverture de 5 nouveaux tickets `BUG-012` à `BUG-016` dans `docs/qa/REGISTRE_BUGS.md`, un par module, pour que chaque testeur audite son périmètre de `remarque.md` non traité et transforme les écarts confirmés en tickets individuels.
- Rédaction du plan `docs/qa/PLAN_2026-10-22.md` : ordre des phases, parallélisme autorisé/interdit, critères de passage, et une règle transversale (§0.1) sur la distinction tests automatisés (`manage.py test`, base éphémère, jamais touché) vs vérification manuelle démonstrative contre `backend/db.sqlite3` (runserver + seed_kiese ou shell sans rollback), avec données fictives clairement identifiables, nettoyage à la discrétion du coordinateur.

## Tickets
- Ouverts : BUG-001 à BUG-016 (16 au total). Corrigés : 0. Vérifiés : 0.
- Aucun module « terminé » au sens CLAUDE.md §7.

## Questions en attente pour le client
- Q-001 à Q-004 déjà dans `docs/qa/QUESTIONS_CLIENT.md`, sans réponse (grille de prix, net à payer négatif, avenant refonte finance, parc PC). Aucune nouvelle question ouverte ce jour — pas de contradiction documentaire identifiée dans cette session, au-delà des 4 déjà connues.

## Prochaines actions
1. Lancer `nettoyeur-securite` (BUG-005, 006, 007, 009, 010) — seul, bloquant pour le reste.
2. Puis `ingenieur-blockchain` (BUG-001/002/003), conception de `architecte-sync` (BUG-004) à valider par le client humain avant code.
3. Puis les 5 testeurs de module en parallèle (BUG-012 à 016 + scénarios CLAUDE.md §5).
