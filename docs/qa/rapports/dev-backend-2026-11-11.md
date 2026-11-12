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


## BUG-161 / B2 — `DailyTeamAssignment`, API de désignation, blocage de la facturation (CORRIGÉ pour l'étape B2 ; BUG-161 reste ouvert)

- Fichiers : `backend/production/models.py` (+ migration `production/0023_bug161_b2_team_assignment.py`), `backend/production/views.py` + `urls.py` (`TeamAssignmentView`), `backend/core/models.py` (`Node.team_rotation_enabled`, migration `core/0018_bug161_b2_team_assignment.py`), `backend/core/serializers.py`, `backend/core/workday.py` (`current_team`, `suggested_team`), `backend/core/reset.py`, `backend/sales/views.py` (blocage + équipe de la facture), tests `production/tests/test_bug161_b2_team_assignment.py`, `sales/tests/test_bug161_b2_team_blocking.py`, `core/tests/test_bug149_reset_superuser.py` (étendu).
- Migrations créées (non appliquées sur `db.sqlite3`, à appliquer par le coordinateur) : `core.0018_bug161_b2_team_assignment`, `production.0023_bug161_b2_team_assignment`.
- Décisions : modèle non synchronisable (convention `DailyOpeningConfirmation`) ; suggestion = autre équipe que la dernière journée désignée avant la courante (robuste à un jour sans désignation) ; blocage limité aux ventes et remboursements (ajustements non touchés) ; drapeau `team_rotation_enabled` False par défaut pour ne rien casser avant F2.
- Suites : `test production sales core` OK (production 207, sales 87, core OK) ; suite complète 709 tests OK (aucun échec, `test_charge_morning_peak` inclus) ; `makemigrations --check` propre.
- Risques : activer le drapeau avant la modale de désignation (F2) bloque la facturation du nœud ; les listes `/api/core/nodes/` exposent un nouveau champ ; la journée de travail suit `timezone.now()` côté serveur (le frontend ne doit pas envoyer de date).

## BUG-177 (volet backend) — NS / RG : rapport de clôture et effets de facturation (CORRIGÉ côté backend ; BUG-177 reste ouvert pour le frontend)

Décisions client/coordinateur appliquées (elles priment sur la recommandation de l'auditeur) : NS = jamais de déstockage ; CREDIT -> dette `valeur − paiement` + `DebtMovement` ; CASH -> aucune dette ; aucun contrôle de plafond ; CM 0 ; `deliver` refusé ; exemptée de `cleanup_expired`. RG : CM 0, aucune dette, livraison normale.

Fichiers : `backend/sales/models.py` (`Invoice.debt_delta`, `compute_debt_after`), `backend/sales/views.py` (`_create_once`, `deliver`, `cancel`, `cleanup_expired`, `pending_deliveries`), `backend/production/views.py` (`_build_daily_closure_report`), tests `backend/sales/tests/test_bug177_ns_rg.py` (10) et `backend/production/tests/test_bug177_closure_ns_rg.py` (6), `test_daily_closure_report.py` adapté (un champ additif). BUG-161/B2 (`TEAM_NOT_ASSIGNED`, `Invoice.team`) inchangés. Aucune migration (`makemigrations --check` propre).

Contrat `daily-closure` : `non_servi = {quantity, fc (positif), fc_signe (nouveau, négatif)}` ; `facture_mvm_interne.fc` et `totals.total_du_jour_fc` retranchent la NS ; `regularisation` = RG (+) + ajustements (±) ; `facture_jr`/`commission_jr` sans RG ; `ecart_facture_fc` sans NS.

Risques / à trancher : (1) `treasury/services.py` ligne ~123 (rapport facturier) compte encore un « crédit » pour une RG livrée sans paiement alors qu'aucune dette n'est créée ; (2) une NS reste PENDING indéfiniment : le frontend doit l'exclure des listes « à livrer » et afficher le libellé « Le client garde la dette » pour NS ; (3) l'ancienne NS en base (déjà créée avec déstockage/dette) n'est pas migrée.

## BUG-178 — Rapport facturier : RG ne compte ni crédit ni vente (CORRIGÉ)

Cause : `treasury/services.py::regenerate_facturier_reports` calculait `crédit = order_total − paiement` pour toute facture livrée, y compris une RG (sans paiement ni dette depuis BUG-177). Correction : la requête exclut `special_code` RG et NS (cash, crédit, valeur vendue, pains par catégorie). Le Niveau 2 (clôture), `suggested_ca` et le journal ne lisent que `FacturierReport` : corrigés par ricochet ; `signals.py` (BUG-036) inchangé ; BUG-033/091/100 non touchés. Test : `backend/treasury/tests/test_bug178_rg_not_credit.py` (6 tests, 4 échouaient avant). Aucune migration, aucun changement de contrat. Fichier modifié : `backend/treasury/services.py`.

## BUG-180 / 181 / 182 / 183 — Ventes : RG, ajustement NS/RG, équipe désignée (CORRIGÉS)

- BUG-180 : `sales/views.py::_create_once` — plafond et déficit du mois ne s'appliquent plus aux RG ; `period_agg` exclut les RG. Ventes normales inchangées.
- BUG-181 : `Invoice.debt_delta` (sales/models.py) suit la nature de l'originale pour un ajustement ; `adjust` : NS = aucun mouvement de stock ; NS CASH et RG = paiement forcé à 0 ; `net_delta = adjustment.debt_delta`. Choix : une RG livrée a déstocké, son ajustement modifie donc le stock normalement (retour physique par défaut BUG-097), sans effet sur la dette. `recompute_client_debt()` vérifié égal à la dette stockée (NS CASH, NS CREDIT, RG).
- BUG-182 : `adjust` pose l'équipe désignée (`current_team`) si rotation active et désignation existante, sinon `request.user.team` ; jamais bloqué.
- BUG-183 (décision coordinateur) : vente rétroactive = équipe désignée pour la journée `invoice_date`, sinon repli `request.user.team`, jamais de blocage ; vente du jour inchangée (403 sans désignation).
- Tests : `backend/sales/tests/test_bug180_181_182_183.py` (14). 7 `expectedFailure` retirés dans `test_verif_ventes_bug177_bug161b2.py` (aucun laissé). Test du testeur `test_backdated_invoice_blocked_without_today_assignment` renommé/inversé car il actait l'ancien comportement (contradiction avec la décision BUG-183) : à valider par testeur-ventes.
- Aucune migration, aucun changement de contrat API (ajustement NS/RG accepté en 201).
- Risque : les tests `sales` sont très lents sur ce poste (~12 s/test, 49 tests = 618 s).
- Vérifications : suites `sales` + `treasury` (266 tests) vertes (1 expectedFailure = BUG-179, hors périmètre) ; `makemigrations --check` propre. Suite complète NON terminée : ~12 s/test sur ce poste, interrompue à ~210/1850 (production, core, etc. non rejouées) : à relancer par le coordinateur.

## BUG-185 / 186 / 187 (production, testeur-production) — CORRIGÉS
- BUG-185 : `_build_daily_closure_report` exclut NS/RG de `soldee_invoices` ; la RG est valorisée à prix plein en Régularisation (catalogue si la facture est soldée). Total du jour 3 000 FC au lieu de 4 500. Réserve : `ecart_facture_fc` (order_total) inchangé.
- BUG-186 : convention = répartition par quantité de la production DÉCLARÉE (lignes DECLARED) ; dénominateur = Σ `produit.quantity` ; CARRYOVER exclu ; somme 100 %. `total_breads_produced` et les totaux FC inchangés.
- BUG-187 : `TeamAssignmentView.post` renvoie 400 `{"detail"}` pour un corps non objet ou `node`/`team` de mauvais type.
- Tests : `production/tests/test_bug185_186_187.py` ; 3 `expectedFailure` du testeur retirés (aucun laissé). Aucune migration, aucun changement de contrat.
- Risque : `DailyOpeningConfirmationView` utilise le même schéma `request.data.get` (non corrigée, hors ticket).
