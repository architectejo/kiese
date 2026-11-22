# Testeur Clients et Commissions - 2026-11-22, ronde b3

Périmètre : vérification indépendante de BUG-737 à 746 (corrigés par Dev B, session D5) et attaque des correctifs.
Nouveaux fichiers de tests (aucun code applicatif modifié, données fictives) :
- `backend/clients/tests/test_clients_v3.py` (33 tests)
- `backend/commissions/tests/test_commissions_v3.py` (34 tests)

## Verdicts

| Ticket | Verdict | Preuve |
|---|---|---|
| BUG-737 | VÉRIFIÉ | 3 boulangeries (une seule retenue 10 000 / 1 500), ordre inversé, régénération x4, mois et années distincts, ligne retenante déjà payée, période de l'autre boulangerie clôturée, BP créditrice, nouvelle facture après génération, totaux `summary` |
| BUG-738 | À CLARIFIER (inchangé) | |
| BUG-739 | VÉRIFIÉ | bornes exactes mois 1/12, année 2000/2100, montant 99 999 999,99 ; bool, float, liste, NaN, Infinity, 1E999999999 = 400 |
| BUG-740 | VÉRIFIÉ | indice 0 et 12 acceptés, 13 / 12.5 / abc refusés ; mérite et total négatifs, NaN refusés |
| BUG-741 | VÉRIFIÉ | ids et node invalides = 400, UUID majuscules/sans tirets acceptés, lot atomique prouvé par panne simulée au 2e client, clés du rapport inchangées |
| BUG-742 | À CLARIFIER (inchangé) | |
| BUG-743 | VÉRIFIÉ | KIESE_FOLD : NULL, injection inerte, `%` et `_` échappés, NFC/NFD, ß, Ñ, 5 000 caractères, emoji, tri par pertinence accentué, isolation du gérant |
| BUG-744 | VÉRIFIÉ | formats UUID valides acceptés, invalides = 400, inconnu = 200 [] |
| BUG-745 | ROUVERT | `manuel_adjustment='1E999999999'` donne encore 500 (voir ci-dessous) |
| BUG-746 | VÉRIFIÉ | 100 caractères pile acceptés (prénom et nom), 101 refusés et listés, NFD de 200 points de code = 100 caractères NFC accepté, doublons NFC/NFD/casse y compris contre un client en base en NFD, dry-run identique au réel, total = importés + existants + invalides |

## Nouveaux tickets (4)

- **BUG-747** (Mineur) : lignes de distribution sociale, dépassement de colonne `max_digits=10` = 500 (somme `total_social` + `merite` valides chacun, ou gros tarif x indice 12).
- **BUG-748** (Mineur) : `bulk_create_month` avec `amount='0'` est traité comme absent (tarif par défaut appliqué). À confirmer côté métier.
- **BUG-749** (Mineur) : `set_manuel` sans le champ `manuel_adjustment` efface l'ajustement manuel existant (perte silencieuse de la décision de la Direction).
- **BUG-750** (Mineur) : `set_manuel` avec `manuel_notes=null` = 500.

Rouvert : **BUG-745** (`decimal.Overflow` de `abs()` non intercepté, 500 sur exposants gigantesques ; correctif d'une ligne).

Déjà ouverts par d'autres agents et recoupés par mes tests (non dupliqués) : BUG-782 (course entre deux générations), BUG-783 (suppression de la ligne qui retient puis régénération : BP retenue nulle part).

## Observations sans ticket
- `set_manuel` arrondit avec `quantize` en `ROUND_HALF_EVEN` : 0,005 devient 0,00 et 0,015 devient 0,02. Même chose pour `deduction_remise` (`round`). Sans enjeu en FC, à signaler si le client veut un arrondi commercial.
- `summary` renvoie des sommes sans décimales (`12500`) alors que les champs de ligne sont `12500.00` (artefact des agrégats SQLite) : le frontend doit tolérer les deux.
- `Decimal` accepte les chiffres Unicode (`١٢` = 12) dans `set_manuel` : inoffensif.
- Règle BUG-737 : la ligne qui retient dépend de l'ordre de génération (déjà signalé par Dev B comme à valider avec le client).
- Fausse alerte écartée : la recherche `'` seule renvoie tout (DRF retire les guillemets des termes), comportement du framework.

## Résultats
- Premier passage des deux fichiers : 67 tests, 8 expectedFailure (BUG-745, 747 x2, 748, 749, 750, 783 plus un test BUG-748 inchangé), 1 succès inattendu corrigé (1E999999999 en `bulk_create_month` est bien refusé : pas un défaut).
- Dernière commande : `manage.py test clients commissions` (résultat ci-dessous).

`manage.py test clients commissions` : **462 tests, OK, 12 expected failures** (7 de cette ronde : BUG-745, 747 x2, 748, 749, 750, 783 ; 5 antérieurs : BUG-738, 742 et autres tickets ouverts), 0 échec, 0 succès inattendu, 1997 s. Perf recherche facturier sur 5 000 clients : 161 ms.
