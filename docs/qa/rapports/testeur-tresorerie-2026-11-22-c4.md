# Testeur Trésorerie (Dev C) — cycle 3, 2026-11-22 (c4)

Branche dev-c (206b87a). Tests : `backend/treasury/tests/test_cycle3_tresorerie_c.py` (27 tests : 19 verts, 8 `@expectedFailure`).
Exécution : `treasury` + `blockchain` complets (519 tests) via un urlconf temporaire sans `finance`
(`finance/views.py` ne compile pas pendant la session : édition en cours par un autre agent, ligne 181).
Seul échec hors périmètre : `test_528_finance` (conséquence de cet urlconf).

## Vérifications
| Ticket | Verdict | Nouveaux angles |
|---|---|---|
| BUG-810 | **ROUVERT** | POST propre (12 valeurs x 6 routes, multipart) ; `PATCH reports/<id>/ {"node": true}` déplace le rapport sur le nœud 1 |
| BUG-815 | VÉRIFIÉ | épargne nœud/date, clôture, PATCH sur soi-même ; même défaut côté rapports : BUG-841 |
| BUG-818 | VÉRIFIÉ | 8 valeurs x 10 routes x 3 paramètres, generate, corps de POST |
| BUG-830, 831, 832, 833, 835, 836, 837, 838, 839 | VÉRIFIÉ | voir fiches (réserves : 840 à 846) |
| BUG-834 | VÉRIFIÉ | épargne, bon, comptage propres ; journal : BUG-847 |

## Nouveaux tickets
- BUG-840 (Majeur) `reports/generate/` sur jour de clôture confirmée : versement 4 500 FC au lieu de 1 500 FC confirmés.
- BUG-841 (Mineur) PATCH de date d'un rapport vers un jour existant -> 500.
- BUG-842 (Mineur) `integrity_check` (GET) : 1 notification DANGER par appel.
- BUG-843 (Mineur) `global_status` « intact » avec boulangeries non vérifiées.
- BUG-844 (Mineur) `log_activity` manquant (suppression rapport, épargne, journal non-CA).
- BUG-845 (Mineur) N+1 `global_status` (15 -> 27 requêtes).
- BUG-846 (Mineur, frontend) `Blockchain.tsx` affiche « COMPROMIS » sur base jamais vérifiée.
- BUG-847 (Mineur) journal : dépassement du solde progressif -> 500.
