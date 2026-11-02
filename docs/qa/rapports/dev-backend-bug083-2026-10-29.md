# Rapport dev-backend — BUG-083 (« ventes passées ») — 2026-10-29

## Périmètre traité

Backend uniquement, conformément au mandat reçu (un agent dev-frontend séparé traite
`Clients.tsx`/`Sales.tsx` après cette session). Ticket **laissé à `EN COURS`** dans
`docs/qa/REGISTRE_BUGS.md` — jamais passé à `VÉRIFIÉ` (règle CLAUDE.md §7.2/§7.3 : seul le testeur
d'origine, ici testeur-tresorerie/testeur-ventes/testeur-clients-commissions, valide une correction).

## Implémentation, dans l'ordre demandé

1. `Config.allow_backdated_sales` (booléen, défaut `False`) — migration
   `core/migrations/0015_config_allow_backdated_sales.py`. Écriture réservée ADMIN/DIRECTION via
   `ConfigView` (déjà le cas avant ce ticket pour tout PATCH/PUT), lecture ouverte à tout authentifié.
2. `Invoice.invoice_date` : `auto_now_add` retiré → `default=timezone.localdate`, champ éditable —
   migration `sales/migrations/0006_alter_invoice_invoice_date.py`. Validation serveur centralisée
   dans `sales/views.py::_validate_requested_date` (jamais de date future ; date passée refusée sauf
   `allow_backdated_sales=True`), appliquée dans `InvoiceViewSet._create_once` (flux standard ET
   remboursement BP).
3. `Invoice.deliver(livreur, delivered_at=None)` + `InvoiceViewSet.deliver` : `delivered_at` optionnel
   dans le payload (`AAAA-MM-JJ`), même validation, heure réelle de l'appel conservée
   (`_combine_date_with_now_time`).
4. `_warn_if_commission_period_locked` (sales/views.py) : notification (`SystemNotification`,
   `DANGER` si une commission du client est déjà `is_paid`, `WARNING` sinon) quand une facture
   rétroactive tombe dans une `CommissionPeriod.is_closed` — jamais de recalcul automatique.
5. Mécanisme de correction du Livre de Caisse (voir section dédiée ci-dessous — le cœur technique du
   ticket) : `treasury/signals.py` (BUG-036) laisse désormais passer une livraison rétroactive quand
   `allow_backdated_sales=True`, et planifie `treasury.services.handle_retroactive_delivery` après
   commit.
6. `treasury/signals.py::block_delivery_on_already_reported_vacation` ajusté en conséquence, sans
   toucher au comportement par défaut (BUG-036 reste strictement actif quand le réglage est
   désactivé, ou pour une re-livraison du jour même déjà rapportée).

## Mécanisme de correction du Livre de Caisse — le point le plus délicat

**Problème** : une livraison rétroactive peut cibler un jour dont la `CashClosure` est déjà
`is_validated=True` ET déjà poussée au Livre de Caisse Direction (`CashbookEntry`, immuable et
chaîné par hash SHA-256, CLAUDE.md §5.5). Il faut refléter la vente ajoutée sans jamais modifier ou
supprimer l'écriture déjà versée.

**Solution retenue** (`treasury/services.py`) :

- `regenerate_facturier_reports(node, target_date)` : extraction (comportement inchangé) de la
  logique d'agrégation de `FacturierReportViewSet.generate`, maintenant partagée par l'action et par
  le mécanisme de correction (une seule implémentation).
- `handle_retroactive_delivery(invoice, node, team, delivery_date, acting_user)` : régénère le
  rapport Niveau 1, puis selon l'état de la `CashClosure` du jour :
  - absente → rien de plus (le gérant clôturera plus tard avec les bons chiffres) ;
  - non validée, ou validée mais jamais poussée → simple recalcul direct des totaux affichés de la
    clôture (rien d'immuable n'existe encore) ;
  - **validée ET déjà poussée (verrouillée)** → le cas non négociable : calcule le delta entre les
    totaux recalculés et `closure.net_cash` **tel qu'il était au moment du push** (jamais modifié),
    puis appelle `record_backdated_correction`.
- `record_backdated_correction(closure, delta, invoice, acting_user)` : ajoute une **nouvelle**
  `CashbookEntry` via `append_cashbook_entry` (fonction unique d'écriture, BUG-002, réutilisée sans
  aucune modification), avec :
  - `date = timezone.localdate()` — **le jour réel de la saisie, jamais la date rétroactive de la
    clôture corrigée.** Ce n'est pas un détail cosmétique : `verify_cashbook_chain` vérifie la chaîne
    par ordre `(date, created_at)` croissant, alors que `_get_last_balance`/`append_cashbook_entry`
    déterminent le `previous_hash` à partir du dernier bloc réellement inséré
    (`order_by('-date', '-created_at')`). Une écriture portant une date dans le passé mais insérée
    aujourd'hui romprait cet ordre : son `previous_hash` pointerait vers le tout dernier bloc réel,
    mais la vérification l'attendrait juste après le dernier bloc de SA PROPRE date (potentiellement
    des semaines plus tôt dans la chaîne), ce qui déclencherait une fausse alerte de falsification
    côté `blockchain`/`integrity_check`. Dater la correction du jour réel évite ce problème par
    construction — c'est d'ailleurs explicitement ce que demande le cahier des charges du ticket
    (« datée du jour RÉEL de la saisie »), qui s'avère donc être non seulement une exigence métier
    mais aussi la seule option techniquement cohérente avec le chaînage existant.
  - `is_correction=True`, `correction_reason` (texte : motif, référence facture/date d'origine),
    `corrected_by` (utilisateur), `correction_source_invoice` (FK vers la facture déclenchante) — 4
    nouveaux champs sur `CashbookEntry` (migration `treasury/migrations/0011_bug083_cashbook_correction_fields.py`).
  - Après l'ajout de la correction (jamais avant, pour que le delta soit calculé sur la valeur
    réellement poussée), les totaux AFFICHÉS de la `CashClosure` (`total_entries`, `net_cash`,
    `physical_cash_total`, `cash_gap`) sont recalculés et une note horodatée est ajoutée à
    `closure.notes` référençant la correction — c'est la « réouverture conceptuelle » demandée, sans
    toucher au Livre de Caisse lui-même.

**Choix de conception signalé explicitement (pas un raccourci caché)** : les 4 nouveaux champs ne
sont **pas** intégrés à `treasury.hashing.compute_cashbook_entry_hash`. Les y ajouter aurait changé la
formule de hash et exigé une nouvelle migration de données recalculant tous les `block_hash`
existants (comme `0007_recompute_cashbook_hash` l'a fait une fois pour BUG-001), avec le risque de
signaler à tort des écritures saines comme falsifiées pendant la bascule — jugé hors périmètre
raisonnable de ce ticket. Ces champs ont le même statut que `node_origin`/`is_synced`/`created_at`/
`updated_at` (déjà hors formule de hash avant BUG-083) : de la métadonnée d'audit, pas une donnée
dont l'altération changerait le solde ou le chaînage (déjà couverts par `entry_amount`/`exit_amount`/
`running_balance`/`previous_hash`). Je n'ai jamais eu besoin de modifier ou de contourner
`append_cashbook_entry`/`compute_cashbook_entry_hash` eux-mêmes — la correction passe exactement par
le même point d'entrée unique que toute autre écriture normale.

**Vérification du point non négociable** : `treasury/tests/test_bug083_backdated_cashbook_correction.py::RetroactiveDeliveryOnLockedClosureTests.test_retroactive_delivery_never_mutates_an_existing_cashbook_entry`
prend une empreinte complète (hash + tous les champs) de l'écriture existante AVANT la correction,
puis vérifie une égalité STRICTE après — en plus de vérifier la chaîne de hash entière
(`verify_cashbook_chain`) reste valide. C'est le test le plus important de cette session.

## Tests ajoutés (tous nouveaux, aucun n'existait avant ce ticket)

- `backend/core/tests/test_bug083_config_backdated_sales.py` (6 tests)
- `backend/sales/tests/test_bug083_backdated_sales.py` (10 tests)
- `backend/treasury/tests/test_bug083_backdated_cashbook_correction.py` (4 tests, dont le test
  critique ci-dessus — `TransactionTestCase` car le mécanisme dépend de `transaction.on_commit`,
  qui ne s'exécute jamais dans un `TestCase` classique, cf. commentaire déjà présent dans
  `sales/views.py::_record_debt_movement_after_commit` pour le même motif)

Tous passent individuellement. Aucun `@expectedFailure` retiré définitivement par cet agent (ces
tests n'existaient pas avant, donc écrits directement sans ce marqueur, conformément à la consigne).

## Résultat de la suite complète

`python manage.py test core sales treasury commissions sync` : voir sortie jointe à la fin de ce
rapport (exécutée en tâche de fond). `python manage.py makemigrations --check --dry-run` : aucune
dérive nouvelle — seule la dérive préexistante BUG-057 (`production`/`clients`/`treasury`,
`AlterField id`/`transfer_status`, `unique_together`) subsiste, non touchée par cette session (migration
`treasury/migrations/0011_bug083_cashbook_correction_fields.py` écrite à la main, isolée au seul
ajout des 4 champs, même convention que `0010_bug066_cashbook_localexpense_indexes.py`).

## BUG-084 (nouveau ticket ouvert, sans rapport avec BUG-083)

En vérifiant la non-régression, j'ai trouvé 2 échecs dans `treasury` :
- `test_cashbook_level3.py::FullDayIntegrationTests.test_full_day_scenario`
- `test_reports_closures.py::CashClosureNetCashTests.test_net_cash_is_cash_sales_minus_local_expenses`

Ces deux tests codent en dur la date `'2026-10-22'` mais livrent leurs factures via
`Invoice.deliver()` sans `delivered_at` explicite (donc `timezone.now()` = date réelle d'exécution).
Confirmé que `timezone.localdate()` dans cet environnement vaut bien `2026-10-29` (une semaine après
la date supposée par ces tests). J'ai vérifié explicitement que la logique qu'ils exercent
(`Invoice.deliver()` sans argument, `FacturierReportViewSet.generate`/`regenerate_facturier_reports`)
est strictement inchangée par BUG-083 — donc ce n'est pas une régression introduite par cette
session, mais une fragilité préexistante révélée par l'avancée du calendrier système. Documenté en
détail dans `docs/qa/REGISTRE_BUGS.md` (fiche BUG-084) plutôt que corrigé unilatéralement (ce sont des
tests écrits par testeur-tresorerie — CLAUDE.md §7 ne me demande pas de les corriger sans ticket, et
les modifier moi-même pour les faire passer serait exactement le genre de raccourci interdit par la
consigne de session).

## Fichiers modifiés (backend uniquement)

- `backend/core/models.py`, `backend/core/serializers.py`,
  `backend/core/migrations/0015_config_allow_backdated_sales.py`
- `backend/sales/models.py`, `backend/sales/serializers.py`, `backend/sales/views.py`,
  `backend/sales/migrations/0006_alter_invoice_invoice_date.py`
- `backend/treasury/models.py`, `backend/treasury/views.py`, `backend/treasury/services.py`,
  `backend/treasury/signals.py`, `backend/treasury/serializers.py`,
  `backend/treasury/migrations/0011_bug083_cashbook_correction_fields.py`
- `docs/architecture/SYNC.md` (§2.5 — note : aucun changement de modèle `DebtMovement` requis,
  vérifié explicitement, voir texte)
- Tests nouveaux : `backend/core/tests/test_bug083_config_backdated_sales.py`,
  `backend/sales/tests/test_bug083_backdated_sales.py`,
  `backend/treasury/tests/test_bug083_backdated_cashbook_correction.py`
- `docs/qa/REGISTRE_BUGS.md` : fiche BUG-083 (section Correction remplie, statut `EN COURS`), fiche
  BUG-084 ajoutée (nouveau ticket, `OUVERT`).

## Impact API / contrat (ticket lié à ouvrir pour dev-frontend par le coordinateur)

- `POST /api/sales/invoices/` : nouveau champ optionnel `invoice_date` (`AAAA-MM-JJ`).
- `POST /api/sales/invoices/{id}/deliver/` : nouveau champ optionnel `delivered_at` (`AAAA-MM-JJ`,
  date seule).
- `GET/PATCH /api/core/config/` : nouveau champ `allow_backdated_sales` (booléen).
- `CashbookEntrySerializer` (`GET /api/treasury/cashbook/`) : nouveaux champs `is_correction`,
  `correction_reason`, `corrected_by`, `corrected_by_display`, `correction_source_invoice`.

Reste à faire côté frontend (hors mandat de cette session) : champ de date dans `Clients.tsx`/
`Sales.tsx` (visible seulement si `allow_backdated_sales=True`, `max=aujourd'hui`), affichage d'un
badge « Correction » dans l'écran Livre de Caisse Direction.

## Risques / points d'attention pour le testeur

1. **BUG-084** (ci-dessus) à trancher avant de considérer la suite « 100% verte » — sans rapport avec
   BUG-083, mais présent dans le même run.
2. Le choix de ne pas étendre la formule de hash aux 4 nouveaux champs de `CashbookEntry` est un
   compromis documenté, pas une découverte cachée — à valider explicitement si le testeur ou
   l'auditeur comptable considère que la traçabilité de ces champs doit être elle-même protégée par
   le hash (impliquerait une nouvelle migration de données, hors périmètre de cette session).
3. `_make_receipt_number` reste basé sur la date réelle du jour de saisie, pas sur `invoice_date`
   choisi (une facture datée d'hier mais saisie aujourd'hui reçoit un numéro de reçu « d'aujourd'hui »)
   — non demandé explicitement par le cahier des charges, mentionné ici par transparence.
4. Le volet frontend n'a pas été touché (hors mandat) — Clients.tsx/Sales.tsx continueront de ne pas
   envoyer `invoice_date`/`delivered_at`, donc le comportement par défaut (date du jour) restera
   inchangé pour les utilisateurs jusqu'à l'intervention de dev-frontend.
