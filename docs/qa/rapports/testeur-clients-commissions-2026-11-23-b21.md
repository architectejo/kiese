# Testeur clients/commissions, ronde b21 (2026-11-23)

Tests : `backend/commissions/tests/test_commissions_v8.py` (19 tests : 18 OK + 1 expected failure) et `backend/clients/tests/test_clients_v17.py` (19 tests : 16 OK + 3 expected failures). Passes réelles, une par fichier (log `$TEMP/b21.log`). Code applicatif non modifié.

## Verdicts
- BUG-1013 VÉRIFIÉ, BUG-1014 VÉRIFIÉ. Le test v6 inversé est valide : il teste toujours « pas de doublon » et le zéro posé par PATCH fige le mois. Reproduit dans v8 avec en plus la carte conservée et le mois suivant non contaminé. Limite : un zéro posé par ORM ou sync est indiscernable d'une porteuse supprimée.
- BUG-1104 VÉRIFIÉ (backend). Les 5 tests adaptés testent toujours l'essentiel. Résiduels : BUG-1028, BUG-1029.
- BUG-1103 REJETÉ (correction incomplète) : BUG-1027 (facturier/livreur) et BUG-1030 (postes locaux).

## Scénarios couverts
Commissions : PATCH identique/autre champ/dette, PUT, drapeau non écrivable ; carte non figée par un PATCH de dette ; carte mise à 0 à la main ; imprimés saisis qui écrasent la carte (limite documentée) ; porteuse payée puis nouvelle ligne (avec et sans dette apparue) ; porteuse supprimée ; période de la porteuse close ; mois suivant ; 3 boulangeries à frais de carte 1000/800/600 ; deux clients ; net négatif (-50 000, mark_paid 400) ; listing de paie et summary (sommes verticales égales ligne par ligne, carte 3 000 sur la première boulangerie, 0 sur la seconde).
Clients : création gérant/facturier/livreur sans node ni taux, taux explicite 0,25 sur 0,30 (REST JSON, nombre, modèle), taux 0 sans commission, changement du taux de la boulangerie (clients et commissions générées inchangés, nouveau client au nouveau taux), transfert de boulangerie, repli sur Config, 3 boulangeries 3 taux, droits et bornes de Node (y compris NaN, Infinity, listes, booléens, chiffres arabes), import Excel (2 boulangeries, réimport après changement), push (sans taux, null, vide, explicite, 0, re-push sans taux, repli Config).
Migration 0025 : relue, correcte, non retestée (3 tests de B-1 couvrent base existante, SIEGE, sans Config, retour arrière).

## Tickets ouverts : 4 (BUG-1027 à BUG-1030)
- BUG-1027 Majeur : `clients/views.py` l.148-154 force le taux 0,25 pour facturier/livreur, donc le taux par boulangerie ne s'applique jamais à leurs clients. 2 tests `@expectedFailure`.
- BUG-1028 Mineur : `card_applied` annoncé exposé par le rapport B-2 mais absent du serializer. 1 test `@expectedFailure`.
- BUG-1029 À CLARIFIER : le montant de carte dépend de l'ordre de génération (et vaut 0 si la première boulangerie générée a `card_fee_fc = 0`). Test de comportement vert.
- BUG-1030 Majeur (sync) : `/api/sync/pull/` ne diffuse aucun paramètre de boulangerie (taux, carte, cotisation, sac). 1 test `@expectedFailure`.

## Observation sans ticket
`Node.default_commission_rate` accepte `1e-1` (= 0,10) : la saisie d'exposant est tolérée ici alors que le parseur partagé de production la refuse. Sans conséquence sur la valeur.
