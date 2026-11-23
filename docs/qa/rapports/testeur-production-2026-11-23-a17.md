# Testeur production a17 (2026-11-23) : verification BUG-1000 a 1003

Fichier : `backend/production/tests/test_verif_production_a17_v17.py` (38 tests, OK, 2 `@expectedFailure`). Log : `$TEMP/a17.log`.

## Verifies
- BUG-1000, 1001, 1002, 1003 : VERIFIE (a17).
- 1003 : scenario J / J+1 a 3 postes (K2 aujourd'hui, K1 aujourd'hui, K1 hier) = (100, 100, 0) ; somme du groupe par jour (effectue = recu) pour envoi direct, demande+reponse (poste et siege), litige+resolution (RECEIVED, SENT, recomptage K2), annulation, transferts croises, multi-lignes ; `updated_at` identique sur les copies.
- 1000 : pic enregistre au push et au pull (PENDING = 0). Abus du pic : un poste perime peut pousser jusqu'au pic mais le pull borne le marqueur a la ligne cloud (1001) : aucune fausse somme apres reinstallation (K1 [100,0] apres ALIGN_ON_RECEIVED, K2 [0,105] apres ALIGN_ON_SENT). Au-dela du pic, poste a jour, tiers : refuse. Pas d'abus possible de la somme.
- 1001/1002 : lignes inconnues et marqueurs vides non descendus, borne d'envoi 0 (PENDING, annule).
- Pull x5 a chaque etape : aucun mouvement, `updated_at` stable. Migration 0005 sur base existante : colonne ajoutee, ligne conservee, `peak = {}`, aller-retour 0004/0005 propre.

## Nouveaux tickets : 2 (BUG-1006, BUG-1007, Mineurs)
- BUG-1006 : confirmation hors ligne la veille, synchronisee le lendemain : K2 date la veille, cloud et K1 le lendemain ; somme par jour faussee (peut relever d'une decision metier).
- BUG-1007 : `stale` repose sur `last_sync`, pose a chaque push : un poste honnete dont le pull echoue est signale `MIRROR_OUT_OF_BOUNDS` au 2e push (bruit, sans effet sur les stocks). Meme effet sur une ligne migree 0005 au pic vide (observation).

## SOLD_DISCOUNT par push
Acceptable : donnees hors ligne anciennes ; la valeur est recalculee (qte x prix), la creation REST reste refusee (400). Pas un defaut tant que l'historique reste modifiable.

## Balayage push vs REST (production/ventes)
Disposal (type, notes > 255, quantites, valeur), ConsumableMovement (type inconnu), session (equipe, doublon, ownership), facture (equipe) : alignes sur REST, aucun nouvel ecart. Rien commite.
