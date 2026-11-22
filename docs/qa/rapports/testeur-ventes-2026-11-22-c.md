# Testeur Ventes (Dev C) - vérification BUG-366 - 2026-11-22

## Verdict
BUG-366 : **VÉRIFIÉ** (testeur-ventes, Dev C), réserve « PostgreSQL non testé » (SQLite uniquement). Registre édité.

## Tests (backend/sales/tests/test_verif_bug366_c.py, MigrationExecutor, TransactionTestCase)
Les données sont créées à l'état courant, retour à 0010, aller 0011 puis 0012, comparaison avant/après.
- Chaîne 0010 -> 0011 -> 0012 : après 0011 seule, colonne vide ; après 0012 : normale 300->300, soldée 225->300, non reconstituable 151->201 (écart <= 1 FC), prix 0 -> 0. `unit_price`, `line_total`, quantités, `order_total`, `payment_amount`, `current_debt`, somme des totaux : identiques avant/après.
- Lots multiples (BATCH=3, 7 soldées + 3 normales).
- Ancienne 0011 déjà appliquée (colonne remplie 555/888) : 0012 ne touche pas ces lignes, remplit les vides.
- Interruption (échec simulé au 4e UPDATE) : lots déjà validés conservés, relance termine, invariants intacts.
- Idempotence (double exécution). Reverse 0011 puis 0010 sans perte (sommes identiques) ; retour 0011 conserve la colonne remplie (0012 inversée = noop).
- Capture du SQL ; `makemigrations --check` propre ; 0011 = un seul AddField nullable ; 0012 `atomic=False`, réversible, dépend de 0011.
- Note : « ligne sans unit_price » = `unit_price` 0 (colonne non nulle, défaut 0).

Résultat : `manage.py test sales.tests.test_verif_bug366_c sales.tests.test_migration_0012_full_unit_price sales.tests.test_verif_bug508_363_testeur_ventes` : 19 tests OK.

Références : aucun autre fichier (production/migrations, sync) ne référence 0011/0012 ; seuls `production/views.py`, `sales/models.py` et des tests utilisent `full_unit_price` (usage du champ, pas du contenu de la migration).

## Évaluation du SQL (non testable ici : PostgreSQL absent)
UPDATE des ventes normales généré :
`UPDATE sales_invoiceline SET full_unit_price = unit_price WHERE id IN (SELECT U0.id FROM sales_invoiceline U0 INNER JOIN sales_invoice U1 ON U0.invoice_id = U1.id WHERE U0.full_unit_price IS NULL AND NOT U1.is_soldee)`
- Un seul UPDATE en une transaction (autocommit, 0012 non atomique) : verrou ROW EXCLUSIVE (les lectures et écritures concurrentes passent), verrous de ligne sur toutes les lignes mises à jour ; une écriture concurrente sur une même ligne attend la fin de l'UPDATE. Plus d'ACCESS EXCLUSIVE (AddField nullable sans défaut, instantané sur PostgreSQL 11+).
- Coût : un seul UPDATE crée une version de ligne par ligne (bloat, WAL proportionnel) ; la sous-requête `IN` est normalement planifiée en semi-join (hash), acceptable ; une transaction longue retient le vacuum sur ~10^5 lignes (secondes). Le risque réel n'est pas le verrou de table mais la durée de la transaction unique et le bloat.
- Pas de lot sur les ventes normales : si le volume dépasse ~10^6 lignes, envisager le même découpage par plages de pk.

Mesure proposée sur une copie de la base cloud : (1) `EXPLAIN (ANALYZE, BUFFERS)` de l'UPDATE dans une transaction annulée (ROLLBACK) ; (2) chronométrer `migrate sales` complet ; (3) pendant l'exécution, lancer des INSERT/UPDATE de facture depuis une autre session et relever `pg_stat_activity`/`pg_locks` (attentes) ; (4) comparer `pg_relation_size('sales_invoiceline')` avant/après (bloat) et `VACUUM` ; (5) valider par un décompte `full_unit_price IS NULL` = 0.

## Tickets ouverts
Aucun nouveau défaut. Seul état modifié : BUG-366 -> VÉRIFIÉ.
