# Rapport dev-backend d61 (2026-11-23) : BUG-1031 a 1035

Tous CORRIGÉ (a verifier par testeur-production ; les `@expectedFailure` de `test_verif_production_a20_v20.py` sont retires, assertions inchangees).

- 1031 : regle unique "zeros finaux acceptes si la valeur tient dans les decimales autorisees" ; `0.3333` reste refuse. `_canonical_decimal_data` (production/serializers.py) pour quantite/prix de mouvement, physical_quantity, flour_sacks_used (le push l'acceptait deja via core/numeric.py, inchange).
- 1032 : decision : refus des DEUX cotes (prix negatif => CUMP negatif, BUG-803). REST 400 "Le prix unitaire ne peut pas être négatif." ; push inchange. Changement de contrat : nouveau 400 REST.
- 1033 : unit_price via parse_ascii_decimal (4 decimales) en REST et push (sync/services.py : verification + construction).
- 1034 : notification "Stock négatif" sur entree negative sous zero (production/models.py, branche ENTRY, REST et push).
- 1035 : `_unresolved_incoming_transfer_gap` juge un DISPUTED sans ligne sur l'en-tete. **treasury/views.py est un fichier de dev-a** (modification minimale, ajout d'un bloc, cas avec lignes inchange).

Fichiers : production/serializers.py, production/models.py, sync/services.py, treasury/views.py, production/tests/test_verif_production_a20_v20.py (decorateurs + import retires), docs/qa/REGISTRE_BUGS.md.

## Resultats REELS
- Passe 1 (log $TEMP/d61.log) : 334 tests, 269 s : OK sauf 1 erreur de chargement, due a MON chemin errone (`production.tests.test_dev_d38_blocage_ventes`, le module est `treasury.tests.test_dev_d38_blocage_ventes`) ; 1 expected failure preexistante (autre ticket, hors a20, non touchee).
- Passe 2 : `treasury.tests.test_dev_d38_blocage_ventes` : 15 tests OK.
- `test_verif_production_a20_v20` seul : 25 tests OK (aucun expectedFailure restant).
- `makemigrations --check --dry-run` : No changes detected.

## Risques
- Nouveau 400 REST sur `unit_price` negatif (frontend : message deja au format `{"detail"}`).
- Si un jour les prix negatifs sont voulus (avoirs fournisseur), il faudra revoir le CUMP.
- Suite complete non lancee (consigne : liste ciblee).
