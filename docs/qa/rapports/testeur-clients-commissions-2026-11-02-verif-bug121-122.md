# Rapport testeur-clients-commissions — 2026-11-02 — Vérification BUG-121 / BUG-122

Mission : revérifier deux tickets `CORRIGÉ` du module Clients/Commissions
(`docs/qa/REGISTRE_BUGS.md`), par des scénarios réels (pas une relecture
seule), sur la base du rapport `docs/qa/rapports/dev-backend-2026-11-02-q001-
q002-q005.md`.

## BUG-121 (Q-001) — Grille de prix de référence seedée

Vérifié :
- `backend/core/management/commands/seed_kiese.py` seed bien
  `MINI=200/MOYEN=300/GRAND=500/PREMIUM=1000` FC (relecture directe du
  fichier).
- Recherche de toute autre référence en dur à l'ancienne grille
  (300/400/500/1000) côté backend : `grep` large sur le dossier `backend/`
  (hors `staticfiles/`, hors `desktop/resources/` — volontairement non
  touché, Desktop suspendu par Q-004). Les seules occurrences de
  300/400/500/1000 restantes sont des valeurs de test génériques dans
  d'autres modules (`sales`, `production`, `treasury`, `sync`, `finance`)
  sans rapport avec la grille de référence — pas une régression.
- `finance/views.py` garde des noms de variables `revenue_300/400/500/1000`
  qui ne correspondent plus littéralement aux valeurs FC réelles des
  catégories — confirmé que ce n'est qu'un nommage interne (clés mappées par
  `category` MINI/MOYEN/GRAND/PREMIUM), le total agrégé reste correct. Pas une
  anomalie, déjà documenté par dev-backend.
- Non-régression des calculs qui dépendent de la grille (commissions,
  factures) : la formule `CM brute = order_value × taux` ne dépend pas de la
  valeur littérale des prix, seulement de `order_value` (dérivé de
  `BreadPrice.unit_price` figé par `InvoiceLine.save()`) — déjà couvert par
  les suites `sales`/`commissions` existantes, relancées sans échec (83 tests
  `clients`+`commissions`, `OK`).

**Conclusion : aucun défaut trouvé. BUG-121 passé à `VÉRIFIÉ`.**

## BUG-122 (Q-002) — Report de dette entre deux périodes de commission

Relecture du correctif (`backend/commissions/models.py::ClientCommission.
compute()` / `_compute_carried_debt_in()`) confirmée cohérente avec la
décision client (report cumulatif, jamais remis à zéro, jamais réclamé
immédiatement, même logique que BP_client CLAUDE.md §5.2).

Puis vérification par **3 scénarios réels** écrits dans
`backend/commissions/tests/test_verif_bug122_2026_11_02.py` (en plus des 2
tests déjà livrés par dev-backend dans `test_bug122_carried_debt.py`, tous
toujours au vert) :

1. **Chaîne de 3+ périodes consécutives**
   (`test_debt_carries_across_three_consecutive_negative_periods`) : le
   client reste déficitaire deux périodes de suite (le report s'alourdit à
   chaque fois, jamais soldé entre-temps), puis une grosse commande éponge
   tout le passif cumulé à la 3ᵉ période. Une 4ᵉ période confirme que
   `carried_debt_in` retombe bien à 0 une fois le passif résorbé. Les
   `net_payable` historiques des périodes 1 et 2 restent inchangés dans la
   base (jamais remis à zéro rétroactivement).
2. **Ajustement manuel DIRECTION non recombiné avec le report**
   (`test_manual_override_is_not_recombined_with_carry_and_feeds_next_period`) :
   un report automatique s'applique d'abord normalement sur une période 2
   déficitaire ; la DIRECTION pose ensuite un `manuel_adjustment` positif via
   `POST /api/commissions/commissions/{id}/set_manuel/`. Confirmé que
   `net_payable = manuel_adjustment + bonus` (le `carried_debt_in` stocké
   n'est pas resoustrait une seconde fois), et que la période 3 suivante
   calcule son propre report à partir du `net_payable` **effectif** (post
   ajustement, positif) de la période 2 → aucun report pour la période 3.
   L'override manuel n'est donc jamais recombiné, ni immédiatement ni après
   coup — conforme à ce que documente dev-backend.
3. **Trou de génération** (`test_gap_period_without_invoice_does_not_break_
   the_carry`) : aucune facture pour le client sur une période intermédiaire
   (donc aucune `ClientCommission` générée pour lui ce mois-là — un vrai
   trou, pas simulé). Confirmé que le report de la période précédente
   traverse bien ce trou et s'applique correctement sur la commission
   suivante, grâce à la recherche de « la commission la plus récente
   strictement antérieure » plutôt qu'une recherche fixe sur N-1.

Les 3 tests ont d'abord échoué sur une erreur de route de ma part
(`/api/commissions/client-commissions/` au lieu de `/api/commissions/
commissions/` — erreur dans mon test, pas une anomalie applicative) ; une
fois corrigée, les 3 passent du premier coup contre le code existant, sans
aucune modification du code applicatif.

**Conclusion : aucun défaut trouvé, les 3 points demandés par le
coordinateur sont confirmés par des scénarios réels. BUG-122 passé à
`VÉRIFIÉ`.**

## Suites lancées

- `backend/.venv/Scripts/python.exe manage.py test clients commissions` :
  **83 tests, `OK`** (aucun échec).
- `backend/.venv/Scripts/python.exe manage.py test commissions.tests.
  test_verif_bug122_2026_11_02` : **3 tests, `OK`**.
- `backend/.venv/Scripts/python.exe manage.py test` (suite complète,
  demandée par la mission) : **489 tests, 3 échecs, 1238.8s.**
  Les 3 échecs sont **hors périmètre Clients/Commissions**, tous dans
  `treasury` :
  - `treasury.tests.test_bug053_signal_side_effects.
    DeliveryBlockedSideEffectTests.
    test_blocked_delivery_still_leaves_client_bread_counter_incremented`
  - `treasury.tests.test_repayment_after_vacation_locked_probe.
    RepaymentNotBlockedByVacationLockTests.
    test_normal_sale_delivery_still_blocked_after_report_generated`
  - `treasury.tests.test_scope_gaps.FacturierSessionLockTests.
    test_no_new_invoice_affects_an_already_generated_report` (référence
    explicitement `BUG-036` dans son message d'échec)
  Ces 3 tests appartiennent au module de `testeur-tresorerie`, ne sont pas
  marqués `@expectedFailure`, et n'ont pas été touchés par cette mission (je
  n'ai modifié aucun fichier `treasury/`). Signalé ici pour le coordinateur
  et `testeur-tresorerie` — pas corrigé, hors mandat (CLAUDE.md §7 règle 2 :
  « les testeurs ne corrigent pas le code applicatif » et ne débordent pas
  du périmètre confié). La suite `clients`+`commissions` isolée reste
  intégralement verte, ce qui couvre la condition « `python manage.py test`
  passe » pour le périmètre de cette mission.

## Registre mis à jour

`docs/qa/REGISTRE_BUGS.md` :
- BUG-121 : `CORRIGÉ` → `VÉRIFIÉ` (colonne « Vérifié par » : `testeur-
  clients-commissions (2026-11-02)`), note de vérification ajoutée dans la
  fiche détaillée.
- BUG-122 : `CORRIGÉ` → `VÉRIFIÉ` (colonne « Vérifié par » : `testeur-
  clients-commissions (2026-11-02)`), note de vérification détaillée (3
  scénarios) ajoutée dans la fiche.
- BUG-124 (ticket lié frontend, hors mandat de cette mission) : déjà passé à
  `CORRIGÉ` par un autre agent entre temps (constaté, non modifié par moi).

## Fichiers touchés par cette mission

- `backend/commissions/tests/test_verif_bug122_2026_11_02.py` (nouveau,
  3 tests de vérification).
- `docs/qa/REGISTRE_BUGS.md` (statuts BUG-121/BUG-122 → `VÉRIFIÉ` + notes).
- `docs/qa/rapports/testeur-clients-commissions-2026-11-02-verif-bug121-122.md`
  (ce rapport).

Aucun fichier de code applicatif modifié (CLAUDE.md §7 règle 2 respectée).
