# Testeur production a10 - 2026-11-23

Fichier de tests : `backend/production/tests/test_verif_production_a10_v10.py` (42 tests : 39 passent, 3 `@expectedFailure` = BUG-938/939/940). Log : `$TEMP/a10.log`. Aucun code applicatif modifie.

## Verifies : BUG-919 a 928 (10/10)
- 919 : collision d'id K1/K2 (ligne 7) pour InvoiceLine, ProductionSessionLine, BreadTransferLine : aucune perte, rejeu idempotent, lignes legacy sans doublon, K2 ne peut ni creer ni modifier une ligne de la facture de K1.
- 920 : fournee ouverte = mise a jour de la ligne, close = refus (meme valeur acceptee) ; transfert : emettrice avec autre quantite = REJECTED.
- 921/922/923/924/925/926/927/928 : controles et bornes exacts (dispositions 1 000 000 x 9 999 ok, x 10 000 refuse ; consumable_type regex, `SALT\n` refuse ; team '', A, B ; closed_at futur ; totaux recalcules et jamais copies ; transfert K1->K1 refuse ; quantity_received figee y compris 0).
- Cycle `build_outbound_payload` -> push -> `apply_push_response` sur 2 postes simules (ids de lignes identiques) : tout ACCEPTED, cloud correct, plus rien a envoyer ensuite ; rejeu avec reponse perdue idempotent ; poste ancien sans `source` = DECLARED sans doublon ; reponse hostile sans crash.

## Nouveaux tickets : 3 (BUG-938, 939, 940)
- BUG-938 (Majeur) : collision residuelle InvoiceLine entre deux categories d'une meme facture : une ligne en ecrase une autre, ACCEPTED. Cas plus courant que la limite deja documentee par le dev (meme categorie).
- BUG-939 (Majeur) : `flour_sacks_used` d'une fournee ouverte jamais propage au cloud apres le premier push : rendement theorique/ecart cloud faux.
- BUG-940 (Mineur) : id de ligne de facture absent/non numerique accepte et duplique a chaque rejeu.

## Observations sans ticket
- Limite connue (dev d28) : deux lignes de meme categorie sur une facture + collision d'id : indiscernables, non ticketee.
- Premier remplissage de `quantity_received` permis sur un transfert deja CONFIRMED (choix de d28) : a surveiller, aucun ecart/alerte n'est recalcule.
- Re-run partiel non effectue sur les autres suites (consigne : seulement ce fichier).
