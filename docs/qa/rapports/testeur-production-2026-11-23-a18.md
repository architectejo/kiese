# testeur-production a18 (cycle 19 partie A, 2026-11-23)

Nouveaux tickets : 0.

1. BUG-1007 : VERIFIE. `production/tests/test_verif_production_a18_v18.py` (10 tests, OK) : honnete sans pull qui rejoue son marqueur (aucune alerte), poste a jour + marqueur gonfle (MIRROR_OUT_OF_BOUNDS), pulled_at non modifie par le push, TransferPull stable au rejeu x10 (une ligne par noeud/transfert, pas de croissance), hostile sans pull (somme du groupe inchangee apres reinstallation ; au-dela du pic refuse), poste reinstalle/jamais livre traite en retard, pic vide initialise par le push, migration 0006 additive sur base existante + retour arriere/avant. Limite connue inchangee : un poste reinstalle perd son stock propre (pas de credit fantome). Volumetrie : au plus une ligne par (poste, transfert livre) ; borne par la fenetre de livraison des transferts.
   Pull echoue : pas de TransferPull pose, donc poste reste « en retard » (comportement voulu).
2. Sales (diff 3ae8168) : seul views.py change (`_get_object_retry` : get_object sous `_retry_on_lock`, 404/403 propages). Relecture : pas de regression ; `_deliver_once` est deja dans une retentative, la retentative interne est imbriquee mais bornee. test_verif_ventes_a7_v7 + test_ventes_a4_verif : OK.
3. Balayage production : a17 rejoue OK (1 echec attendu = BUG-1006, A CLARIFIER). Rien de nouveau : premier cycle propre de la partie A.

Run : 84 tests (a18+a17+ventes a7/a4), 2 echecs initiaux = mes assertions erronees (pic recu 98, perte de stock a la reinstallation), corrigees ; a18 isole 10/10 OK. Log $TEMP/a18.log.
