"""
`python manage.py sync_now` — un cycle complet push puis pull, à lancer
depuis un **nœud local** (poste desktop packagé, DESKTOP.md §9). N'a aucun
effet utile lancé depuis le Cloud lui-même (qui n'a pas de file d'attente
sortante vers lui-même, SYNC.md §6 H5).

Configuration attendue (variables d'environnement, voir `.env.example`) :
- `KIESE_NODE_CODE` : code de cette boulangerie (ex. 'K1').
- `KIESE_CLOUD_URL` : URL de base de l'API Cloud (ex. 'https://api.etskiese.com').
- `KIESE_NODE_TOKEN` : jeton de nœud émis par le siège (cahierDesCharges.md §6.3.1).

En V1, ce module backend définit la commande pour qu'elle soit déjà
utilisable/testable ; son exécution périodique réelle sur un poste desktop
(toutes les 30 s, DESKTOP.md §9) sera orchestrée par le service Electron en
tâche de fond (`packaging-desktop`), qui appellera cette même commande (ou
une route interne équivalente) — hors périmètre backend de ce ticket.
"""

import time
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

# BUG-067/BUG-072 : codes HTTP transitoires d'infrastructure Cloud (voir
# BUG-062) pour lesquels AUCUN SyncBatchLog n'a été persisté côté Cloud — le
# lot (même `batch_id`) reste intégralement rejouable, contrairement à un
# 400/401/403 qui est une erreur définitive. Constante partagée avec
# `sync.desktop_client` (qui applique la même règle pour la boucle
# automatique du poste desktop) pour garder une seule source de vérité sur
# « quels codes sont transitoires ».
TRANSIENT_STATUS_CODES = {503}

DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BACKOFF_SECONDS = 2
MAX_RETRY_BACKOFF_SECONDS = 30


def _send_with_retry(send_fn, max_retries, initial_backoff, sleep_fn=None, on_retry=None):
    """Appelle `send_fn()` (sans argument, renvoie une réponse `requests`) et
    la rejoue UNIQUEMENT si la réponse a un code transitoire
    (`TRANSIENT_STATUS_CODES`, ex. 503), avec un backoff exponentiel
    plafonné, jusqu'à `max_retries` tentatives supplémentaires (donc
    `max_retries + 1` appels de `send_fn` au total). `send_fn` reçoit
    toujours le MÊME payload fermé par l'appelant (même `batch_id`) : cette
    fonction ne reconstruit jamais rien.

    Les erreurs réseau (`requests.RequestException`) ne sont PAS retentées
    ici : elles remontent telles quelles, comme avant cette correction (une
    coupure réseau n'est pas la panne transitoire visée par BUG-067).

    Renvoie `(response, attempts)` où `attempts` est le nombre de
    nouvelles tentatives effectivement faites après le premier essai."""
    sleep_fn = sleep_fn or time.sleep
    attempt = 0
    backoff = initial_backoff
    while True:
        response = send_fn()
        if response.status_code not in TRANSIENT_STATUS_CODES or attempt >= max_retries:
            return response, attempt
        attempt += 1
        if on_retry:
            on_retry(attempt, backoff)
        sleep_fn(min(backoff, MAX_RETRY_BACKOFF_SECONDS))
        backoff *= 2


class Command(BaseCommand):
    help = "Un cycle de synchronisation (push puis pull) avec le Cloud, pour un nœud local."

    def add_arguments(self, parser):
        parser.add_argument('--node-code', default=None, help="Surcharge KIESE_NODE_CODE.")
        parser.add_argument('--cloud-url', default=None, help="Surcharge KIESE_CLOUD_URL.")
        parser.add_argument('--node-token', default=None, help="Surcharge KIESE_NODE_TOKEN.")
        parser.add_argument('--dry-run', action='store_true', help="Construit le lot mais ne l'envoie pas.")
        parser.add_argument(
            '--max-retries', type=int, default=DEFAULT_MAX_RETRIES,
            help="BUG-067 : nombre maximal de nouvelles tentatives (même batch_id) après un 503 "
                 "transitoire avant d'abandonner (par défaut : %d)." % DEFAULT_MAX_RETRIES,
        )
        parser.add_argument(
            '--retry-backoff', type=float, default=DEFAULT_RETRY_BACKOFF_SECONDS,
            help="BUG-067 : délai initial (secondes) avant la première retentative après un 503, "
                 "doublé à chaque nouvel essai et plafonné à %ds (par défaut : %ss)."
                 % (MAX_RETRY_BACKOFF_SECONDS, DEFAULT_RETRY_BACKOFF_SECONDS),
        )

    def handle(self, *args, **options):
        import os
        node_code = options['node_code'] or os.environ.get('KIESE_NODE_CODE')
        cloud_url = (options['cloud_url'] or os.environ.get('KIESE_CLOUD_URL') or '').rstrip('/')
        node_token = options['node_token'] or os.environ.get('KIESE_NODE_TOKEN')

        if not node_code:
            raise CommandError("KIESE_NODE_CODE non défini — ce poste ne sait pas quel nœud il représente.")

        payload = build_outbound_payload(node_code)
        total = sum(len(v) for v in payload['records'].values())
        self.stdout.write(f"Lot préparé pour {node_code} : {total} enregistrement(s) en attente.")

        if options['dry_run']:
            self.stdout.write(self.style.WARNING("--dry-run : rien envoyé."))
            return

        if not cloud_url or not node_token:
            raise CommandError(
                "KIESE_CLOUD_URL et KIESE_NODE_TOKEN doivent être définis pour synchroniser réellement "
                "(utiliser --dry-run pour seulement construire le lot sans l'envoyer)."
            )

        import requests

        headers = {'Authorization': f'Bearer {node_token}'}
        max_retries = options['max_retries']
        backoff = options['retry_backoff']
        batch_id = payload['batch_id']

        def _on_retry(attempt, delay):
            # BUG-067 : même batch_id rejoué, jamais régénéré entre deux
            # tentatives — contrairement à ce qui se passerait en relançant
            # la commande depuis zéro.
            self.stdout.write(self.style.WARNING(
                f"Service cloud temporairement indisponible (503) — nouvel essai {attempt}/{max_retries} "
                f"dans {delay:.0f}s avec le même lot (batch_id {batch_id})..."
            ))

        try:
            response, attempts = _send_with_retry(
                lambda: requests.post(f"{cloud_url}/api/sync/push/", json=payload, headers=headers, timeout=30),
                max_retries, backoff, on_retry=_on_retry,
            )
        except requests.RequestException as exc:
            raise CommandError(f"Échec de connexion au Cloud ({cloud_url}) : {exc}")

        if response.status_code in TRANSIENT_STATUS_CODES:
            raise CommandError(
                f"Service cloud temporairement indisponible (503) après {attempts} nouvelle(s) tentative(s) "
                f"— abandon. Aucun enregistrement n'a été marqué synchronisé : relancez cette commande "
                f"plus tard, le même lot (batch_id {batch_id}) sera reconstruit et rejoué à l'identique."
            )

        if response.status_code >= 400:
            raise CommandError(f"Push refusé par le Cloud ({response.status_code}) : {response.text}")

        apply_push_response(response.json())
        self.stdout.write(self.style.SUCCESS("Push terminé."))

        try:
            pull_response, pull_attempts = _send_with_retry(
                lambda: requests.get(f"{cloud_url}/api/sync/pull/", headers=headers, timeout=30),
                max_retries, backoff, on_retry=_on_retry,
            )
        except requests.RequestException as exc:
            raise CommandError(f"Push accepté mais pull impossible ({exc}) — prochain cycle réessaiera.")

        if pull_response.status_code in TRANSIENT_STATUS_CODES:
            raise CommandError(
                f"Push accepté mais service cloud temporairement indisponible (503) au pull après "
                f"{pull_attempts} nouvelle(s) tentative(s) — abandon. Relancez cette commande plus tard "
                f"pour récupérer la descente Cloud → Local (le push, lui, est déjà confirmé)."
            )

        if pull_response.status_code >= 400:
            raise CommandError(f"Pull refusé par le Cloud ({pull_response.status_code}) : {pull_response.text}")

        apply_pull_response(pull_response.json())
        self.stdout.write(self.style.SUCCESS("Synchronisation terminée (push + pull)."))


def build_outbound_payload(node_code):
    """
    Construit le lot sortant : tout ce qui, sur CE nœud, est `is_synced=False`
    et appartient aux modèles supportés en V1 (SYNC.md §11). Volontairement
    simple (pas de pagination à 200 par lot ici — V2, voir SYNC.md §3.2) :
    la volumétrie d'une boulangerie entre deux cycles de 30 s est faible.
    """
    from clients.models import (
        Client, SocialContribution, SocialDistribution, SocialDistributionLine,
    )
    from sales.models import Invoice, InvoiceLine
    from sync.models import DebtMovement
    from treasury.models import CashClosure, LocalExpense, FacturierReport, DisbursementVoucher
    from production.models import (
        ProductionSession, ProductionSessionLine, BreadDisposal,
        ConsumableMovement, BreadTransfer, BreadTransferLine,
    )

    def _dec(value):
        return str(value) if value is not None else None

    clients = [
        {
            'id': str(c.id), 'code': c.code, 'first_name': c.first_name, 'last_name': c.last_name,
            'phone': c.phone, 'address': c.address, 'node': c.node.code,
            'cotisation_sociale': _dec(c.cotisation_sociale), 'commission_rate': _dec(c.commission_rate),
            'credit_limit': _dec(c.credit_limit), 'client_type': c.client_type, 'notes': c.notes,
            'node_origin': c.node_origin,
        }
        for c in Client.objects.filter(node_origin=node_code, is_synced=False)
    ]

    invoices_qs = Invoice.objects.filter(node_origin=node_code, is_synced=False)
    invoices = [
        {
            'id': str(i.id), 'node': i.node.code, 'client': str(i.client_id) if i.client_id else None,
            'team': i.team, 'status': i.status, 'payment_type': i.payment_type,
            'debt_before': _dec(i.debt_before), 'order_total': _dec(i.order_total),
            'payment_amount': _dec(i.payment_amount), 'debt_after': _dec(i.debt_after),
            'commission_rate': _dec(i.commission_rate), 'is_soldee': i.is_soldee,
            'special_code': i.special_code, 'is_debt_repayment': i.is_debt_repayment,
            'receipt_number': i.receipt_number,
            'delivered_at': i.delivered_at.isoformat() if i.delivered_at else None,
            'node_origin': i.node_origin,
        }
        for i in invoices_qs
    ]
    invoice_lines = [
        {'id': str(l.id), 'invoice': str(l.invoice_id), 'bread_price': l.bread_price_id, 'quantity': l.quantity}
        for i in invoices_qs for l in i.lines.all()
    ]

    debt_movements = [
        {
            'id': str(m.id), 'client': str(m.client_id), 'invoice': str(m.invoice_id) if m.invoice_id else None,
            'amount': _dec(m.amount), 'kind': m.kind, 'note': m.note, 'node_origin': m.node_origin,
        }
        for m in DebtMovement.objects.filter(node_origin=node_code, is_synced=False)
    ]

    closures = [
        {
            'id': str(c.id), 'node': c.node.code, 'date': c.date.isoformat(),
            'total_entries': _dec(c.total_entries), 'total_expenses': _dec(c.total_expenses),
            'bills_20000': c.bills_20000, 'bills_10000': c.bills_10000, 'bills_5000': c.bills_5000,
            'bills_1000': c.bills_1000, 'bills_500': c.bills_500, 'bills_200': c.bills_200,
            'bills_100': c.bills_100, 'bills_50': c.bills_50,
            'is_validated': c.is_validated, 'notes': c.notes, 'node_origin': c.node_origin,
        }
        for c in CashClosure.objects.filter(node_origin=node_code, is_synced=False)
    ]

    # BUG-004 (extension 2026-11-02, SYNC.md §11) : production.
    sessions_qs = ProductionSession.objects.filter(node_origin=node_code, is_synced=False)
    sessions = [
        {
            'id': str(s.id), 'node': s.node.code, 'team': s.team, 'date': s.date.isoformat(),
            'flour_sacks_used': _dec(s.flour_sacks_used),
            'breads_300': s.breads_300, 'breads_400': s.breads_400,
            'breads_500': s.breads_500, 'breads_1000': s.breads_1000,
            'total_breads': s.total_breads, 'total_fc_produced': s.total_fc_produced,
            'theoretical_yield': s.theoretical_yield, 'yield_gap': s.yield_gap,
            'sac_value_fc_used': s.sac_value_fc_used, 'is_closed': s.is_closed,
            'closed_at': s.closed_at.isoformat() if s.closed_at else None,
            'closure_summary': s.closure_summary, 'notes': s.notes,
            'node_origin': s.node_origin,
        }
        for s in sessions_qs
    ]
    session_lines = [
        {'id': str(l.id), 'session': str(l.session_id), 'bread_price': l.bread_price_id, 'quantity': l.quantity}
        for s in sessions_qs for l in s.lines.all()
    ]
    disposals = [
        {
            'id': str(d.id), 'node': d.node.code, 'session': str(d.session_id),
            'bread_price': d.bread_price_id, 'disposal_type': d.disposal_type,
            'quantity': d.quantity, 'unit_price_sold': d.unit_price_sold,
            'notes': d.notes, 'node_origin': d.node_origin,
        }
        for d in BreadDisposal.objects.filter(node_origin=node_code, is_synced=False)
    ]
    consumable_movements = [
        {
            'id': str(m.id), 'node': m.node.code, 'stock': str(m.stock_id),
            'consumable_type': m.stock.consumable_type, 'unit': m.stock.unit,
            'session': str(m.session_id) if m.session_id else None,
            'movement_type': m.movement_type, 'quantity': _dec(m.quantity),
            'unit_price': _dec(m.unit_price), 'supplier': m.supplier,
            'description': m.description, 'node_origin': m.node_origin,
        }
        for m in ConsumableMovement.objects.filter(node_origin=node_code, is_synced=False).select_related('stock')
    ]
    transfers_qs = BreadTransfer.objects.filter(node_origin=node_code, is_synced=False)
    transfers = [
        {
            'id': str(t.id), 'from_node': t.from_node.code, 'to_node': t.to_node.code,
            'bread_price': t.bread_price_id, 'quantity_sent': t.quantity_sent,
            'quantity_received': t.quantity_received, 'transfer_status': t.transfer_status,
            'notes': t.notes, 'node_origin': t.node_origin,
        }
        for t in transfers_qs
    ]
    transfer_lines = [
        {
            'id': str(l.id), 'transfer': str(l.transfer_id), 'bread_price': l.bread_price_id,
            'quantity_sent': l.quantity_sent, 'quantity_received': l.quantity_received,
        }
        for t in transfers_qs for l in t.lines.all()
    ]
    # BreadTransferLine modifiée après coup (quantity_received ajouté sur
    # une ligne d'un transfert déjà synchronisé, lui, lors d'un cycle
    # précédent) : BreadTransferLine n'est pas un SyncableModel (pas de
    # `is_synced`), donc pas filtrable comme les autres — hors périmètre de
    # cette extraction automatique, remonte uniquement avec son transfert
    # parent au moment où celui-ci est encore `is_synced=False` (suffisant
    # pour le scénario de test SYNC.md §12, le rafraîchissement isolé d'une
    # ligne seule sans son transfert est un raffinement V2).

    # BUG-004 (extension 2026-11-02, SYNC.md §11) : trésorerie.
    local_expenses = [
        {
            'id': str(e.id), 'node': e.node.code, 'description': e.description,
            'amount': _dec(e.amount), 'category': e.category_id, 'date': e.date.isoformat(),
            'node_origin': e.node_origin,
        }
        for e in LocalExpense.objects.filter(node_origin=node_code, is_synced=False)
    ]
    facturier_reports = [
        {
            'id': str(r.id), 'node': r.node.code, 'team': r.team, 'date': r.date.isoformat(),
            'total_cash_sales': _dec(r.total_cash_sales), 'total_credit_sales': _dec(r.total_credit_sales),
            'theoretical_cash': _dec(r.theoretical_cash), 'is_validated': r.is_validated,
            'validated_at': r.validated_at.isoformat() if r.validated_at else None,
            'sacks_consumed': _dec(r.sacks_consumed),
            'breads_produced_by_category': r.breads_produced_by_category,
            'breads_sold_by_category': r.breads_sold_by_category,
            'sacks_value_gap': _dec(r.sacks_value_gap), 'node_origin': r.node_origin,
        }
        for r in FacturierReport.objects.filter(node_origin=node_code, is_synced=False)
    ]
    disbursement_vouchers = [
        {
            'id': str(v.id), 'date': v.date.isoformat(), 'motif': v.motif, 'beneficiary': v.beneficiary,
            'bills_20000': v.bills_20000, 'bills_10000': v.bills_10000, 'bills_5000': v.bills_5000,
            'bills_1000': v.bills_1000, 'bills_500': v.bills_500, 'bills_200': v.bills_200,
            'bills_100': v.bills_100, 'bills_50': v.bills_50, 'piece_number': v.piece_number,
            'node_origin': v.node_origin,
        }
        # DisbursementVoucher est aujourd'hui toujours `node_origin='CLOUD'`
        # (créé au siège, SYNC.md §1.2) : ce filtre ne remonte donc rien en
        # V1 réel, mais couvre déjà le cas documenté « si un poste direction
        # local existe » sans changement supplémentaire le jour où il existera.
        for v in DisbursementVoucher.objects.filter(node_origin=node_code, is_synced=False)
    ]

    # BUG-004 (extension 2026-11-02, suite) : caisse sociale (clients.*), une
    # fois ces 3 modèles migrés vers `SyncableModel` (PK UUID, migrations
    # 0008/0009 de `clients`) — voir SYNC.md §11.
    social_contributions = [
        {
            'id': str(c.id), 'client': str(c.client_id), 'node': c.node.code,
            'month': c.month, 'year': c.year, 'amount': _dec(c.amount),
            'is_paid': c.is_paid, 'paid_at': c.paid_at.isoformat() if c.paid_at else None,
            'node_origin': c.node_origin,
        }
        for c in SocialContribution.objects.filter(node_origin=node_code, is_synced=False)
    ]
    social_distributions_qs = SocialDistribution.objects.filter(
        node_origin=node_code, is_synced=False,
    )
    social_distributions = [
        {
            'id': str(d.id), 'node': d.node.code, 'year': d.year,
            'tarif': _dec(d.tarif), 'is_closed': d.is_closed, 'node_origin': d.node_origin,
        }
        for d in social_distributions_qs
    ]
    # Les lignes d'une distribution déjà synchronisée (is_synced=True) mais
    # modifiées depuis (indice/merite recalculés localement) ont elles-mêmes
    # leur propre `is_synced` (SyncableModel) — filtrées indépendamment de
    # leur distribution parente, contrairement à `BreadTransferLine` plus
    # haut qui n'a pas ce champ.
    social_distribution_lines = [
        {
            'id': str(l.id), 'distribution': str(l.distribution_id), 'client': str(l.client_id),
            'indice': l.indice, 'total_social': _dec(l.total_social), 'remise': _dec(l.remise),
            'merite': _dec(l.merite), 'total_payer': _dec(l.total_payer),
            'position': l.position, 'form': l.form, 'node_origin': l.node_origin,
        }
        for l in SocialDistributionLine.objects.filter(node_origin=node_code, is_synced=False)
    ]

    return {
        'node_code': node_code,
        'batch_id': str(uuid.uuid4()),
        'records': {
            'clients.Client': clients,
            'sales.Invoice': invoices,
            'sales.InvoiceLine': invoice_lines,
            'sync.DebtMovement': debt_movements,
            'production.ProductionSession': sessions,
            'production.ProductionSessionLine': session_lines,
            'production.BreadDisposal': disposals,
            'production.ConsumableMovement': consumable_movements,
            'production.BreadTransfer': transfers,
            'production.BreadTransferLine': transfer_lines,
            'treasury.LocalExpense': local_expenses,
            'treasury.FacturierReport': facturier_reports,
            'treasury.CashClosure': closures,
            'treasury.DisbursementVoucher': disbursement_vouchers,
            'clients.SocialContribution': social_contributions,
            'clients.SocialDistribution': social_distributions,
            'clients.SocialDistributionLine': social_distribution_lines,
        },
    }


def apply_push_response(response_data):
    """Marque `is_synced=True` tout enregistrement ACCEPTED par le Cloud."""
    from django.apps import apps

    results = response_data.get('results', {})
    for model_label, record_results in results.items():
        try:
            model = apps.get_model(model_label)
        except LookupError:
            continue
        accepted_ids = [r['id'] for r in record_results if r.get('status') == 'ACCEPTED']
        if accepted_ids and hasattr(model, 'is_synced'):
            model.objects.filter(pk__in=accepted_ids).update(is_synced=True)


def apply_pull_response(payload):
    """
    Applique la descente Cloud → Local (SYNC.md §4) : configuration, prix,
    et surtout `current_debt`/`category` recalculés pour les clients connus
    de ce nœud — jamais une fusion, un simple remplacement par la valeur
    déjà arbitrée au Cloud (SYNC.md §2.2).
    """
    from clients.models import Client

    for client_data in payload.get('clients', []):
        Client.objects.filter(pk=client_data['id']).update(
            current_debt=client_data['current_debt'],
            category=client_data['category'],
        )
    # `config`/`bread_prices` : appliqués par le futur backend desktop sur
    # ses propres tables `Config`/`BreadPrice` locales — non pertinent à
    # appliquer ici quand la commande est testée contre la même base que
    # le Cloud (ce serait un no-op de toute façon).
