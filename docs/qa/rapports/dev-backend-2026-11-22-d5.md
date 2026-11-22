# Rapport dev-backend (Dev B) - 2026-11-22, session D5

Périmètre : BUG-737 à BUG-746 (tickets du testeur clients/commissions, ronde v2).

## Tickets passés à CORRIGÉ (8)

| Ticket | Cause | Correctif | Fichiers |
|---|---|---|---|
| BUG-737 | `generate` reprenait la BP et la cotisation entières sur chaque ligne d'un client facturé dans 2 boulangeries | Règle retenue : la première paie générée du mois retient BP et cotisation ; les lignes suivantes du même client/mois reçoivent 0 (modifiables à la main). La carte reste par boulangerie. À valider avec le client | commissions/views.py |
| BUG-739 | `bulk_create_month` sans validation | node (parse_node_param + existence), month 1..12, year 2000..2100, amount Decimal fini 0..99 999 999,99 ; 400 en français | clients/views.py |
| BUG-740 | indice/mérite sans bornes | indice 0..12, mérite >= 0, total_social >= 0 | clients/serializers.py |
| BUG-741 | ids/node invalides = 500, `bulk_move` non atomique | ids = liste d'UUID, node via parse_node_param, `transaction.atomic()` | clients/views.py |
| BUG-743 | LIKE/lower() SQLite ASCII seulement | fonction SQL `KIESE_FOLD` (minuscule sans accents) enregistrée à la connexion SQLite, `AccentInsensitiveSearchFilter` et classement par pertinence repliés. Autres moteurs inchangés | clients/search.py (nouveau), clients/apps.py, clients/views.py |
| BUG-744 | `period` non UUID = 500 | validation UUID, 400 | commissions/views.py |
| BUG-745 | `set_manuel` NaN/Infinity/trop grand = 500 + valeur empoisonnée | refus (400) si non fini, bool/liste ou >= 10^12 ; quantize 0,01 avant calcul | commissions/views.py |
| BUG-746 | noms > 100 caractères, doublons NFC/NFD | normalisation NFC (stockage + doublons), noms trop longs non importés et listés dans le rapport (`invalid`, `invalid_names`) | clients/imports.py, clients/views.py |

Tests : les `@expectedFailure` des tests correspondants ont été retirés (ClientMultiBoulangerieTests x2, ParametresInvalidesTests x2, RechercheTests, BulkTests x2, ImportTests x2, CaisseSocialeTests x2).

## Tickets passés à À CLARIFIER (non codés, sur consigne)
- BUG-738 : CM au taux du reçu (par facture) ou au taux courant du client ?
- BUG-742 : un client à plafond 0 FC sans dette est-il « à risque » ?
Leurs tests restent `@expectedFailure`.

## Contrats d'API modifiés (impact frontend à signaler)
- `import_excel` : le rapport par boulangerie gagne `invalid` et `invalid_names` (ajout, rétro-compatible).
- `bulk_move` : « Boulangerie introuvable » est renvoyé sous la clé `detail` (avant : `node`).
- Nouvelles validations 400 (bulk_create_month, lignes de distribution, set_manuel, payroll_listing).
- Aucune migration.

## Risques / points à valider
- BUG-737 dépend de l'ordre de génération des paies (la première retient). Alternative (rattachement ou plus grande part) possible si le client la préfère.
- Mérite >= 0 et indice <= 12 : hypothèses à confirmer avec le client.
- BUG-743 : repli casse/accents uniquement sous SQLite ; sur PostgreSQL les accents restent significatifs (hors périmètre).
- Aucun ticket passé à VÉRIFIÉ ; rien commité ni poussé.
