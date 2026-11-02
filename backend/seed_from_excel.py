"""
Seed script — ETS. KIESE
Supprime la DB existante, réinitialise et importe les données réelles d'août 2026
à partir des fichiers Excel dans ./data_kiese/.

Usage (depuis d:\Projects\kiesse\backend\) :
    python seed_from_excel.py

Structure attendue :
    ../data_kiese/DOC 01- RAPPORT  BOULANGERIES AOUT  2026.xlsx
    ../data_kiese/daja_analysé/K1 AOUT 26 *.xlsx  (et K2–K6, B1, B2)
"""

import os
import sys
import django
from decimal import Decimal
from pathlib import Path

# ── Django setup ─────────────────────────────────────────────────────────────
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kiese.settings')
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
django.setup()

# ── Imports après setup ──────────────────────────────────────────────────────
from datetime import date, datetime
from django.db import connection, transaction

import openpyxl

# ── Constantes ───────────────────────────────────────────────────────────────
DATA_DIR = BASE_DIR.parent / 'data_kiese'
DOC01_PATH = DATA_DIR / 'DOC 01- RAPPORT  BOULANGERIES AOUT  2026.xlsx'

NODES_CFG = [
    ('K1', 'TABORA',  'TABORA'),
    ('K2', 'COQ',     'COQ'),
    ('K3', 'ATHENEE', 'ATHENEE'),
    ('K4', 'LOMA',    'LOMA'),
    ('K5', 'MPIANGU', 'MPIANGU'),
    ('K6', 'ZADIM',   'ZADIM'),
    ('B1', 'KUMBI',   'KUMBI'),
    ('B2', 'MPETE',   'MPETE'),
]

SHEET_TO_NODE = {
    'TABORA': 'K1', 'COQ': 'K2', 'ATHENEE': 'K3', 'LOMA': 'K4',
    'MPIANGU': 'K5', 'ZADIM': 'K6', 'KUMBI': 'B1', 'MPETE': 'B2',
}

SAVINGS_RATE = Decimal('0.1580')
COMMISSION_RATE = Decimal('0.25')

# ── DOC 01 column mapping (1-indexed for ws.cell) ────────────────────────────
# formula: D*E + F*G + H*I + J*K
# D=col4=qty200, E=col5=price200, F=col6=qty300, G=col7=price300
# H=col8=qty500, I=col9=price500, J=col10=qty1000, K=col11=price1000
# L=col12=total, M=col13=taux, N=col14=cm, O=col15=paiement, P=col16=site_pmt
COL_QTY200 = 4
COL_QTY300 = 6
COL_QTY500 = 8
COL_QTY1000 = 10
COL_TOTAL = 12
COL_TAUX = 13
COL_PAIEMENT = 15
COL_SITE_PMT = 16

SKIP_NAMES = frozenset(['VENTE SOLDE', 'VENTE CASH'])

# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 0 — NETTOYAGE DE LA BASE
# ═══════════════════════════════════════════════════════════════════════════════

def flush_database():
    """Vide toutes les tables applicatives (préserve les tables Django admin)."""
    print('→ Nettoyage de la base de données…')
    from django.contrib.contenttypes.models import ContentType
    from django.contrib.auth.models import Permission

    # Suppression dans l'ordre inverse des dépendances
    tables_to_clear = [
        'commissions_clientcommission',
        'commissions_commissionperiod',
        'sales_invoiceline',
        'sales_invoice',
        'clients_socialdistributionline',
        'clients_socialdistribution',
        'clients_socialcontribution',
        'clients_client',
        'treasury_dailysavings',
        'treasury_journalentry',
        'treasury_cashbookentry',
        'treasury_cashclosure',
        'treasury_facturierreport',
        'treasury_localexpense',
        'production_consumablemovement',
        'production_consumablecount',
        'production_consumablestock',
        'finance_financialyear',
        'core_colisdistribution',
        'core_systemnotification',
        'core_activitylog',
        'core_breadprice',
        'core_config',
        'core_user',
        'core_node',
    ]
    with connection.cursor() as cursor:
        for table in tables_to_clear:
            try:
                cursor.execute(f'DELETE FROM {table}')
                print(f'   cleared {table}')
            except Exception as e:
                print(f'   skip {table}: {e}')
    print('   Base nettoyée.')


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 1 — INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════════════════════

def create_infrastructure():
    from core.models import Node, User, Config, BreadPrice

    print('\n→ Création des nœuds (boulangeries)…')
    nodes = {}
    for code, name, _ in NODES_CFG:
        node = Node.objects.create(
            code=code, name=name,
            address=f'Kinshasa — Boulangerie {code}',
            sac_value_fc=Decimal('200000'),
            is_active=True,
        )
        nodes[code] = node
        print(f'   {node}')

    print('\n→ Création des utilisateurs…')
    # Admin / Direction
    admin = User.objects.create_superuser(
        username='admin', password='admin2026',
        first_name='Admin', last_name='Système',
        email='admin@kiese.cd', role='ADMIN',
    )
    direction = User.objects.create_user(
        username='direction', password='direction2026',
        first_name='Direction', last_name='Générale',
        email='direction@kiese.cd', role='DIRECTION',
    )
    comptable = User.objects.create_user(
        username='comptable', password='comptable2026',
        first_name='Comptable', last_name='DAF',
        email='comptable@kiese.cd', role='COMPTABLE',
    )
    gerants = {}
    gerant_names = {
        'K1': ('Gérant', 'TABORA K1'),
        'K2': ('Gérant', 'COQ K2'),
        'K3': ('Gérant', 'ATHENEE K3'),
        'K4': ('Gérant', 'LOMA K4'),
        'K5': ('Gérant', 'MPIANGU K5'),
        'K6': ('Gérant', 'ZADIM K6'),
        'B1': ('Gérant', 'KUMBI B1'),
        'B2': ('Gérant', 'MPETE B2'),
    }
    for code, (fn, ln) in gerant_names.items():
        g = User.objects.create_user(
            username=f'gerant_{code.lower()}',
            password=f'gerant2026',
            first_name=fn, last_name=ln,
            role='GERANT', node=nodes[code],
        )
        gerants[code] = g
        print(f'   gérant {code}: {g.username}')

    print('\n→ Configuration globale…')
    config = Config.get_instance()
    config.savings_rate = SAVINGS_RATE
    config.default_commission_rate = COMMISSION_RATE
    config.social_deduction_rate = Decimal('0.00')
    config.print_fee = Decimal('0')
    config.debt_ceiling = Decimal('500000')
    config.sac_value_fc = 200000
    config.save()
    print(f'   Config: savings_rate={config.savings_rate}, cm_rate={config.default_commission_rate}')

    print('\n→ Grille tarifaire pains…')
    bread_prices = {}
    price_data = [
        ('MINI',    'Pain 200 FC',  200),
        ('MOYEN',   'Pain 300 FC',  300),
        ('GRAND',   'Pain 500 FC',  500),
        ('PREMIUM', 'Pain 1000 FC', 1000),
    ]
    for cat, label, price in price_data:
        bp = BreadPrice.objects.create(category=cat, label=label, unit_price=price, is_active=True)
        bread_prices[price] = bp
        print(f'   {bp}')

    return nodes, gerants, config, bread_prices


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 2 — LECTURE DES DONNÉES DOC 01
# ═══════════════════════════════════════════════════════════════════════════════

def _is_valid_client_row(client_num, client_name):
    """Retourne True si la ligne représente un vrai client."""
    if not isinstance(client_num, int):
        return False
    if not client_name or not str(client_name).strip():
        return False
    name = str(client_name).strip()
    if name in SKIP_NAMES:
        return False
    if name.startswith('Total') or name.startswith('TOTAL'):
        return False
    return True


def read_doc01(sheet_name):
    """
    Lit un onglet de DOC 01 et retourne :
      - clients: dict {client_num (int): name (str)}
      - invoices: dict {(client_num, date): (qty200, qty300, qty500, qty1000, total, paiement)}
    """
    print(f'\n   Lecture DOC 01 — {sheet_name}…')
    wb = openpyxl.load_workbook(str(DOC01_PATH), data_only=True)
    ws = wb[sheet_name]

    clients = {}   # client_num → name
    invoices = {}  # (client_num, date) → (q200, q300, q500, q1000, total, pmt)

    for r in range(1, ws.max_row + 1):
        date_val = ws.cell(r, 1).value
        client_num = ws.cell(r, 2).value
        client_name = ws.cell(r, 3).value

        # Doit être une date août 2026
        if not (hasattr(date_val, 'year') and date_val.year == 2026 and date_val.month == 8):
            continue

        if not _is_valid_client_row(client_num, client_name):
            continue

        name = str(client_name).strip()

        # Enregistrer le client
        if client_num not in clients:
            clients[client_num] = name
        else:
            # Mettre à jour si le nom change (rare mais possible)
            if clients[client_num] != name:
                clients[client_num] = name

        # Lire les quantités
        q200  = int(ws.cell(r, COL_QTY200).value  or 0)
        q300  = int(ws.cell(r, COL_QTY300).value  or 0)
        q500  = int(ws.cell(r, COL_QTY500).value  or 0)
        q1000 = int(ws.cell(r, COL_QTY1000).value or 0)

        # Total et paiement
        raw_total = ws.cell(r, COL_TOTAL).value
        total = int(raw_total or 0)

        pmt_actuel = ws.cell(r, COL_PAIEMENT).value or 0
        site_pmt   = ws.cell(r, COL_SITE_PMT).value or 0
        paiement   = int(pmt_actuel) + int(site_pmt)

        # Recalcule le total si la formule n'est pas résolue
        if total == 0 and (q200 or q300 or q500 or q1000):
            total = q200 * 200 + q300 * 300 + q500 * 500 + q1000 * 1000

        if total == 0 and paiement == 0:
            continue  # Ligne vide — ignorer

        inv_date = date_val.date() if hasattr(date_val, 'date') else date_val
        key = (client_num, inv_date)
        if key not in invoices:
            invoices[key] = (q200, q300, q500, q1000, total, paiement)
        else:
            # Doublon (même client même jour dans deux blocs) — agréger
            old = invoices[key]
            invoices[key] = (
                old[0] + q200, old[1] + q300, old[2] + q500, old[3] + q1000,
                old[4] + total, old[5] + paiement,
            )

    wb.close()
    print(f'      {len(clients)} clients, {len(invoices)} lignes de facture')
    return clients, invoices


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 3 — CRÉATION DES CLIENTS
# ═══════════════════════════════════════════════════════════════════════════════

def create_clients(node_code, node, clients_dict):
    """Crée les clients pour un nœud. Retourne {client_num: Client}."""
    from clients.models import Client

    result = {}
    for num in sorted(clients_dict.keys()):
        name = clients_dict[num].strip()
        # Décomposer le nom : dernier mot = prénom, reste = nom
        parts = name.split()
        if len(parts) > 1:
            last_name  = ' '.join(parts[:-1])
            first_name = parts[-1]
        else:
            last_name  = name
            first_name = ''

        # Code auto-généré par le modèle
        client = Client(
            node=node,
            last_name=last_name,
            first_name=first_name,
            commission_rate=COMMISSION_RATE,
            cotisation_sociale=Decimal('3000'),
            current_debt=Decimal('0'),
            is_active=True,
        )
        client.save()
        result[num] = client

    print(f'      {len(result)} clients créés pour {node_code}')
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 4 — CRÉATION DES FACTURES
# ═══════════════════════════════════════════════════════════════════════════════

def create_invoices(node, gerant, clients_by_num, invoices_dict, bread_prices):
    """
    Crée les factures + lignes pour un nœud à partir de invoices_dict.
    Retourne {client_num: debt_after_final} et stats.
    """
    from sales.models import Invoice, InvoiceLine

    # Désactiver temporairement auto_now_add pour invoice_date
    inv_date_field = Invoice._meta.get_field('invoice_date')
    orig_auto = inv_date_field.auto_now_add
    inv_date_field.auto_now_add = False

    # Suivre la dette courante par client
    running_debt = {num: Decimal('0') for num in clients_by_num}

    # Trier par date puis client
    sorted_keys = sorted(invoices_dict.keys(), key=lambda k: (k[1], k[0]))

    count = 0
    for (client_num, inv_date) in sorted_keys:
        if client_num not in clients_by_num:
            continue

        client = clients_by_num[client_num]
        q200, q300, q500, q1000, total, paiement = invoices_dict[(client_num, inv_date)]

        debt_before = running_debt[client_num]
        pmt = Decimal(str(paiement))
        order_total = Decimal(str(total))

        if order_total == 0 and pmt == 0:
            continue

        debt_after = debt_before + order_total - pmt

        inv = Invoice(
            node=node,
            client=client,
            facturier=gerant,
            livreur=gerant,
            invoice_date=inv_date,
            status='DELIVERED',
            payment_type='CREDIT',
            debt_before=debt_before,
            order_total=order_total,
            payment_amount=pmt,
            debt_after=debt_after,
            commission_rate=COMMISSION_RATE,
            is_soldee=False,
        )
        inv.save()

        # Lignes de facture
        lines_data = [
            (bread_prices.get(200), q200),
            (bread_prices.get(300), q300),
            (bread_prices.get(500), q500),
            (bread_prices.get(1000), q1000),
        ]
        for bp, qty in lines_data:
            if qty > 0 and bp is not None:
                InvoiceLine.objects.create(invoice=inv, bread_price=bp, quantity=qty)

        running_debt[client_num] = debt_after
        count += 1

    # Mettre à jour la dette actuelle des clients
    for num, client in clients_by_num.items():
        final_debt = running_debt[num]
        if final_debt != Decimal('0'):
            from django.db import models as djm
            type(client).objects.filter(pk=client.pk).update(current_debt=final_debt)

    # Restaurer auto_now_add
    inv_date_field.auto_now_add = orig_auto

    print(f'      {count} factures créées pour {node.code}')
    return running_debt


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 5 — COMMISSIONS AOÛT 2026
# ═══════════════════════════════════════════════════════════════════════════════

def create_commissions_august(node, clients_by_num, running_debt):
    """
    Crée une CommissionPeriod pour août 2026 et calcule les ClientCommissions
    en agrégeant les factures DELIVERED.
    """
    from commissions.models import CommissionPeriod, ClientCommission
    from sales.models import Invoice
    from django.db.models import Sum

    period, _ = CommissionPeriod.objects.get_or_create(
        node=node, month=8, year=2026,
        defaults={'is_closed': False}
    )

    count = 0
    for client_num, client in clients_by_num.items():
        # Agréger les commandes du mois
        agg = Invoice.objects.filter(
            node=node, client=client, status='DELIVERED',
            invoice_date__month=8, invoice_date__year=2026,
        ).aggregate(
            total_order=Sum('order_total'),
            total_payment=Sum('payment_amount'),
        )
        order_val = agg['total_order'] or Decimal('0')
        if order_val == 0:
            continue

        # Calcul de la commission
        cc = ClientCommission(
            period=period,
            client=client,
            order_value=order_val,
            commission_rate=COMMISSION_RATE,
            deduction_debt=max(Decimal('0'), running_debt.get(client_num, Decimal('0'))),
            deduction_social=Decimal('0'),
            deduction_prints=Decimal('0'),
            deduction_other=Decimal('0'),
        )
        cc.compute()

        # Total pains pour bonus annuel
        from sales.models import InvoiceLine
        from django.db.models import Sum as DjSum
        total_breads = InvoiceLine.objects.filter(
            invoice__node=node,
            invoice__client=client,
            invoice__status='DELIVERED',
            invoice__invoice_date__month=8,
            invoice__invoice_date__year=2026,
        ).aggregate(t=DjSum('quantity'))['t'] or 0
        cc.total_breads = total_breads

        cc.save()
        count += 1

    print(f'      {count} commissions août 2026 calculées pour {node.code}')


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 6 — ÉPARGNE JOURNALIÈRE
# ═══════════════════════════════════════════════════════════════════════════════

def create_daily_savings(node, gerant, invoices_dict, clients_by_num):
    """
    Crée les enregistrements DailySavings en agrégeant les CA journaliers.
    """
    from treasury.models import DailySavings
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Agréger CA par jour pour ce nœud
    daily_ca = {}
    for (client_num, inv_date), (_, _, _, _, total, _) in invoices_dict.items():
        if client_num not in clients_by_num:
            continue
        daily_ca[inv_date] = daily_ca.get(inv_date, Decimal('0')) + Decimal(str(total))

    count = 0
    for inv_date, ca in sorted(daily_ca.items()):
        savings_amount = (ca * SAVINGS_RATE).quantize(Decimal('0.01'))
        obj, created = DailySavings.objects.update_or_create(
            node=node, date=inv_date,
            defaults={
                'recorded_by': gerant,
                'flour_sacks': Decimal('0'),
                'daily_revenue': ca,
                'savings_rate': SAVINGS_RATE,
                'savings_amount': savings_amount,
            }
        )
        count += 1

    print(f'      {count} enregistrements épargne pour {node.code}')


# ═══════════════════════════════════════════════════════════════════════════════
#  PHASE 7 — YEAR FINANCIER
# ═══════════════════════════════════════════════════════════════════════════════

def create_financial_year():
    from finance.models import FinancialYear
    fy, _ = FinancialYear.objects.get_or_create(year=2026, defaults={'is_current': True, 'is_closed': False})
    fy2025, _ = FinancialYear.objects.get_or_create(year=2025, defaults={'is_current': False, 'is_closed': False})
    print(f'   Exercices financiers créés: {fy}, {fy2025}')


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print('='*70)
    print('  SEED ETS. KIESE — Données réelles Août 2026')
    print('='*70)

    # Phase 0 — Nettoyage
    flush_database()

    # Phase 1 — Infrastructure
    with transaction.atomic():
        nodes, gerants, config, bread_prices = create_infrastructure()
        create_financial_year()

    # Phase 2 → 6 par nœud
    for sheet_name, node_code in SHEET_TO_NODE.items():
        print(f'\n{"─"*60}')
        print(f'  NŒUD {node_code} / {sheet_name}')
        print(f'{"─"*60}')

        node   = nodes[node_code]
        gerant = gerants[node_code]

        with transaction.atomic():
            # Lire DOC 01
            clients_dict, invoices_dict = read_doc01(sheet_name)

            if not clients_dict:
                print(f'   Aucun client trouvé pour {sheet_name}')
                continue

            # Clients
            print(f'\n→ Clients {node_code}…')
            clients_by_num = create_clients(node_code, node, clients_dict)

            # Factures
            print(f'\n→ Factures {node_code}…')
            running_debt = create_invoices(node, gerant, clients_by_num, invoices_dict, bread_prices)

            # Commissions
            print(f'\n→ Commissions août 2026 — {node_code}…')
            create_commissions_august(node, clients_by_num, running_debt)

            # Épargne
            print(f'\n→ Épargne journalière — {node_code}…')
            create_daily_savings(node, gerant, invoices_dict, clients_by_num)

    # Résumé
    print('\n' + '='*70)
    print('  RÉSUMÉ FINAL')
    print('='*70)
    from core.models import Node, User
    from clients.models import Client
    from sales.models import Invoice, InvoiceLine
    from commissions.models import CommissionPeriod, ClientCommission
    from treasury.models import DailySavings

    print(f'  Nœuds        : {Node.objects.count()}')
    print(f'  Utilisateurs  : {User.objects.count()}')
    print(f'  Clients       : {Client.objects.count()}')
    print(f'  Factures      : {Invoice.objects.count()}')
    print(f'  Lignes fact.  : {InvoiceLine.objects.count()}')
    print(f'  Périodes CM   : {CommissionPeriod.objects.count()}')
    print(f'  Commissions   : {ClientCommission.objects.count()}')
    print(f'  Épargne       : {DailySavings.objects.count()}')
    print('\n  Seed terminé avec succès.')


if __name__ == '__main__':
    main()
