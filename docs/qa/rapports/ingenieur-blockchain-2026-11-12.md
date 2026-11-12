# Rapport ingenieur-blockchain, 2026-11-12 : BUG-198 et BUG-199

## BUG-198 (CORRIGÉ)
- `treasury/views.py::CashClosureViewSet.destroy` : 403 en français si la clôture est confirmée (`is_validated`) ou liée à une écriture du livre ; sinon suppression permise au gérant de son nœud / rôles siège, journalisée (`log_activity`).
- `treasury/models.py` : `CashbookEntry.source_closure` en `PROTECT` (cascade impossible). `core/reset.py` supprime déjà `cashbook_entries` avant `cash_closures` : remise à zéro inchangée.

## BUG-199 (CORRIGÉ)
Cause : chaînage = ordre d'insertion, tri de référence = `(date, created_at)`.
Correction : `CashbookEntry.chain_seq` (BigInteger, null, unique, hors hash), attribué dans `CashbookEntry.save()` (max+1) à l'intérieur de la transaction d'`append_cashbook_entry` ; l'unicité de `chain_seq` et de `previous_hash` rejette toute fourche (retry existant). Ordre unique `chain_order()` / `chain_order_desc()` (nulls = plus anciens) utilisé par `_get_last_balance`, `integrity_check`, `blockchain/views.py::_verify_full_chain` (`run_check`) et `finance/views.py` (solde de clôture). Formule de hash inchangée (HASH_FORMAT_VERSION = 3).

## Migration (créée, NON appliquée)
`treasury/migrations/0016_bug198_199_chain_seq_protect_closure.py` : AddField `chain_seq`, RunPython de backfill (réversible, journalisé via logger `treasury.migrations`), AlterField `source_closure` PROTECT.
Procédure de déploiement : sauvegarder la base, `python manage.py migrate treasury`, puis `integrity_check` et `run_check` : verdict inchangé par rapport à avant migration. Le backfill suit `previous_hash` depuis le génésis (les migrations 0007/0014 ont déjà réécrit la chaîne dans l'ordre date/created_at, donc l'ordre stocké est celui-là) ; les écritures non rattachables (chaîne déjà rompue) passent en fin dans l'ordre `(date, created_at, pk)`. Aucun hash n'est modifié.

## Tests
`treasury/tests/test_bug198_199.py` (8 tests) ; `@expectedFailure` retirés de `ClosureDeleteProbe` et `OutOfOrderPushProbe`. Voir le registre pour le statut (CORRIGÉ, vérification par testeur-tresorerie).
Points d'attention : les tests existants qui trient par `('date','created_at')` restent valides tant que les dates sont croissantes dans l'ordre d'ajout.
