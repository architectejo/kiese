"""
BUG-149 — Réinitialisation globale des données (bouton Superuser).

remarque.md (après l.404) : « En tant que Superuser, j'aimerais avoir un
bouton pour supprimer les autres données sauf, les données de la
configuration, les succursales (boulangeries), les utilisateurs et la
liste des clients ».

Décisions prises avec le coordinateur (voir docs/qa/REGISTRE_BUGS.md
BUG-149 et docs/qa/rapports/dev-backend-2026-11-10-bug149-reset-superuser.md
pour le détail complet) :

CONSERVÉ (jamais touché par ce module) :
  - core.Config, core.Node, core.User
  - core.BreadPrice, core.ExpenseCategory (paramétrage « Configuration »)
  - clients.Client (la fiche elle-même : code, nom, téléphone, adresse,
    photo, plafond, type, boulangerie) — mais ses champs DÉRIVÉS de
    l'historique transactionnel supprimé sont remis à zéro/Normal :
    current_debt, total_breads_received, category.
  - clients.ClientCodeSequence (compteur de génération de code — les
    clients existants étant conservés, aucune raison de le toucher).
  - sync.NodeAuthToken : décision documentée (pas une ambiguïté métier,
    simple choix d'infrastructure) — c'est un jeton d'AUTHENTIFICATION de
    machine/nœud (cahierDesCharges.md §6.3.1), pas une donnée métier. Le
    conserver est cohérent avec la conservation de `core.User`/JWT, que ce
    bouton ne révoque pas non plus. Le supprimer casserait la
    synchronisation d'un nœud desktop sans que l'utilisateur l'ait demandé.

SUPPRIMÉ (tout le reste — inventaire complet des apps métier) :
  - sales.Invoice / sales.InvoiceLine
  - production.* (sessions, lignes, stocks pains/consommables, mouvements,
    comptages, transferts, dispositions, snapshots, confirmations d'ouverture)
  - treasury.* (dépenses locales, rapports facturier, clôtures, livre de
    caisse, journal, épargne, bordereaux, comptages Direction)
  - commissions.* (périodes, commissions clients)
  - finance.FinancialYear
  - blockchain.* (alertes, instantanés)
  - clients.SocialContribution / SocialDistribution / SocialDistributionLine
    (caisse sociale — historique transactionnel lié aux clients, PAS « la
    liste des clients » elle-même)
  - core.ActivityLog, core.SystemNotification
  - core.ColisDistribution : décision documentée — c'est un événement annuel
    de distribution de biens (riz/viande/espèces) à un bénéficiaire donné
    pour une année donnée, donc une donnée TRANSACTIONNELLE/historique
    (comme les autres), pas un réglage de « Configuration » (elle n'a ni
    liste figée ni écran de paramétrage — contrairement à BreadPrice/
    ExpenseCategory, elle n'est jamais réutilisée comme référentiel par un
    autre modèle).
  - sync.DebtMovement, sync.SyncBatchLog, sync.SyncConflictLog : journaux de
    mouvements/synchronisation — historique transactionnel, pas de
    l'infrastructure (contrairement à NodeAuthToken ci-dessus).
    IMPORTANT : `Client.current_debt` est recalculé par
    `sync.services.recompute_client_debt()` comme somme des `DebtMovement`
    existants — si on ne supprimait QUE les factures sans purger
    `DebtMovement`, un recalcul ultérieur reconstituerait l'ancienne dette
    à partir de ces mouvements orphelins. Doit donc être supprimé dans la
    MÊME opération que les factures, jamais laissé de côté.

Ordre de suppression : respecte les contraintes `on_delete=PROTECT`
existantes (ex. `ConsumableMovement.stock` avant `ConsumableStock` ;
`Invoice.adjusts` self-référent cassé par un `update(adjusts=None)`
préalable, sans quoi une facture d'origine référencée par ses propres
ajustements bloquerait sa suppression même si l'ajustement est supprimé
dans la même transaction). Tout le reste pointe soit vers des modèles
CONSERVÉS (Node/User/Client/BreadPrice — jamais bloquant puisqu'ils
restent en base), soit via CASCADE/SET_NULL (jamais bloquant).
"""

from django.db import transaction

from clients.models import Client, SocialContribution, SocialDistribution, SocialDistributionLine
from sales.models import Invoice, InvoiceLine
from production.models import (
    ProductionSession, ProductionSessionLine, BreadStock, ConsumableStock,
    ConsumableMovement, ConsumableCount, BreadTransfer, BreadTransferLine,
    BreadDisposal, DailyBreadStockSnapshot, DailyOpeningConfirmation,
    DailyOpeningConfirmationLine,
)
from treasury.models import (
    LocalExpense, FacturierReport, CashClosure, CashbookEntry, JournalEntry,
    DailySavings, DisbursementVoucher, DirectionCashCount,
)
from commissions.models import CommissionPeriod, ClientCommission
from finance.models import FinancialYear
from blockchain.models import TamperAlert, BlockchainSnapshot
from sync.models import DebtMovement, SyncBatchLog, SyncConflictLog
from core.models import ActivityLog, SystemNotification, ColisDistribution
from core.utils import log_activity


# Ordre de suppression : voir docstring du module ci-dessus pour la
# justification des contraintes PROTECT respectées par cet ordre.
_DELETION_ORDER = [
    ('sync_conflict_logs', SyncConflictLog),
    ('sync_batch_logs', SyncBatchLog),
    ('debt_movements', DebtMovement),
    ('tamper_alerts', TamperAlert),
    ('blockchain_snapshots', BlockchainSnapshot),
    ('client_commissions', ClientCommission),
    ('commission_periods', CommissionPeriod),
    ('financial_years', FinancialYear),
    ('direction_cash_counts', DirectionCashCount),
    ('cashbook_entries', CashbookEntry),
    ('journal_entries', JournalEntry),
    ('daily_savings', DailySavings),
    ('disbursement_vouchers', DisbursementVoucher),
    ('cash_closures', CashClosure),
    ('facturier_reports', FacturierReport),
    ('local_expenses', LocalExpense),
    ('consumable_movements', ConsumableMovement),
    ('consumable_stocks', ConsumableStock),
    ('consumable_counts', ConsumableCount),
    ('bread_disposals', BreadDisposal),
    ('production_session_lines', ProductionSessionLine),
    ('production_sessions', ProductionSession),
    ('bread_transfer_lines', BreadTransferLine),
    ('bread_transfers', BreadTransfer),
    ('bread_stocks', BreadStock),
    ('daily_opening_confirmation_lines', DailyOpeningConfirmationLine),
    ('daily_opening_confirmations', DailyOpeningConfirmation),
    ('daily_bread_stock_snapshots', DailyBreadStockSnapshot),
    ('invoice_lines', InvoiceLine),
    ('invoices', Invoice),
    ('social_distribution_lines', SocialDistributionLine),
    ('social_distributions', SocialDistribution),
    ('social_contributions', SocialContribution),
    ('colis_distributions', ColisDistribution),
    ('activity_logs', ActivityLog),
    ('system_notifications', SystemNotification),
]

# Phrase de confirmation exacte exigée pour le POST (anti-clic-accidentel).
CONFIRMATION_PHRASE = "SUPPRIMER TOUT"


def _clients_to_reset_queryset():
    """Clients dont au moins un champ dérivé de l'historique n'est pas déjà à sa valeur par défaut."""
    from django.db.models import Q
    return Client.objects.exclude(
        Q(current_debt=0) & Q(total_breads_received=0) & Q(category=Client.Category.NORMAL)
    )


def preview_counts():
    """
    Décompte en lecture seule de ce qui SERAIT supprimé/réinitialisé.
    Ne modifie jamais la base (utilisé par le GET d'aperçu).
    """
    counts = {key: model.objects.count() for key, model in _DELETION_ORDER}
    counts['clients_to_reset'] = _clients_to_reset_queryset().count()
    return counts


def execute_reset(user):
    """
    Supprime toutes les données listées dans `_DELETION_ORDER`, remet à
    zéro les champs dérivés de `Client`, puis journalise l'opération dans
    une NOUVELLE `ActivityLog` (la seule trace qui survit, l'historique
    précédent étant lui-même supprimé par cette opération). Tout dans une
    seule transaction : soit tout est appliqué, soit rien ne l'est.

    Renvoie le décompte de ce qui a été effectivement supprimé/réinitialisé
    (même forme que `preview_counts()`).
    """
    counts = {}
    with transaction.atomic():
        # Casse le lien self-référent Invoice.adjusts (PROTECT) avant toute
        # suppression de factures (voir docstring du module).
        Invoice.objects.update(adjusts=None)

        for key, model in _DELETION_ORDER:
            counts[key] = model.objects.count()
            model.objects.all().delete()

        counts['clients_to_reset'] = _clients_to_reset_queryset().count()
        Client.objects.update(
            current_debt=0,
            total_breads_received=0,
            category=Client.Category.NORMAL,
        )

        description = (
            "Réinitialisation globale des données (BUG-149) exécutée par "
            f"{getattr(user, 'username', 'superuser')} — "
            f"données conservées : Config, Node, User, BreadPrice, "
            f"ExpenseCategory, Client (fiches), NodeAuthToken — "
            f"décompte des éléments supprimés/réinitialisés : {counts}"
        )
        log_activity(user, 'GLOBAL_DATA_RESET', description, node_origin='CLOUD')

    return counts
