# Rapport dev-backend (Dev B) - d55 - 2026-11-23

## Tickets traites : BUG-1015, 1016, 1017, 1018, 1019 -> CORRIGE

Cause commune : validations numeriques ajoutees ticket par ticket, divergentes (`str.strip()` Python retire NBSP, `int('1_0')`,
`or 0` sur null, minimum 0 au push...).

### Correction : un seul parseur
`backend/core/numeric.py` : `parse_ascii_int(value, *, minimum, maximum, allow_negative, label)` et
`parse_ascii_decimal(value, *, places, minimum, maximum, max_digits, label)` (leve `NumericError(ValueError)`, attribut `reason`).
Regle canonique du coordinateur : int (pas bool), float entier, Decimal fini, chaine ASCII apres `strip()` des seuls espaces ASCII,
`[-+]?[0-9]+(\.0+)?` (entier) / `[-+]?[0-9]+(\.[0-9]+)?` (decimal) ; refus bool, None, exposants, `_`, non ASCII, espaces non ASCII,
liste/dict, decimale non nulle pour un entier, vide ou > 32 car., NaN/Infinity.

Branche sur :
- REST : `production/views.py` (`_strict_int`, `_bounded_integral_decimal`, regex opening-confirmation supprimee, `_strict_pk`
  espaces ASCII, `consumables_used`), `production/serializers.py` (ligne de fournee, disposition, mouvement, comptage,
  `flour_sacks_used`), `production/consumables_direction.py::parse_qty` (virgule decimale toujours toleree).
- Push : `sync/services.py` : nouveaux `_prod_int`/`_prod_decimal` (production uniquement ; `_sync_int`/`_sync_decimal` laisses
  aux autres modules), `_sync_bounded_qty`, `_strict_decimal` (comptages), `_bread_price_or_none`, handlers/checks de session,
  ligne de fournee, disposition, transfert + ligne, mouvement.
- 1017 : null/vide refuse au push pour `quantity` (disposition), `quantity_sent` (ligne de transfert), `flour_sacks_used`.
- 1019 : push accepte negatif/nul pour une SORTIE de consommable (bornes de magnitude conservees) ; comptages/inventaires >= 0.
- 1015 (parite `-0`/`+0`) : REST `send`/demande exige >= 1 pain (tests existants test_vague1 / test_transfert_envoi_direct_a /
  core c5) ; le push refuse donc une NOUVELLE ligne a 0 pour un transfert PENDING/RESPONDED (la reponse du fournisseur, qui met a
  jour une ligne existante, peut toujours ramener a 0).
- Tests : `@expectedFailure` et import retires dans `A19Defects` (`test_verif_production_a19_v19.py`), assertions inchangees.

## Valeurs de tests existants en tension avec la regle canonique
- **BUG-907 (a8_v8 `test_BUG_907_negative_entry_refused_and_stock_untouched`)** : exige que le push refuse `ENTRY -5`, alors que
  REST accepte les mouvements negatifs (BUG-216) et que 1019 demande d'aligner. Regle la plus stricte compatible appliquee :
  le push accepte le negatif pour EXIT seulement ; **ENTRY negative reste refusee au push (ecart residuel avec REST)**.
  A trancher par le coordinateur (si l'alignement total est voulu, adapter le test BUG-907).
- Aucun autre test BUG-686/687/688/896/902/903/906/1012/1017/317/322 n'a du etre modifie.

## Resultats REELS (logs `$TEMP/d55.log` et `$TEMP/d55b.log`)
- Passe 1 : a19 + a18 + a17 + a16 + a15 + a8 : 125 tests, 1 echec (BUG-907 ci-dessus, avant ajustement EXIT-seul), 1 x attendu.
- Passe 2 (apres ajustement) : a19 + a8 + a7 + a6 + test_dev_d13_bugs_652_654_626 + test_verif_bug317 + test_verif_bug319_322 +
  test_vague1_db_production_2026_11_12 + sync.tests.test_verif_sync_v5 : **211 tests OK (1 expected failure preexistant)**.
- a18/a17/a16/a15 n'ont pas ete rejoues apres l'ajustement EXIT-seul (qui ne touche que `_check_consumable_movement` pour les
  quantites negatives) : ils etaient verts en passe 1.
- `makemigrations --check --dry-run` : No changes detected. Suite complete `manage.py test` non lancee (hors consigne).

## Risques
- Les chaines vides/`null` pour les sacs de farine d'une session poussee sont maintenant rejetees : un poste ancien qui exporte `""`
  verrait la fournee rejetee (motif explicite).
- `parse_qty` et le parseur refusent desormais les nombres de plus de 28 chiffres significatifs (message « invalide » au lieu de
  « trop grande »).
- `unit_price` (mouvements) conserve son controle historique (non ASCII) ; seule la quantite suit la regle canonique.
- Fichiers a fins de ligne CRLF preserves ; les modifications `backend/commissions/` ne sont pas de mon fait.
