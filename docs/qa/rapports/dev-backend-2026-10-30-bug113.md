# Rapport dev-backend — BUG-113 (2026-10-30)

## Ticket traité

**BUG-113** (Bloquant) — Fuite inter-nœuds en lecture sur `JournalEntryViewSet.suggested_ca`,
`.monthly_report`, et `.get_queryset()` via `?node=` forgé par un utilisateur non-HQ.

Statut final : `CORRIGÉ` (règle CLAUDE.md §7 : seul testeur-permissions, l'ouvreur du ticket, ou
le coordinateur peut passer à `VÉRIFIÉ`).

## Reproduction confirmée avant correction

Lancé `backend/core/tests/test_permissions.py::JournalSuggestedCaNodeIsolationTests` avant toute
modification : les 2 tests marqués `@unittest.expectedFailure` échouaient bien comme attendu
(confirmé « expected failure », pas de `unexpectedSuccess`), preuve que la faille décrite dans la
fiche BUG-113 était bien reproductible :
- `GET /api/treasury/journal/suggested_ca/?node=<K2>&date=...` par un GERANT K1 renvoyait les
  `total_entries` réels de la `CashClosure` de K2.
- `GET /api/treasury/journal/monthly_report/?node=<K2>&month=...&year=...` par le même GERANT K1
  renvoyait les totaux mensuels réels de K2 au lieu de zéro.

## Correctif appliqué

Fichier modifié : `backend/treasury/views.py` (`JournalEntryViewSet`).

1. **`get_queryset()`** (point annexe confirmé vulnérable, même cause racine) : avant, un
   `?node=` fourni était appliqué sans jamais vérifier `can_access_all_nodes`. Désormais :
   - non-HQ → `node` toujours forcé à `user.node` (ignore tout `?node=` fourni) ; `qs.none()` si
     l'utilisateur n'a aucun nœud.
   - HQ → comportement inchangé, `?node=` du paramètre respecté.
2. **`suggested_ca()`** : non-HQ → `node_id` forcé à `str(request.user.node_id)`, `403
   {"detail": "Aucune boulangerie associée à cet utilisateur."}` si pas de nœud. HQ → paramètre
   `node` respecté tel quel (inchangé).
3. **`monthly_report()`** : même motif exact que `suggested_ca()`.

`perform_create()` n'a pas été touché (déjà conforme, vérifié par testeur-permissions — motif
BUG-022/025/030 correctement appliqué).

Motif repris à l'identique de `ClientViewSet.perform_create`/`perform_update` (BUG-025) et
`ConsumableMovementViewSet`/`SocialContributionViewSet` (BUG-022), comme demandé.

## Tests

Fichier modifié : `backend/core/tests/test_permissions.py` (classe
`JournalSuggestedCaNodeIsolationTests`).

- Décorateur `@unittest.expectedFailure` **retiré** des 2 tests existants (ils passent désormais
  normalement, et non plus comme « échec attendu ») :
  - `test_gerant_k1_cannot_read_suggested_ca_of_another_node_via_forged_node_param`
  - `test_gerant_k1_cannot_read_monthly_report_of_another_node_via_forged_node_param`
- Import `unittest` devenu inutile retiré (plus aucun `@unittest.xxx` dans le fichier).
- 2 tests de non-régression ajoutés :
  - `test_gerant_k1_cannot_list_journal_entries_of_another_node_via_forged_node_param` — preuve
    du point annexe sur `get_queryset()` (liste standard), qui n'était pas couvert par un test
    dédié dans la fiche d'origine.
  - `test_hq_can_still_read_suggested_ca_and_monthly_report_and_list_of_other_node` — vérifie
    qu'un utilisateur HQ (Direction) garde l'accès complet à `?node=<autre boulangerie>` sur les
    3 endpoints (suggested_ca, monthly_report, liste), aucune régression côté HQ.

### Résultats

- `backend/core/tests/test_permissions.py::JournalSuggestedCaNodeIsolationTests` isolé : 4 tests,
  `OK` (0 échec, aucun `expectedFailure` restant — confirmé qu'aucun test ne « réussit de façon
  inattendue » puisque le décorateur a été retiré avant la vérification finale).
- `python manage.py test core treasury` : 156 tests, `OK` — exécuté deux fois (confirmation),
  1474s puis 841s selon la charge machine.
- `python manage.py test` (suite complète) : **391 tests, `OK`, 0 échec**, aucun
  `expectedFailure` restant dans toute la suite.
- `python manage.py makemigrations --check --dry-run` : `No changes detected` — correctif
  purement applicatif, aucune migration nécessaire.
- `PRAGMA integrity_check` sur `backend/db.sqlite3` (lecture seule, aucune donnée modifiée) :
  `ok`.

## Impact sur le contrat d'API

Aucun changement de contrat pour les cas d'usage légitimes (HQ avec `?node=`, ou non-HQ sans
`?node=` forgé) : réponses strictement identiques. Seul le cas d'attaque (`?node=<autre
boulangerie>` envoyé par un non-HQ) change de comportement : il retombe désormais sur le nœud de
l'utilisateur au lieu d'exposer les données financières d'une autre boulangerie (et peut renvoyer
`403` si l'utilisateur n'a aucun nœud, cas qui n'existait pas en pratique auparavant pour un
utilisateur authentifié normal). Le frontend n'a jamais eu de raison légitime d'envoyer un `node`
différent du nœud courant pour un non-HQ sur ces 3 endpoints : **aucun ticket `dev-frontend`
ouvert**.

## Fichiers modifiés

- `backend/treasury/views.py`
- `backend/core/tests/test_permissions.py`
- `docs/qa/REGISTRE_BUGS.md` (fiche BUG-113 → `CORRIGÉ`, section « Correction » ajoutée, note de
  synthèse testeur-permissions annotée d'une mise à jour)
- `docs/qa/rapports/dev-backend-2026-10-30-bug113.md` (ce rapport)

Aucun autre fichier touché (conformément au périmètre demandé).

## Risques / points d'attention pour la vérification

- Le correctif de `get_queryset()` a été élargi au-delà du périmètre strictement décrit dans la
  demande initiale (qui ne mentionnait que `suggested_ca`/`monthly_report` comme correctif
  obligatoire), car le point annexe a été confirmé vulnérable par la reproduction. À valider par
  testeur-permissions que ce périmètre élargi est bien celui attendu.
- Aucune contradiction entre documents de référence rencontrée — correctif purement RBAC
  (CLAUDE.md §4), pas de règle métier ambiguë.
- Suite complète lente (~22 min) sur cette machine (génération de schéma OpenAPI répétée par
  test, déjà connu/sans rapport avec ce ticket) — purement environnemental, aucun test flaky
  observé, 0 échec sur 391 tests à deux reprises pour le sous-ensemble core+treasury.
