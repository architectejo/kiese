# Rapport dev-backend (Dev B) — 2026-11-22-b

## Ticket traité
BUG-521 (Bloquant) — `deficit_report` non filtré par boulangerie : CORRIGÉ.

## Cause
`clients/views.py::deficit_report` (`IsAuthenticated`) ne filtrait ni la période ni les commissions par nœud ; `?node=` était passé tel quel au filtre (ValueError -> 500).

## Correction
- Permission `IsGerant` (ADMIN, DIRECTION, COMPTABLE, GERANT) : minimum sûr, aligné BUG-253. Facturier/livreur -> 403. **Choix à confirmer** (ambiguïté de rôles).
- Compte sans boulangerie non siège : `[]` (`is_node_less_non_hq`).
- Non-siège : borné à `user.node` ; `?node=` ignoré (convention du dépôt).
- Siège : `?node=` entier validé, sinon 400 `{"detail": "..."}` en français.

## Tests
- Nouveau : `backend/clients/tests/test_bug521_deficit_report_isolation.py` (5 tests).
- `backend/core/tests/test_verif_isolation_a_c.py::DeficitReportLeak` : `@expectedFailure` retirés ; attente facturier/livreur modifiée de 200 à 403 (conséquence du choix de permission, pas un affaiblissement d'isolation).
- Exécution ciblée (2 modules) : 44 tests OK (2 expected failures = BUG-522, sans rapport).
- `clients` seul : 131 tests OK. `clients core` (667 tests, avant retrait du dernier `@expectedFailure`) : seul incident = « unexpected success » de `test_node_param_non_numeric_is_not_a_500`, résolu par le retrait de la marque ; module re-testé ensuite : OK. Des exécutions lancées en parallèle ont montré des échecs transitoires (contention), absents en exécution isolée.

## Risques / à signaler
- Frontend : `ClientsKpiGrid.tsx` appelle la route pour tous les rôles ; facturier/livreur reçoivent 403 (erreur ignorée, carte « — »). Ticket frontend facultatif pour masquer la carte.
- Pas de commit, pas de push.
