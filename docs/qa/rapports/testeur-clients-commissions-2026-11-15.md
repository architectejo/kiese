# Rapport testeur-clients-commissions — 2026-11-15

Vérification indépendante des tickets CORRIGÉ BUG-289, 291, 292, 293, 295 (aucun code applicatif modifié ; base isolée via `DB_NAME`, `backend/db.sqlite3` non touché ; venv `backend\.venv`).

## Tests ajoutés
`backend/clients/tests/test_verif_bug289_295_2026_11_15.py` (9 tests, valeurs calculées à la main en Decimal, écrits sans reprendre les fixtures des tests du dev).

| Ticket | Preuve (calcul à la main) | Résultat |
|---|---|---|
| 289 | Node 2 000 FC : retenue sociale 2 000 ; cotisation client NULL suit la boulangerie, 0 explicite prévaut ; boulangerie à 0 : aucune cotisation créée (`bulk_create_month`) ; régénération après changement de la boulangerie ne modifie pas la commission existante | VÉRIFIÉ |
| 291 | CM 5 000, carte = 0, net_carte = net_ordi, remise non déduite | VÉRIFIÉ |
| 292 | remise = commande × 0,0025 : 20 000 -> 50 ; 10 000 -> 25 ; taux 0,30 : CM 3 000 | VÉRIFIÉ |
| 293 | BP −1 500 : deduction_debt −1 500, net_ordi 5 000 + 1 500 = 6 500, net 6 500 − 2 000 = 4 500 ; dette +1 000, CM 3 000 : net 2 000 | VÉRIFIÉ |
| 295 | annual_bonus 0 même avec le flag « incorporée » (net 2 500) ; refresh_indices : 10 mois payés (le 11e impayé exclu) : 10 × 700 = 7 000, total 30 000 + 7 000 + 1 500 = 38 500 ; tarif 600 : 6 000 / 37 500 ; 11 mois : 6 600 / 41 100 ; tarif d'une distribution clôturée refusé (400), refresh refusé (400), lignes figées ; facturier et gérant d'une autre boulangerie refusés | VÉRIFIÉ |
| Migration `clients/0010` | Avant : 3 000 -> NULL, 1 500 et 0 conservés ; retour arrière : NULL -> 3 000 ; commission préexistante (social 3 000, net 777, annual_bonus 611, carte 37) strictement inchangée dans les deux sens ; `makemigrations --check` : aucun changement | OK |

## Exécutions (DB_NAME isolé)
- Fichier de vérification : 9 tests OK.
- `manage.py test clients commissions` : 161 tests, OK.
- `makemigrations --check --dry-run` : No changes detected.

## Tickets
- Passés à VÉRIFIÉ : BUG-289, 291, 292, 293, 295 (note ajoutée dans `docs/qa/REGISTRE_BUGS.md`). Aucun rouvert.
- Non traités ici : BUG-290 (ventes, testeur-ventes), BUG-301 (frontend, ouvert), BUG-285/294/296 (À CLARIFIER).

## Réserves (non bloquantes, déjà signalées par le dev)
1. 0010 : un client volontairement personnalisé à 3 000 FC devient NULL (suit la boulangerie) ; irréversible à l'identique pour ce cas. Question client.
2. Commissions déjà générées : conservent annual_bonus/remise/net d'avant tant qu'elles ne sont pas régénérées ; la régénération d'une commission existante ne les rafraîchit pas (vérifié) : des périodes ouvertes générées avant correction gardent l'ancienne remise (0,1 %) et la carte, à purger/régénérer par la direction si souhaité.
3. TARIF par défaut 700 FC à la création d'une distribution (valeur K2 2023) ; à saisir par la direction.
