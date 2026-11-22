# Rapport dev-backend, 2026-11-22 (c10)

Tickets passés à CORRIGÉ : BUG-810 (rouvert 2), 840, 841, 842, 843, 844, 845, 847 (backend) et BUG-846 (frontend, fait à la demande du coordinateur).

| Ticket | Correction | Fichier |
|---|---|---|
| 810 | PATCH `node` d'un rapport passé à `_body_node` (bool/float/illisible -> 400) | treasury/views.py |
| 840 | `generate` refusé (400) un jour de clôture confirmée | treasury/views.py |
| 841 | unicité (node, facturier, team, date) contrôlée au PATCH -> 400 | treasury/views.py |
| 842 | `integrity_check` : notification seulement à la première détection (`is_tampered`), « livre amputé » dédupliqué | treasury/views.py |
| 843 | `all_intact` faux tant qu'un nœud n'est pas vérifié ; champ `unchecked_nodes` ajouté | blockchain/views.py |
| 844 | `log_activity` : suppression de rapport, épargne (création/modification), journal hors CA | treasury/views.py |
| 845 | `global_status` en 4 requêtes constantes | blockchain/views.py |
| 847 | solde progressif (écriture + suivantes) borné dans la transaction -> 400 | treasury/views.py |
| 846 | « JAMAIS VÉRIFIÉ » / « VÉRIFICATION PARTIELLE » distincts de « COMPROMIS » | frontend/src/pages/dashboard/Blockchain.tsx |

Tests de non-régression : `backend/treasury/tests/test_bug840_847.py` (8 tests, passent).
Suite `manage.py test treasury blockchain --noinput` : 528 tests, 1 échec (mon test 845 avant ajout de l'appel de chauffe, corrigé depuis ; relancé : 8/8 OK), `check` et `makemigrations --check` propres. `npx tsc --noEmit` et `npm run build` OK.

## Marques `@expectedFailure` à retirer (test_cycle3_tresorerie_c.py)
Passent désormais (« unexpected success ») : `test_BUG_810_report_patch_node_bool_float_moves_report`, `test_BUG_841_...`, `test_BUG_840_...`, `test_BUG_847_...`, `test_BUG_842_...`, `test_BUG_843_...`, `test_BUG_844_...`.

## Point de vigilance : `test_BUG_845_global_status_n_plus_one`
Reste en échec attendu, à tort : il mesure le PREMIER appel de l'API, qui crée la `Config` singleton (+ log + notification) = 10 requêtes, contre 4 aux appels suivants. Le N+1 est supprimé (4 requêtes à 3 comme à 12 nœuds). Le testeur doit ajouter un appel de chauffe avant la première mesure (comme dans `Bug845`). Je ne modifie pas son test.

## Impact API
`GET blockchain/snapshots/global_status/` : nouveau champ `unchecked_nodes: string[]` ; `all_intact` est faux si un nœud n'a jamais été vérifié. Journal : 400 {"detail"} si solde hors plage.

## Risques
- 840 : un gérant ne peut plus régénérer les rapports d'un jour confirmé (voulu) ; la correction de livraison rétroactive (BUG-083) passe par le service, non concerné.
- 842 : un `is_tampered` posé par un contrôle antérieur supprime les notifications suivantes (une alerte `TamperAlert` reste visible via run_check).
- `finance/views.py` non touché.
