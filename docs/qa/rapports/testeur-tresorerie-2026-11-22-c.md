# Rapport testeur-tresorerie (Dev C) - 2026-11-22-c - verification independante

Etat 2fcfa0e, branche dev-c. Aucun code applicatif modifie.

## Resultats
| Ticket | Resultat |
|---|---|
| BUG-381 (Versement direction, lecture) | VERIFIE (statut, table et fiche mis a jour) |
| BUG-383 (page Caisse) | VERIFIE (code, tsc, build ; rendu navigateur impossible) |
| BUG-533 (decoupage Treasury.tsx) | VERIFIE (comparaison automatique de fidelite) |
| BUG-526 a 529 + helpers node_guard | VERIFIES (balayage siege + gerant, helpers attaques) |
| BUG-516 (PROTECT) | reste VERIFIE (migration 0002, ProtectedError) |
| BUG-175 (rapports retroactifs) | reste VERIFIE apres decoupage (ClotureOperations.tsx) |
Aucun ticket rouvert, aucun BUG-545 a 549 ouvert.

## Tests ajoutes
`backend/treasury/tests/test_verif_versement_chaine_c.py` : 21 tests (Versement 9, helpers 3, params 500->400 4, chaine 4, PROTECT 1).
Serie `python manage.py test treasury blockchain` : 342 tests OK. `makemigrations --check` propre.
`tsc --noEmit` 0 erreur ; `npm run build` OK.

## Chaine de hash
Une seule fonction (`treasury/hashing.py`), aucun `hashlib.sha256(` ailleurs dans treasury/blockchain.
30 ecritures sur 2 boulangeries : solde final correct, `integrity_check` valide, `run_check` sans alerte.
Alteration directe du montant ou du champ node : detectee par integrity_check ET run_check cree une TamperAlert (meme verdict).
La lecture Versement n'a aucun effet sur la chaine.

## Observations non bloquantes
- Premier GET d'un compte : creation paresseuse de Config + ActivityLog « Modification Configuration » (effet de bord hors endpoint).
- COMPTABLE : API Versement autorisee, UI limitee a ADMIN/DIRECTION (a trancher client, remarque.md l.307 vs l.456).
- Deux selecteurs de succursale cote siege (Caisse / Cloture Journaliere), deja signale par dev-frontend.
- Frontend : pas de test composant ; fidelite BUG-533 etablie par comparaison de litteraux/appels/classes, rendu a confirmer a 360/768/1440 px.
