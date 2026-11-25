# Rapport de tests — dev-a (2026-11-25)

Ordre du responsable : série de tests de dev-a ; répartition dans `docs/COMMUNICATION_A_B.md` (#51-A). Rapport en cours de rédaction : complété au fil des résultats.

## 1. Version testée
Branche `dev-a`, base `5e12db5` (fusion de `dev-b` `50623ad` + BUG-1300 + BUG-1302).

## 2. Tests automatisés (backend, base SQLite isolée, `KIESE_TEST_CLOCK_SHIFT=1`)

| Groupe | Résultat |
|---|---|
| `core clients commissions sync chat` | Ran 2 298 — FAILED (failures=3, errors=28) : 30 dus à BUG-1302 (outil de test, corrigé), 1 concurrence SQLite à rejouer seul |
| `production` | Ran 1 731 — **OK** (expected failures=5) |
| `sales treasury finance blockchain` | en cours |

## 3. Tickets
- BUG-1300 (fausse alerte Q-021) : CORRIGÉ, à vérifier par dev-b.
- BUG-1301 (verrou de vente sans clôture la veille) : À CLARIFIER (client).
- BUG-1302 (runner de test / throttle DRF) : CORRIGÉ, à vérifier par dev-b.

## 4. Parcours Chrome
À venir (après la fin de la série, pour ne pas saturer la machine).
