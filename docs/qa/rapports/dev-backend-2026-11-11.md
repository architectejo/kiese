# Rapport dev-backend — 2026-11-11

## BUG-161 / B1 — `workday.py` + `Node.handover_time` (CORRIGÉ pour l'étape B1 ; BUG-161 reste ouvert)

- Fichiers : `backend/core/models.py` (champ `handover_time`, défaut 12:00), `backend/core/migrations/0017_node_handover_time.py` (AddField seul, non appliquée sur `db.sqlite3`), `backend/core/serializers.py` (`handover_time` dans `NodeSerializer`), `backend/core/workday.py` (nouveau : `business_date`, `workday_bounds`, `next_handover`), `backend/core/tests/test_bug161_workday.py`.
- Fuseau : `TIME_ZONE='Africa/Kinshasa'`, `USE_TZ=True` ; calculs via `timezone.localtime` / `make_aware`.
- Anciens champs `team_a/b_*`, `active_team_at()`, `opening_team()` inchangés. Aucune logique production/sales/treasury touchée.
- Permissions inchangées : lecture authentifiée, écriture `IsDirection` ; `null`/heure invalide -> 400.
- Risque : `workday_bounds` suppose une journée de 24 h (exact pour Kinshasa, pas de changement d'heure).
- Suites : `test core` OK (130) ; suite complète 671 tests : 2 erreurs de migration (`clients.tests.test_migration_social_uuid*`, NOT NULL sur `handover_time`) corrigées en ajoutant `db_default=12:00` (migration 0017 régénérée, jamais appliquée), ces 2 tests + tests BUG-161/BUG-130 relancés OK ; `makemigrations --check` propre. La suite complète n'a pas été relancée après le `db_default` (~48 min sous charge).


## BUG-172 / BUG-176 (volet backend) - tri déterministe des listes paginées

- Cause : `ordering` non unique + LIMIT/OFFSET (non déterministe sur PostgreSQL).
- Fichiers : `backend/kiese/pagination.py` (nouveau), `backend/kiese/settings.py` (pagination par défaut), `backend/commissions/views.py`, `backend/treasury/views.py` (ordering + `pk`), test `backend/commissions/tests/test_bug172_deterministic_ordering.py`.
- Garantie globale par le paginateur (pk en dernier critère, y compris `?ordering=`), ordre primaire inchangé (livre de caisse : `-date, -created_at, -pk`).
- Migrations créées : aucune. Contrat d'API inchangé.
- Risque : endpoints non paginés (`@action` listes complètes) non concernés ; le tri par UUID est arbitraire mais stable.
