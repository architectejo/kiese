# Rapport dev-backend — 2026-11-19

Tickets : BUG-303, BUG-304, BUG-306 (partie API) -> CORRIGÉ. Aucun passage à VÉRIFIÉ.
Base de test isolée via `DB_NAME` (jamais `backend/db.sqlite3`).

## BUG-303 — refuser les négatifs à « Clôturer la Fournée »
- Cause : `close()` acceptait les quantités négatives de `remaining` (décision BUG-158, 2026-11-10).
- Correction : `ProductionSessionViewSet.close` (`production/views.py`) répond 400
  `{"detail": "« remaining » : la quantité ne peut pas être négative."}`, rien n'est appliqué (session non clôturée).
- **Contradiction signalée** : remarque.md du 2026-11-19 (« Ne pas accepter les négatifs ») remplace l'instruction BUG-158 du 2026-11-10 pour CETTE saisie. Décision stock/consommable négatif (BUG-143/158) inchangée ailleurs : la clôture FORCÉE automatique (`shift-end-status`), le formulaire `disposals` (REMAINING) et la confirmation du stock de départ (BUG-162) acceptent toujours le négatif. À confirmer avec le client si ces chemins doivent aussi refuser.
- Tests existants adaptés (décision client postérieure, non affaiblis) : `test_daily_stock_snapshot.py::test_close_with_negative_remaining_quantity_is_rejected_and_nothing_applied`, `test_bug158_auto_closure_negative_stock.py::test_negative_suggested_value_is_rejected_by_voluntary_close`. Nouveau : `Bug303NegativeClosureTests`.
- Impact frontend : `quantity_suggested` renvoyé par `shift-end-status` peut rester négatif (stock réel) ; le frontend doit empêcher l'envoi d'un négatif (déjà fait par dev-frontend, min=0).

## BUG-304 — reste d'hier / reste du jour pris pour le jour
- Cause : le rapport ne les exposait que par équipe (`reste_du_hier`, `reste_du_jour` = dicts {A,B}).
- Correction additive (`_build_daily_closure_report`) ; les dicts par équipe, les totaux FC et l'identité du rapport sont conservés (pas de casse de l'historique ni de BUG-139/141/151/152).
- Contrat (`GET /api/production/daily-closure/`) :
  - par catégorie : `reste_du_hier_jour` (int, convention négative du rapport) et `reste_du_jour_jour` (int ou `null` si non encore déclaré).
    Rotation : départ = somme du dict par équipe (une seule équipe porteuse), fin = `reste_du_jour_fin_journee`.
    Hors rotation : départ = stock de départ confirmé le plus tôt du jour, sinon dernier reste du nœud avant le jour (toutes équipes, ex. A=10 puis B=5 -> -5, pas -15) ; fin = dernier reste déclaré du jour (toutes équipes).
  - `totals.reste_du_hier_jour_fc`, `totals.reste_du_jour_jour_fc` (str décimales).
- Note : cette logique était déjà présente dans le working tree (session interrompue) ; un doublon de mon ajout a été retiré.
- Tests : `Bug304DayLevelRestesTests`.

## BUG-306 — fournée « en cours » par nombre de sacs (API)
- Migration `production/migrations/0024_productionsession_auto_track.py` : `ProductionSession.auto_track` (bool, défaut False).
- Déclaration : `POST /api/production/sessions/` avec `flour_sacks_used` seul (`lines` désormais facultatif) -> 201, session ouverte, `auto_track=true`, équipe/date = équipe en service et journée de travail (défauts de rotation inchangés). Aucune alerte « Manquant de Rendement » à la déclaration.
- Augmenter les sacs : nouveau `POST` identique (additif, même session, BUG-142) ou `PATCH /sessions/{id}/ {"flour_sacks_used": "4.00"}` (absolu).
- Une session existante du jour sans ligne DECLARED passe en `auto_track` sur un POST sacs seuls ; une fournée déclarée avec des quantités de pains (flux historique) n'est jamais modifiée automatiquement.
- Incrément automatique : `POST /api/sales/invoices/{id}/deliver/` appelle `production.services.apply_delivered_invoice_to_open_batch` (transaction.atomic, `select_for_update` sur la session, `F()` sur les lignes et `BreadStock.qty_produced`) : lignes DECLARED par catégorie + totaux recalculés ; `log_activity("Avancement Fournée")`. Cible = fournée ouverte `auto_track` du nœud, de la journée de travail de la livraison, de l'équipe en service (rotation). Ignorés : remboursements, ajustements, NS, factures sans ligne, fournée clôturée, autre boulangerie.
- Champs ajoutés à la session (lecture seule, `GET /sessions/` et `/sessions/{id}/`) :
  - `auto_track` (bool), `is_in_progress` (= non clôturée)
  - `objective_fc` (int) = sacs x valeur du sac figée à la déclaration (`Node.sac_value_fc`, sinon Config ; BUG-038) = `theoretical_yield`
  - `progress_value_fc` (int) = valeur livrée sur la fournée (au prix catalogue, y compris vente soldée)
  - `progress_pct` (str, 2 décimales, non plafonné : peut dépasser 100)
  - `lines[]` s'incrémentent (`bread_price`, `quantity`, `source=DECLARED`).
- Proposition de seuils pour la barre (rouge -> orange -> jaune -> verte), à valider/trancher côté frontend : <25 % rouge, <50 % orange, <100 % jaune, >=100 % verte.
- Tests : `Bug306BatchInProgressTests` (7).
- Limites / points à trancher : (1) valeur du sac figée à la 1re déclaration, pas relue si `Node.sac_value_fc` change ensuite ; (2) les factures d'ajustement d'une vente déjà livrée ne corrigent pas l'avancement ; (3) conflit possible avec cahierDesCharges §5.4 (valeur produite déclarée) : remarque.md prioritaire, à signaler au client ; (4) avec incrément automatique, produit = livré, donc le reliquat NV du recoupement à la clôture n'est plus informatif pour ces fournées.

## Tests
- `production.tests.test_bug303_304_306_2026_11_19` : 10 tests verts.
- Suite complète (`DB_NAME` isolée, --parallel 4) : 1341 tests, OK (skipped=1, expected failures=1).
- `makemigrations --check --dry-run` : No changes detected.

## Ticket frontend lié
Contrat ci-dessus à consommer par dev-frontend (objectif, barre de progression, déclaration par sacs, champs `reste_du_*_jour`).

## BUG-309 (CORRIGÉ, à vérifier par testeur-production)
- Cause : `flour_sacks_used` non validé ; un négatif déclenchait la CHECK `theoretical_yield` (500).
- Correctif : `ProductionSessionSerializer.to_internal_value` -> 400 `{"detail"}` français (négatif, non numérique, vide/null/booléen, NaN/Infinity, > 100 000, > 2 décimales). 0 accepté (contrat BUG-306).
- Mineur : `close()` refuse un `remaining` non entier (-0,5, 2.5, NaN...) au lieu de le tronquer en 0.
- Fichiers : `backend/production/serializers.py`, `backend/production/views.py`, tests `test_verif_bug303_304_306_testeur_production.py` (2 `@expectedFailure` retirés + 1 test), `test_bug303_304_306_2026_11_19.py` (`Bug309FractionalRemainingTests`).
- Risque : un client frontend envoyant un reste décimal reçoit désormais 400 (le champ est entier côté UI).
- Suite `manage.py test production` (base isolée DB_NAME) : 456 tests, 1 échec = test constat de troncature (-0.5) mis à jour vers 400, puis rejoué OK (48 tests ciblés). `makemigrations --check` : aucun changement.
