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

        # BUG-784 : curseur du dernier pull appliqué (persisté), pour ne
        # redescendre que les clients modifiés depuis.
        from sync.desktop_client import load_pull_cursor, save_pull_cursor
        data_dir = getattr(settings, 'KIESE_DATA_DIR', None)
        pull_params = load_pull_cursor(data_dir, cloud_url, node_code)

        try:
            pull_response, pull_attempts = _send_with_retry(
                lambda: requests.get(f"{cloud_url}/api/sync/pull/", headers=headers, timeout=30,
                                     params=pull_params),
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

        pull_data = pull_response.json()
        apply_pull_response(pull_data)
        save_pull_cursor(data_dir, cloud_url, pull_data, node_code)
        self.stdout.write(self.style.SUCCESS("Synchronisation terminée (push + pull)."))


def build_outbound_payload(node_code):
    """
    Construit le lot sortant : tout ce qui, sur CE nœud, est `is_synced=False`
    et appartient aux modèles supportés en V1 (SYNC.md §11). Volontairement
    simple (pas de pagination à 200 par lot ici — V2, voir SYNC.md §3.2) :
    la volumétrie d'une boulangerie entre deux cycles de 30 s est faible.
    """
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    from clients.models import (
        Client, SocialContribution, SocialDistribution, SocialDistributionLine,
    )
    from sales.models import Invoice, InvoiceLine
    from sync.models import DebtMovement
    from treasury.models import CashClosure, LocalExpense, FacturierReport, DisbursementVoucher
    from production.models import (
        ProductionSession, ProductionSessionLine, BreadDisposal,
        ConsumableMovement, BreadTransfer, BreadTransferLine, ConsumableInventory, ConsumableCount,
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
            # BUG-970 : versions pour la garde « dernier écrivain gagne » du push d'identité.
            'updated_at': c.updated_at.isoformat() if c.updated_at else None,
            'identity_updated_at': c.identity_updated_at.isoformat() if c.identity_updated_at else None,
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
        {'id': str(l.id), 'invoice': str(l.invoice_id), 'bread_price': l.bread_price_id, 'quantity': l.quantity,
         'unit_price': _dec(l.unit_price), 'full_unit_price': _dec(l.full_unit_price)}
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
            'resubmit_count': c.resubmit_count,
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
        {'id': str(l.id), 'session': str(l.session_id), 'bread_price': l.bread_price_id, 'quantity': l.quantity,
         'source': l.source}
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
    # BUG-386 : inventaire physique journalier (en-tête) + ses lignes
    # (`ConsumableCount` n'a pas `is_synced` : elles remontent avec leur
    # inventaire tant que celui-ci est `is_synced=False`, rejeu idempotent).
    inventories_qs = ConsumableInventory.objects.filter(node_origin=node_code, is_synced=False)
    consumable_inventories = [
        {
            'id': str(i.id), 'node': i.node.code, 'inventory_date': i.inventory_date.isoformat(),
            'comment': i.comment, 'node_origin': i.node_origin,
        }
        for i in inventories_qs.select_related('node')
    ]
    consumable_counts = [
        {
            'node': l.node.code, 'inventory': str(l.inventory_id),
            'consumable_type': l.consumable_type, 'count_date': l.count_date.isoformat(),
            'system_quantity': _dec(l.system_quantity), 'physical_quantity': _dec(l.physical_quantity),
            'gap': _dec(l.gap), 'notes': l.notes,
        }
        for i in inventories_qs for l in i.lines.select_related('node')
    ]
    # BUG-626 : comptages historiques (sans inventaire) non encore synchronisés.
    # `id` = clé locale entière, renvoyée telle quelle par le Cloud pour le marquage.
    consumable_counts += [
        {
            'id': str(l.pk), 'node': l.node.code, 'inventory': None,
            'consumable_type': l.consumable_type, 'count_date': l.count_date.isoformat(),
            'system_quantity': _dec(l.system_quantity), 'physical_quantity': _dec(l.physical_quantity),
            'gap': _dec(l.gap), 'notes': l.notes,
        }
        for l in ConsumableCount.objects.filter(
            node__code=node_code, inventory__isnull=True, is_synced=False,
        ).select_related('node')
    ]
    # BUG-965 : un poste exporte aussi les transferts dont il est émettrice OU réceptrice
    # (sa validation/ses écarts doivent remonter), pas seulement ceux qu'il a créés.
    # Les restrictions de rôle du push (BUG-874/888/891) restent appliquées côté cloud.
    transfers_qs = BreadTransfer.objects.filter(
        Q(node_origin=node_code) | Q(from_node__code=node_code) | Q(to_node__code=node_code),
        is_synced=False,
    ).select_related('from_node', 'to_node').distinct()
    transfers = [
        {
            'id': str(t.id), 'from_node': t.from_node.code, 'to_node': t.to_node.code,
            'bread_price': t.bread_price_id, 'quantity_sent': t.quantity_sent,
            'quantity_received': t.quantity_received, 'transfer_status': t.transfer_status,
            'flow': t.flow,  # BUG-977
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
            # BUG-959 : facturier exporté (deux facturiers possibles par équipe/jour) ;
            # un cloud ancien l'ignore, un poste ancien sans la clé reste accepté.
            'facturier': str(r.facturier_id) if r.facturier_id else None,
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

    # BUG-980 : transferts non terminaux que ce poste connaît (rattrapage du cloud > 30 jours).
    open_transfers = [
        str(i) for i in BreadTransfer.objects.filter(
            Q(from_node__code=node_code) | Q(to_node__code=node_code),
        ).exclude(transfer_status__in=_TRANSFER_DONE).values_list('id', flat=True)[:1000]
    ]

    # BUG-989/990 : miroir de stock appliqué par CE poste (l'état de ses lignes locales tient lieu
    # de marqueur) : émettrice = quantité envoyée déduite ; réceptrice = quantité reçue créditée.
    # Hors `records`, donc hors empreinte du lot. Borné (500 transferts, 30 derniers jours / ouverts).
    mirrors = {}
    mirror_qs = BreadTransfer.objects.filter(
        Q(from_node__code=node_code) | Q(to_node__code=node_code),
    ).filter(
        Q(updated_at__gte=timezone.now() - timedelta(days=30)) | ~Q(transfer_status__in=_TRANSFER_DONE),
    ).select_related('from_node', 'to_node').prefetch_related('lines').order_by('-updated_at')[:500]
    for t in mirror_qs:
        is_from = t.from_node.code == node_code
        deducted = t.transfer_status in ('RESPONDED', 'DISPUTED', 'CONFIRMED')
        mirrors[str(t.id)] = {
            str(l.bread_price_id): [
                (l.quantity_sent if (is_from and deducted) else 0),
                (0 if is_from else (l.quantity_received or 0)),
            ]
            for l in t.lines.all()
        }

    return {
        'node_code': node_code,
        'batch_id': str(uuid.uuid4()),
        'open_transfers': open_transfers,
        'mirrors': mirrors,
        'records': {
            'clients.Client': clients,
            'sales.Invoice': invoices,
            'sales.InvoiceLine': invoice_lines,
            'sync.DebtMovement': debt_movements,
            'production.ProductionSession': sessions,
            'production.ProductionSessionLine': session_lines,
            'production.BreadDisposal': disposals,
            'production.ConsumableMovement': consumable_movements,
            'production.ConsumableInventory': consumable_inventories,
            'production.ConsumableCount': consumable_counts,
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

    from sync.services import _strict_uuid

    # BUG-733 : une réponse Cloud tronquée, ancienne ou hostile ne doit jamais
    # interrompre le cycle : entrées invalides ignorées, rien marqué à tort.
    results = response_data.get('results') if isinstance(response_data, dict) else None
    if not isinstance(results, dict):
        return

    # BUG-731 : un inventaire dont au moins une ligne a été REJETÉE n'est pas
    # marqué synchronisé : la ligne rejetée doit rester renvoyable.
    blocked_inventories = set()
    count_results = results.get('production.ConsumableCount')
    if isinstance(count_results, list):
        for r in count_results:
            if isinstance(r, dict) and r.get('status') != 'ACCEPTED':
                inv = _strict_uuid(r.get('inventory'))
                if inv is not None:
                    blocked_inventories.add(inv)

    for model_label, record_results in results.items():
        if not isinstance(record_results, list):
            continue
        try:
            model = apps.get_model(model_label)
        except (LookupError, ValueError):
            continue
        if not hasattr(model, 'is_synced'):
            continue
        if model_label == 'production.ConsumableCount':
            # BUG-626 : clé locale entière (comptages historiques sans inventaire).
            int_ids = [
                int(r['id']) for r in record_results
                if isinstance(r, dict) and r.get('status') == 'ACCEPTED' and not r.get('inventory')
                and isinstance(r.get('id'), str) and r['id'].isascii() and r['id'].isdigit()
                and len(r['id']) <= 12
            ]
            if int_ids:
                model.objects.filter(pk__in=int_ids, inventory__isnull=True).update(is_synced=True)
            continue
        accepted_ids = []
        for r in record_results:
            if not isinstance(r, dict) or r.get('status') != 'ACCEPTED':
                continue
            rid = _strict_uuid(r.get('id'))
            if rid is None:
                continue
            if model_label == 'production.ConsumableInventory' and rid in blocked_inventories:
                continue
            accepted_ids.append(rid)
        if accepted_ids:
            model.objects.filter(pk__in=accepted_ids).update(is_synced=True)


_TRANSFER_RANK = {'PENDING': 0, 'RESPONDED': 1, 'DISPUTED': 2, 'CONFIRMED': 3, 'CANCELLED': 3}
_TRANSFER_DONE = ('CONFIRMED', 'CANCELLED')


def _local_node_code(payload):
    """Code du poste : `node_code` de la réponse du cloud (identité du jeton), à défaut
    `KIESE_NODE_CODE`. Sans code, aucun effet de stock ni alerte n'est appliqué."""
    import os
    code = payload.get('node_code') if isinstance(payload, dict) else None
    if isinstance(code, str) and code:
        return code
    return os.environ.get('KIESE_NODE_CODE') or None


def _apply_pulled_transfers(transfers, lines, local_code=None, mirrors=None):
    """BUG-964/975/976/978/979 : applique les transferts descendus du cloud (émetteur OU récepteur).

    Contrat (SYNC.md §5.3) :
    - Transfert inconnu localement : créé (`is_synced=True`, statut et `flow` du cloud), lignes
      créées SANS mouvement de stock (copie d'un état ; un poste réinstallé ne rejoue pas
      l'historique) ; alerte locale « Demande de Pains » (émettrice, PENDING) ou « Pains Envoyés »
      (réceptrice, RESPONDED) régénérée ici car les `SystemNotification` ne sont pas synchronisées.
    - Transfert connu : jamais de régression de statut ; jamais écrasé s'il a une modification
      locale non poussée (`is_synced=False`) ni s'il est déjà terminé localement.
      Les lignes sont appliquées dès que le statut cloud est >= au statut local (BUG-979 :
      lignes manquantes créées, quantités reçues/envoyées mises à jour même à statut égal).
    - Stock miroir (BUG-976) : appliqué par DELTA entre la ligne locale et la ligne cloud, dans la
      même transaction que l'écriture de la ligne. La ligne locale est donc le marqueur
      d'application : un second pull identique donne un delta nul (aucun double mouvement) ;
      les actions REST locales, qui écrivent la ligne en même temps que le stock, restent cohérentes.
        * réceptrice : `received += quantité_reçue_cloud - quantité_reçue_locale` ;
        * émettrice : `sent += quantité_envoyée_cloud - quantité_envoyée_locale`, seulement si
          la copie locale était déjà « envoyée » (RESPONDED/DISPUTED : stock déjà déduit).
    Les entrées invalides sont ignorées silencieusement (BUG-781).

    BUG-989 à 992 (contrat d43) :
    - Transfert INCONNU et `mirrors` présent dans la réponse (cloud récent) : la copie est créée
      puis le stock est appliqué par différence avec le marqueur du cloud pour (transfert, ce poste)
      (absent = rien d'appliqué) : un envoi jamais vu est crédité/déduit une fois ; un poste
      réinstallé qui rejoue l'historique (marqueur = état déjà appliqué) n'applique rien.
      `mirrors` absent (cloud ancien) : ancien comportement, copie sans mouvement de stock.
    - Émettrice : la déduction est due dès que le statut cloud est RESPONDED/DISPUTED/CONFIRMED
      (y compris sur passage PENDING -> RESPONDED décidé au siège : BUG-990) ; elle est restituée
      si le cloud est CANCELLED (BUG-992). Delta = (envoyé cloud si déduit) - (envoyé local si déjà déduit).
    - Copie locale CANCELLED et acquittée (`is_synced`) alors que le cloud est RESPONDED/DISPUTED/
      CONFIRMED : conflit perdu (BUG-992), le cloud prévaut et le poste se réaligne.
    """
    from django.db import transaction

    from core.models import BreadPrice, Node
    from core.utils import create_notification
    from production.models import BreadTransfer, BreadTransferLine, _adjust_bread_stock
    from sync.services import _strict_uuid, _sync_bounded_qty

    if not isinstance(transfers, list):
        return
    rank = _TRANSFER_RANK
    new_mode = isinstance(mirrors, dict)
    lines_by_transfer = {}
    for ld in lines if isinstance(lines, list) else []:
        if isinstance(ld, dict):
            lines_by_transfer.setdefault(str(ld.get('transfer')), []).append(ld)
    for td in transfers:
        if not isinstance(td, dict):
            continue
        tid = _strict_uuid(td.get('id'))
        status = td.get('transfer_status')
        if tid is None or status not in rank:
            continue
        qsent = None if td.get('quantity_sent') is None else _sync_bounded_qty(td['quantity_sent'])
        qrecv = None if td.get('quantity_received') is None else _sync_bounded_qty(td['quantity_received'])
        with transaction.atomic():
            local = BreadTransfer.objects.select_for_update().filter(pk=tid).first()
            created = local is None
            old_status = None
            if created:
                from_node = Node.objects.filter(code=td.get('from_node')).first()
                to_node = Node.objects.filter(code=td.get('to_node')).first()
                if from_node is None or to_node is None or from_node.pk == to_node.pk:
                    continue
                bp = td.get('bread_price')
                local = BreadTransfer(
                    id=tid, from_node=from_node, to_node=to_node,
                    bread_price=BreadPrice.objects.filter(pk=bp).first() if isinstance(bp, int) else None,
                    quantity_sent=qsent, quantity_received=qrecv, transfer_status=status,
                    flow=td.get('flow') if td.get('flow') in BreadTransfer.Flow.values else BreadTransfer.Flow.REQUEST,
                    notes=td.get('notes') if isinstance(td.get('notes'), str) else '',
                    node_origin=td.get('node_origin') if isinstance(td.get('node_origin'), str) else from_node.code,
                    is_synced=True,
                )
                local.save(_sync_bypass=True)
            else:
                lost_conflict = (local.transfer_status == 'CANCELLED' and local.is_synced
                                 and status in ('RESPONDED', 'DISPUTED', 'CONFIRMED'))
                if (not local.is_synced
                        or (local.transfer_status in _TRANSFER_DONE and not lost_conflict)
                        or (rank[status] < rank[local.transfer_status] and not lost_conflict)):
                    continue
                old_status = local.transfer_status
                if rank[status] > rank[old_status] or lost_conflict:
                    local.transfer_status = status
                    local.quantity_received = qrecv
                    local.save(update_fields=['transfer_status', 'quantity_received', 'is_synced'],
                               _sync_bypass=True)
            is_to = bool(local_code) and local.to_node.code == local_code
            is_from = bool(local_code) and local.from_node.code == local_code
            before = old_status in ('RESPONDED', 'DISPUTED')   # stock émettrice déjà déduit (copie locale)
            after = status in ('RESPONDED', 'DISPUTED', 'CONFIRMED')
            marker = mirrors.get(str(tid)) if (created and new_mode) else None
            for ld in lines_by_transfer.get(str(tid), []):
                bp = ld.get('bread_price')
                if not isinstance(bp, int) or isinstance(bp, bool):
                    continue
                price = BreadPrice.objects.filter(pk=bp).first()
                ls, lr = _sync_bounded_qty(ld.get('quantity_sent')), (
                    None if ld.get('quantity_received') is None else _sync_bounded_qty(ld['quantity_received']))
                if price is None or ls is None:
                    continue
                line = BreadTransferLine.objects.select_for_update().filter(transfer=local, bread_price=price).first()
                if line is None:
                    BreadTransferLine.objects.create(
                        transfer=local, bread_price=price, quantity_sent=ls, quantity_received=lr)
                    base_sent, base_recv, new_recv = 0, 0, lr
                    if created:   # déjà appliqué selon le marqueur du cloud (BUG-989)
                        pair = marker.get(str(bp)) if isinstance(marker, dict) else None
                        if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(
                                isinstance(v, int) and not isinstance(v, bool) for v in pair):
                            base_sent, base_recv = pair
                else:
                    new_recv = line.quantity_received if lr is None else lr
                    base_sent, base_recv = (line.quantity_sent if before else 0), (line.quantity_received or 0)
                    if ls != line.quantity_sent or new_recv != line.quantity_received:
                        line.quantity_sent, line.quantity_received = ls, new_recv
                        line.save(update_fields=['quantity_sent', 'quantity_received'])
                if created and not new_mode:
                    continue  # cloud ancien : copie d'un état, pas de mouvement de stock
                d_sent, d_recv = (ls if after else 0) - base_sent, (new_recv or 0) - base_recv
                if is_to and d_recv:
                    _adjust_bread_stock(local.to_node, price, received=d_recv)
                if is_from and d_sent:
                    _adjust_bread_stock(local.from_node, price, sent=d_sent)

            # BUG-978 : alertes régénérées localement (une fois : la création ou l'avance de
            # statut n'a lieu qu'une fois par poste ; un rejeu n'avance plus rien).
            if local_code and is_from and old_status == 'CANCELLED' and status != 'CANCELLED':
                create_notification(
                    title=f"Conflit Transfert — {local.from_node.code}→{local.to_node.code}",
                    message=("Votre refus local est arrivé après la réponse du siège : "
                             "la réponse du siège prévaut, le stock a été ajusté en conséquence."),
                    severity='WARNING', node_origin=local.from_node.code)
            elif local_code and (is_to or is_from) and (created or rank[status] > rank[old_status]):
                lines_txt = ', '.join(
                    f"{l.quantity_sent}×{l.bread_price.label}"
                    for l in local.lines.select_related('bread_price')) or '—'
                f_code, t_code = local.from_node.code, local.to_node.code
                if is_from and status == 'PENDING' and created:
                    create_notification(
                        title=f"Demande de Pains — {f_code}",
                        message=(f"La boulangerie {t_code} vous demande {lines_txt}. "
                                 f"Veuillez répondre à cette demande (accepter ou refuser)."),
                        severity='INFO', node_origin=f_code)
                elif is_to and status == 'RESPONDED':
                    create_notification(
                        title=f"Pains Envoyés — {t_code}",
                        message=(f"La boulangerie {f_code} vous envoie {lines_txt}. "
                                 f"Veuillez confirmer la réception."),
                        severity='INFO', node_origin=t_code)
                elif is_from and status == 'DISPUTED':
                    create_notification(
                        title=f"Litige Transfert — {f_code}→{t_code}",
                        message=f"Écart détecté à la réception. {lines_txt}.",
                        severity='DANGER', node_origin=f_code)
                elif status == 'CONFIRMED' and old_status == 'DISPUTED':
                    create_notification(
                        title=f"Litige Transfert résolu — {f_code}→{t_code}",
                        message="Le litige a été résolu au siège ou par l'autre boulangerie.",
                        severity='INFO', node_origin=local_code)
                elif is_to and status == 'CANCELLED':
                    create_notification(
                        title=f"Demande Refusée — {t_code}",
                        message=f"La boulangerie {f_code} n'a pas le stock disponible pour votre demande.",
                        severity='WARNING', node_origin=t_code)


def _apply_pulled_closures(closures, local_code):
    """BUG-983 : applique l'état (confirmée / infirmée + motif) des clôtures de CE poste,
    sans jamais toucher aux montants ni au billetage. Entrées invalides ignorées. Une
    resoumission locale pas encore poussée n'est pas ré-infirmée par un pull plus ancien."""
    from django.db import transaction

    from sync.services import _strict_uuid
    from treasury.models import CashClosure

    if not isinstance(closures, list):
        return
    for item in closures:
        if not isinstance(item, dict):
            continue
        cid = _strict_uuid(item.get('id'))
        validated, rejected = item.get('is_validated'), item.get('is_rejected')
        reason = item.get('rejection_reason', '')
        if cid is None or not isinstance(validated, bool) or not isinstance(rejected, bool)                 or not isinstance(reason, str):
            continue
        with transaction.atomic():
            local = CashClosure.objects.select_for_update().filter(pk=cid).first()
            if local is None or (local_code and local.node.code != local_code):
                continue
            if not local.is_synced and not local.is_rejected and rejected and not validated:
                continue  # resoumission locale en attente de push
            CashClosure.objects.filter(pk=cid).update(
                is_validated=validated, is_rejected=rejected, rejection_reason=reason[:2000])


def apply_pull_response(payload):
    """
    Applique la descente Cloud → Local (SYNC.md §4) : configuration, prix,
    et surtout `current_debt`/`category` recalculés pour les clients connus
    de ce nœud — jamais une fusion, un simple remplacement par la valeur
    déjà arbitrée au Cloud (SYNC.md §2.2).
    """
    from decimal import Decimal, InvalidOperation

    from django.db import transaction

    from clients.models import Client
    from sync.models import DebtMovement
    from sync.services import MAX_DEBT_ABS, _strict_uuid

    # BUG-781 : une réponse tronquée ou hostile ne doit jamais lever
    # d'exception : entrées invalides ignorées, rien d'écrit à tort.
    if isinstance(payload, dict):
        _apply_pulled_transfers(payload.get('transfers'), payload.get('transfer_lines'),
                                _local_node_code(payload), payload.get('mirrors'))
    if isinstance(payload, dict):
        _apply_pulled_closures(payload.get('closures'), _local_node_code(payload))
    clients = payload.get('clients') if isinstance(payload, dict) else None
    if not isinstance(clients, list):
        return
    for client_data in clients:
        if not isinstance(client_data, dict):
            continue
        client_id = _strict_uuid(client_data.get('id'))
        category = client_data.get('category')
        if client_id is None or category not in Client.Category.values:
            continue
        raw_debt = client_data.get('current_debt')
        if isinstance(raw_debt, bool) or raw_debt is None:
            continue
        try:
            debt = Decimal(str(raw_debt))
        except InvalidOperation:
            continue
        if not debt.is_finite() or abs(debt) >= MAX_DEBT_ABS:
            continue
        with transaction.atomic():
            # BUG-780 : un mouvement local pas encore poussé n'est pas dans la
            # valeur Cloud : écraser la dette locale la ferait redescendre et
            # fausserait BP et plafond. Le client est ignoré ; une fois le
            # mouvement poussé, la dette Cloud le contient et un prochain pull
            # (curseur `updated_at` du Cloud) la redescend.
            if DebtMovement.objects.filter(client_id=client_id, is_synced=False).exists():
                continue
            locked = Client.objects.select_for_update().filter(pk=client_id).first()
            if locked is None:
                continue
            old_category = locked.category
            locked.current_debt = debt.quantize(Decimal('0.01'))
            fields = ['current_debt', 'category']
            # BUG-952 : une édition locale d'identité/plafond pas encore poussée
            # (is_synced=False et identity_updated_at renseigné) n'est jamais écrasée
            # par le pull ; elle sera poussée ensuite (le propriétaire fait autorité,
            # SYNC.md §5.1). La dette, elle, est toujours appliquée.
            local_edit_pending = (not locked.is_synced) and locked.identity_updated_at is not None
            # BUG-942 : plafond et identité du Cloud appliqués (valeurs invalides ignorées).
            limit = client_data.get('credit_limit')
            if local_edit_pending:
                limit = None
            elif limit is not None and not isinstance(limit, bool):
                try:
                    limit = Decimal(str(limit))
                except InvalidOperation:
                    limit = None
                if limit is not None and limit.is_finite() and Decimal('0') <= limit <= Decimal('10000000'):
                    locked.credit_limit = limit.quantize(Decimal('0.01'))
                    fields.append('credit_limit')
                else:
                    limit = None
            else:
                limit = None
            for name, max_len in (('first_name', 100), ('last_name', 100), ('phone', 25), ('address', None)):
                val = None if local_edit_pending else client_data.get(name)
                if isinstance(val, str) and (max_len is None or len(val) <= max_len) \
                        and (name not in ('first_name', 'last_name') or val.strip()):
                    setattr(locked, name, val)
                    fields.append(name)
            locked.category = category
            if local_edit_pending:
                locked.refresh_category()  # catégorie sur le plafond LOCAL conservé
            elif limit is not None:
                # La catégorie doit rester cohérente avec le plafond appliqué.
                if locked.current_debt >= locked.credit_limit:
                    locked.category = Client.Category.RISK
                elif category == Client.Category.RISK:
                    locked.refresh_category()
            locked.save(update_fields=fields, _sync_bypass=True)
            locked.notify_risk_transition(old_category)
    # `config`/`bread_prices` : appliqués par le futur backend desktop sur
    # ses propres tables `Config`/`BreadPrice` locales — non pertinent à
    # appliquer ici quand la commande est testée contre la même base que
    # le Cloud (ce serait un no-op de toute façon).
