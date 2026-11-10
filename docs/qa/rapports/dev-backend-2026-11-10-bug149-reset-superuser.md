# dev-backend — 2026-11-10 — BUG-149 : réinitialisation globale des données (Superuser)

## Contexte

remarque.md (après l.404) : « En tant que Superuser, j'aimerais avoir un bouton pour supprimer les
autres données sauf, les données de la configuration, les succursales (boulangeries), les
utilisateurs et la liste des clients ».

Clarifié avec le coordinateur avant de commencer :
- Accès réservé STRICTEMENT à `request.user.is_superuser == True` (flag technique Django), jamais au
  rôle métier (ADMIN/DIRECTION). Un compte DIRECTION nommé, sans ce flag, est refusé.
- Les soldes clients dérivés de l'historique (`current_debt`, `total_breads_received`, `category`)
  sont remis à zéro/`NORMAL` — la fiche client (code, nom, téléphone, adresse, photo, plafond, type,
  boulangerie) est conservée telle quelle.

## Ce qui est conservé

- `core.Config` (singleton).
- `core.Node` (boulangeries, créneaux A/B, `sac_value_fc`).
- `core.User` (tous les comptes).
- `core.BreadPrice`, `core.ExpenseCategory` : paramétrage « Configuration » (catégories de pains/
  dépenses), pas des données transactionnelles.
- `clients.Client` : la fiche elle-même, intacte. Champs dérivés de l'historique remis à zéro/Normal
  via une mise à jour en masse (`Client.objects.update(...)`), jamais une boucle Python.
- `clients.ClientCodeSequence` : non touché (les clients existants sont conservés, ce compteur n'a
  aucune raison de changer).
- `sync.NodeAuthToken` : **décision documentée** (pas une ambiguïté métier réelle, un choix
  d'infrastructure clair) — c'est un jeton d'authentification de MACHINE/nœud
  (cahierDesCharges.md §6.3.1), analogue à un JWT utilisateur ou à une clé d'API, jamais une donnée
  métier/comptable. Le conserver est cohérent avec la conservation de `core.User` (ce bouton ne
  déconnecte/ne révoque rien côté authentification) ; le supprimer casserait silencieusement la
  synchronisation d'un nœud desktop sans que l'utilisateur l'ait demandé explicitement.

## Ce qui est supprimé (inventaire complet)

| App | Modèles supprimés |
|---|---|
| sales | `Invoice`, `InvoiceLine` |
| production | `ProductionSession`, `ProductionSessionLine`, `BreadStock`, `ConsumableStock`, `ConsumableMovement`, `ConsumableCount`, `BreadTransfer`, `BreadTransferLine`, `BreadDisposal`, `DailyBreadStockSnapshot`, `DailyOpeningConfirmation`, `DailyOpeningConfirmationLine` |
| treasury | `LocalExpense`, `FacturierReport`, `CashClosure`, `CashbookEntry`, `JournalEntry`, `DailySavings`, `DisbursementVoucher`, `DirectionCashCount` |
| commissions | `CommissionPeriod`, `ClientCommission` |
| finance | `FinancialYear` |
| blockchain | `TamperAlert`, `BlockchainSnapshot` |
| clients | `SocialContribution`, `SocialDistribution`, `SocialDistributionLine` (caisse sociale — PAS la liste des clients) |
| core | `ActivityLog`, `SystemNotification`, `ColisDistribution` |
| sync | `DebtMovement`, `SyncBatchLog`, `SyncConflictLog` |

Deux choix méritent d'être explicités (demandés par le ticket, pas de réelle ambiguïté métier
remontée au coordinateur — raisonnement documenté ici) :

- **`core.ColisDistribution`** : supprimé. C'est un événement annuel transactionnel (distribution de
  riz/viande/espèces à un bénéficiaire donné, pour une année donnée) — contrairement à
  `BreadPrice`/`ExpenseCategory`, elle n'a ni liste figée de paramétrage ni écran de « Configuration »
  dédié, et aucun autre modèle ne la référence comme un référentiel. Elle appartient à la même
  catégorie que les autres historiques transactionnels par boulangerie/année.
- **`sync.DebtMovement`** : supprimé, et c'est **important** de bien le faire en même temps que les
  factures. `Client.current_debt` peut être recalculé par `sync.services.recompute_client_debt()`
  comme la SOMME des `DebtMovement` existants pour ce client. Si on avait supprimé les factures sans
  purger `DebtMovement`, un recalcul ultérieur (déclenché par le module de synchronisation) aurait
  reconstitué l'ancienne dette à partir de ces mouvements devenus orphelins — contredisant
  silencieusement le `current_debt = 0` fixé par cette opération.
- **`sync.NodeAuthToken`** : conservé (voir section précédente) — c'est le seul modèle de l'app
  `sync` traité différemment des deux autres (`DebtMovement`, `SyncBatchLog`/`SyncConflictLog`,
  supprimés car ce sont des journaux/historiques transactionnels, pas de l'infrastructure).

## Ordre de suppression (contraintes `on_delete=PROTECT`)

Toute la suppression a lieu dans un seul `transaction.atomic()` (voir `backend/core/reset.py`,
fonction `execute_reset`). Point notable : `Invoice.adjusts` est un FK self-référent
`on_delete=PROTECT` (une facture d'origine est protégée tant qu'une facture d'ajustement la
référence). Avant toute suppression de factures, on casse ce lien avec
`Invoice.objects.update(adjusts=None)` (champ nullable) — sans ça, une facture originale référencée
par son propre ajustement bloquerait sa suppression même si l'ajustement est supprimé dans la même
opération.

Second point : `ConsumableMovement.stock` est `on_delete=PROTECT` vers `ConsumableStock` — les
mouvements sont donc supprimés avant les stocks. Tout le reste pointe soit vers des modèles
CONSERVÉS (`Node`/`User`/`Client`/`BreadPrice`, jamais bloquant puisqu'ils restent en base), soit via
`CASCADE`/`SET_NULL` (jamais bloquant, peu importe l'ordre).

## Contrat API (pour `dev-frontend`, ticket BUG-150)

### `GET /api/core/reset-data/`

Aperçu en lecture seule — **ne modifie jamais la base**. Réservé à `request.user.is_superuser`
(403 sinon, y compris pour un rôle ADMIN/DIRECTION sans ce flag).

Réponse `200` — décompte de ce qui SERAIT supprimé/réinitialisé par modèle (clé = nom technique
interne, pas forcément le nom du modèle Django) :

```json
{
  "sync_conflict_logs": 0,
  "sync_batch_logs": 3,
  "debt_movements": 128,
  "tamper_alerts": 0,
  "blockchain_snapshots": 12,
  "client_commissions": 45,
  "commission_periods": 6,
  "financial_years": 1,
  "direction_cash_counts": 2,
  "cashbook_entries": 310,
  "journal_entries": 88,
  "daily_savings": 30,
  "disbursement_vouchers": 4,
  "cash_closures": 56,
  "facturier_reports": 60,
  "local_expenses": 77,
  "consumable_movements": 210,
  "consumable_stocks": 24,
  "consumable_counts": 10,
  "bread_disposals": 95,
  "production_session_lines": 140,
  "production_sessions": 70,
  "bread_transfer_lines": 5,
  "bread_transfers": 3,
  "bread_stocks": 24,
  "daily_opening_confirmation_lines": 20,
  "daily_opening_confirmations": 10,
  "daily_bread_stock_snapshots": 150,
  "invoice_lines": 980,
  "invoices": 420,
  "social_distribution_lines": 18,
  "social_distributions": 2,
  "social_contributions": 60,
  "colis_distributions": 8,
  "activity_logs": 540,
  "system_notifications": 90,
  "clients_to_reset": 37
}
```

`clients_to_reset` = nombre de clients dont au moins un champ dérivé (`current_debt`,
`total_breads_received`, `category`) n'est pas déjà à sa valeur par défaut — PAS un décompte de
suppression (les clients ne sont jamais supprimés).

### `POST /api/core/reset-data/`

Corps de requête attendu (JSON) :

```json
{ "confirm_phrase": "SUPPRIMER TOUT", "password": "<mot de passe ACTUEL du superuser>" }
```

- `confirm_phrase` doit être **exactement** `"SUPPRIMER TOUT"` (sensible à la casse, aux espaces —
  comparaison stricte après `strip()`). Choisie délibérément en deux mots majuscules, plus difficile
  à taper par accident qu'un simple « SUPPRIMER ».
- `password` est revérifié via `user.check_password(...)` — jamais le JWT seul, même esprit qu'une
  suppression de compte/action destructive à double confirmation.
- Si l'un des deux manque ou est incorrect → `400 {"detail": "..."}`, **rien n'est supprimé** (vérifié
  explicitement par les tests : aucune ligne ne disparaît).
- Succès → `200`, même forme de réponse que le `GET` (décompte de ce qui a été **effectivement**
  supprimé/réinitialisé), pour que le frontend affiche une confirmation visuelle après coup.

Suggestion UI pour `dev-frontend` (ticket BUG-150, non implémentée ici — aucun fichier frontend
touché) : bouton visible uniquement si `user.is_superuser` (champ déjà exposé par `UserSerializer` ?
à vérifier — sinon l'ajouter à `/api/core/auth/me/`), écran Configuration. Boîte de confirmation en
deux étapes : (1) afficher le `GET` d'aperçu avec les plus gros décomptes en évidence, (2) champ texte
« Tapez SUPPRIMER TOUT pour confirmer » + champ mot de passe, bouton désactivé jusqu'à correspondance
exacte de la phrase.

## Fichiers modifiés/créés

- `backend/core/permissions.py` : nouvelle classe `IsSuperuser` (flag technique strict, pas de rôle
  métier).
- `backend/core/reset.py` (nouveau) : logique de suppression (`_DELETION_ORDER`, `preview_counts()`,
  `execute_reset()`), avec la justification complète de chaque choix de conservation/suppression dans
  la docstring du module.
- `backend/core/views.py` : nouvelle vue `reset_data_view` (GET/POST).
- `backend/core/urls.py` : route `reset-data/`.
- `backend/core/tests/test_bug149_reset_superuser.py` (nouveau) : permission stricte (DIRECTION/ADMIN
  sans `is_superuser` refusés, superuser accepté, anonyme refusé) ; `GET` ne modifie jamais rien ;
  `POST` refusé sans phrase/mot de passe correct, rien n'est supprimé (vérifié explicitement, pas
  seulement le code HTTP) ; scénario complet bout en bout (une donnée fictive par catégorie à
  supprimer + un client avec dette/pains livrés non nuls) vérifiant que tout disparaît sauf
  Config/Node/User/BreadPrice/ExpenseCategory/NodeAuthToken/Client (fiche), et que les champs dérivés
  du client sont bien remis à zéro/Normal.

## Tests

- `backend/.venv/Scripts/python.exe manage.py test core.tests.test_bug149_reset_superuser` →
  **11/11 OK**.
- `backend/.venv/Scripts/python.exe manage.py test` (suite COMPLÈTE, tous modules) →
  **`Ran 599 tests in 1662.686s — OK`**. Aucune régression introduite par ce ticket sur les autres
  modules (sales/production/treasury/commissions/finance/blockchain/sync/clients).
- `backend/.venv/Scripts/python.exe manage.py check` → `System check identified no issues`.
- `backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → `No changes
  detected` (aucun nouveau champ/modèle introduit par ce ticket, cohérent avec une suppression de
  données pure, sans changement de schéma).

Note d'environnement : deux processus `runserver` préexistants (un avec le bon interpréteur
`.venv`, un avec l'interpréteur système) tournaient déjà sur le port 8000 au début de cette session,
antérieurs à mon intervention (horodatage avant le début de mes travaux) — je ne les ai ni utilisés
ni arrêtés (pas les miens, possible session active du coordinateur). Aucun processus `manage.py
test`/`runserver` n'a été laissé actif par moi à la fin de cette session.

## Impact contrat d'API

Nouvel endpoint uniquement (`GET/POST /api/core/reset-data/`) — aucun endpoint existant modifié.
Ticket **BUG-150** ouvert dans le registre pour `dev-frontend` (bouton + boîte de confirmation,
écran Configuration), avec le contrat détaillé ci-dessus pour implémenter sans deviner.

## Registre

Ticket **BUG-149** ouvert et passé directement à `CORRIGÉ` (jamais `VÉRIFIÉ` — c'est au testeur
d'origine ou au coordinateur de le vérifier, CLAUDE.md §7 règle 3).
