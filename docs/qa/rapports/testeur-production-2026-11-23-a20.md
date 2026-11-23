# Testeur production : cycle 21 partie A (a20), 2026-11-23

Fichier de tests : `backend/production/tests/test_verif_production_a20_v20.py` (25 tests, OK, 5 `@expectedFailure`). Log : `$TEMP/a20.log`.

## Vérifiés
- BUG-1015 à 1020 : matrice de 47 formes entières et 38 formes décimales, oracle écrit indépendamment du code (regex ASCII, espaces ASCII seuls, bool/null/exposants/underscores/non-ASCII/NaN refusés, 32 caractères max), REST et push sur toutes les entrées de quantité de production. Verdicts identiques à l'oracle, aucun 500. Seuls écarts : BUG-1031 (zéros finaux).
- BUG-1021 (production) : litige sans ligne, écart d'entête (100/98, 100/null, 100/0, 98/100) jamais levé par un push, ni par K1 ni par K2 ; 100/100 levé ; un enregistrement portant une autre quantité ne contourne rien ; avec lignes le comportement BUG-966 est inchangé. Voir toutefois BUG-1035.
- BUG-1022 : les 3 tests adaptés testent toujours l'essentiel (retenue sociale déjà posée figée après changement de boulangerie ; bornes farine ; bornes ENTRY/exposant). Séries a9, a11 et commissions vertes.

## Réponses aux points d'attention
- `unit_price` à contrôle historique : incohérence réelle (BUG-1033) : `1_0` et `1e1` acceptés comme prix (REST et push), refusés comme quantité. Et `-5` accepté en REST, refusé au push (BUG-1032).
- Poste ancien exportant `""` pour les sacs : rejet acceptable. REST répond aussi 400, la raison renvoyée cite `flour_sacks_used`, rien n'est créé. Une clé absente reste acceptée.
- ENTRY négative sans notification de stock négatif : défaut Mineur (BUG-1034).
- Tolérances notées, sans ticket : la virgule décimale (`1,5`) est acceptée au dispatch et à l'inventaire seulement ; `consumables_used` arrondit `0.0004` à 3 décimales (historique BUG-219) ; `quantity_received: null` au push = ligne non reçue.

## Nouveaux tickets : 5 (tous Mineur)
BUG-1031 (zéros finaux REST/push), BUG-1032 (prix négatif), BUG-1033 (prix `1_0`/`1e1`), BUG-1034 (pas d'alerte ENTRY négative), BUG-1035 (litige sans ligne ne bloque pas la clôture). Numéros 1023 à 1030 déjà pris par d'autres testeurs.

Ce n'est donc pas un cycle propre.
