"""
Script de charge — volumétrie (testeur-charge, 2026-10-22).

Objectif (CLAUDE.md §4/§5.2/§5.5, mission testeur-charge point 4) :
mesurer les temps de réponse des listes, recherche clients, rapports,
livre de caisse et états financiers sur un volume de données fictives
représentatif d'une fraction d'exercice, et détecter les requêtes N+1
avec `CaptureQueriesContext`.

Règle transversale (PLAN_2026-10-22.md §0.1, rappelée dans la mission) :
ce script N'ÉCRIT JAMAIS dans `backend/db.sqlite3`. Il crée sa propre
base SQLite temporaire (fichier distinct, supprimé à la fin), via une
variable d'environnement `DB_NAME` positionnée AVANT `django.setup()`.
Ce n'est ni un test de non-régression (`manage.py test`), ni une
démonstration manuelle visible pour le client — c'est un outil de mesure
ponctuel, à lancer manuellement par un agent/développeur.

Usage :
    cd backend
    python scripts/charge/volumetrie.py [--days 10] [--invoices-per-day-per-node 300]

Échelle choisie par défaut : 8 boulangeries, 700 clients, 300
factures/jour/boulangerie, mais sur un nombre de jours réduit (10 par
défaut, configurable) plutôt que 365 — un an complet (365 j × 8 × 300 ≈
876 000 factures) prendrait plusieurs dizaines de minutes à insérer en
SQLite sur ce poste et n'apporte rien de plus pour mesurer le temps de
réponse des endpoints : la plupart sont déjà filtrés par nœud + date
(donc indépendants du volume total accumulé), seuls les endpoints non
filtrés par date (recherche client, listes non filtrées, agrégats
annuels `finance`) dépendent vraiment du volume TOTAL en base — voir le
rapport pour l'extrapolation linéaire explicite à 365 jours.
"""
import argparse
import hashlib
import os
import random
import sys
import tempfile
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

TMP_DB_PATH = Path(tempfile.gettempdir()) / f"kiese_charge_volumetrie_{uuid.uuid4().hex}.sqlite3"

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kiese.settings')
# settings.py refuse de démarrer hors DEBUG avec la clé de secours par
# défaut (BUG-005, garde-fou toujours en place) : ce script est un outil
# de mesure local, jamais déployé, DEBUG=True est donc approprié ici.
os.environ['DJANGO_DEBUG'] = 'True'

import django  # noqa: E402
django.setup()  # noqa: E402

# Jamais db.sqlite3 : base temporaire dédiée à ce script, détruite à la fin.
#
# ATTENTION (constaté en testant ce script, laissé en commentaire pour la
# prochaine personne qui en écrirait un équivalent) : positionner
# `os.environ['DB_NAME']` AVANT `django.setup()` ne suffit PAS ici.
# `kiese/settings.py` appelle `load_dotenv(BASE_DIR / '.env', override=True)`
# — avec `override=True`, toute variable déjà présente dans le fichier
# `.env` local du développeur (même VIDE, ex. `DB_NAME=`) écrase une
# variable déjà positionnée dans `os.environ`, donc notre `DB_NAME` était
# aussitôt effacé et remplacé par la chaîne vide, faisant retomber
# `settings.py` sur `BASE_DIR / 'db.sqlite3'` — la VRAIE base de
# développement. Un premier essai de ce script a confirmé ce mécanisme en
# échouant sur `UNIQUE constraint failed: core_node.code` (K1 existait déjà
# dans `db.sqlite3`) : l'écriture a échoué avant toute insertion effective
# (confirmé après coup : aucune donnée de charge n'a atteint `db.sqlite3`,
# voir rapport), mais avec d'autres données la pollution aurait pu être
# silencieuse. Solution robuste retenue, indépendante de l'ordre de
# chargement de `.env` : patcher directement `django.conf.settings.DATABASES`
# APRÈS `django.setup()`, avant toute requête SQL (aucune connexion n'a
# encore été ouverte à ce stade).
from django.conf import settings as _dj_settings  # noqa: E402
_dj_settings.DATABASES['default']['NAME'] = str(TMP_DB_PATH)
_dj_settings.DATABASES['default']['ENGINE'] = 'django.db.backends.sqlite3'
# APIClient (DRF) envoie Host: testserver — autorisé seulement pour ce
# script de mesure, jamais en production (ALLOWED_HOSTS réel inchangé).
if 'testserver' not in _dj_settings.ALLOWED_HOSTS:
    _dj_settings.ALLOWED_HOSTS = list(_dj_settings.ALLOWED_HOSTS) + ['testserver']

from django.core.management import call_command  # noqa: E402
from django.db import connection, connections, transaction  # noqa: E402

# Garde-fou explicite : on n'exécute RIEN d'autre si, pour une raison
# quelconque (nouvelle variante de Django, nouvel ordre d'import...), la
# connexion par défaut ne pointe pas vers notre fichier temporaire. Mieux
# vaut planter bruyamment ici que d'écrire silencieusement dans db.sqlite3.
_actual_name = str(connections.databases['default']['NAME'])
if TMP_DB_PATH.name not in _actual_name or 'db.sqlite3' in _actual_name.replace(TMP_DB_PATH.name, ''):
    raise RuntimeError(
        f"Garde-fou d'isolation de base de données déclenché : NAME='{_actual_name}' "
        f"ne correspond pas au fichier temporaire attendu ({TMP_DB_PATH}). "
        "Abandon volontaire pour ne jamais risquer d'écrire dans db.sqlite3."
    )
from django.test.utils import CaptureQueriesContext  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from core.models import Node, BreadPrice, Config, User  # noqa: E402
from clients.models import Client  # noqa: E402
from sales.models import Invoice, InvoiceLine  # noqa: E402
from treasury.models import CashbookEntry  # noqa: E402
from finance.models import FinancialYear  # noqa: E402
from decimal import Decimal  # noqa: E402
import datetime  # noqa: E402


NODE_CODES = ['K1', 'K2', 'K3', 'K4', 'K5', 'K6', 'B1', 'B2']
CATEGORIES = [
    ('MINI', 'Pain 200 FC', 200),
    ('MOYEN', 'Pain 300 FC', 300),
    ('GRAND', 'Pain 500 FC', 500),
    ('PREMIUM', 'Pain 1000 FC', 1000),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def seed_master_data():
    """
    Les 8 boulangeries existent déjà après `migrate` (migrations de données
    `core/migrations/0007_data_nodes_b1_b2.py` et
    `core/migrations/0011_data_node_siege.py`, qui créent aussi un nœud
    `SIEGE`) : on les récupère par `get_or_create` plutôt que de les créer
    à nouveau (sinon `IntegrityError` sur `core_node.code`, unique).
    """
    Config.get_instance()
    nodes = {}
    for code in NODE_CODES:
        node, _created = Node.objects.get_or_create(
            code=code, defaults={'name': f"Boulangerie {code}", 'sac_value_fc': Decimal('200000')}
        )
        nodes[code] = node
    prices = []
    for cat, label, price in CATEGORIES:
        bp, _created = BreadPrice.objects.get_or_create(
            category=cat, defaults={'label': label, 'unit_price': price, 'is_active': True}
        )
        prices.append(bp)
    hq = User.objects.create_user(
        username='charge_hq_admin', password='x', role='ADMIN',
    )
    return nodes, prices, hq


def seed_clients(nodes, n_total=700):
    """~700 clients fictifs, répartis sur les 8 boulangeries (CLAUDE.md §5.1)."""
    per_node = n_total // len(nodes)
    clients = []
    seq = 0
    for code, node in nodes.items():
        batch = []
        for i in range(per_node):
            seq += 1
            batch.append(Client(
                node=node, node_origin=code,
                code=f"{code}-{i + 1:04d}",
                first_name=f"ClientCharge{seq}",
                last_name=f"Boulangerie{code}",
                phone=f"08{seq:08d}",
                credit_limit=Decimal('50000.00'),
                current_debt=Decimal('0.00'),
                commission_rate=Decimal('0.25'),
                client_type='DETAILLANT',
                is_synced=True,
            ))
        clients.extend(Client.objects.bulk_create(batch))
    log(f"{len(clients)} clients fictifs créés (répartis sur {len(nodes)} boulangeries).")
    return clients


def seed_invoices(nodes, clients, prices, days, invoices_per_day_per_node):
    """
    Factures + lignes fictives, `days` journées pleines à
    `invoices_per_day_per_node` par boulangerie (défaut 300, cf. mission).
    Utilise `bulk_create` (pas la pile API/vue) pour atteindre un volume
    réaliste en un temps raisonnable ; les dates (`invoice_date`,
    `created_at`) sont `auto_now_add` donc forcées à "aujourd'hui" par
    l'ORM lors du `bulk_create` — on les recale ensuite par un `.update()`
    groupé par journée simulée (qui NE déclenche PAS `auto_now`/`auto_now_add`,
    contrairement à `.save()`), pour obtenir un historique étalé réaliste.
    """
    clients_by_node = {}
    for c in clients:
        clients_by_node.setdefault(c.node_id, []).append(c)

    today = datetime.date.today()
    total_invoices = 0
    total_lines = 0
    for day_offset in range(days):
        sim_date = today - datetime.timedelta(days=days - day_offset)
        day_invoice_objs = []
        day_invoice_clients = []  # parallel list of (client) for debt/lines generation
        for code, node in nodes.items():
            node_clients = clients_by_node[node.pk]
            for _ in range(invoices_per_day_per_node):
                client = random.choice(node_clients)
                inv = Invoice(
                    node=node, client=client, team=random.choice(['A', 'B']),
                    status=Invoice.Status.DELIVERED,
                    payment_type=random.choice([Invoice.PaymentType.CASH, Invoice.PaymentType.CREDIT]),
                    debt_before=Decimal('0.00'), order_total=Decimal('0.00'),
                    payment_amount=Decimal('0.00'), debt_after=Decimal('0.00'),
                    commission_rate=Decimal('0.25'),
                    node_origin=code,
                    receipt_number=f"{code}-{sim_date.strftime('%Y%m%d')}-{_ + 1:04d}",
                )
                day_invoice_objs.append(inv)

        created = Invoice.objects.bulk_create(day_invoice_objs, batch_size=2000)
        # Recale la date simulée (update() ne touche pas auto_now_add).
        Invoice.objects.filter(id__in=[i.id for i in created]).update(invoice_date=sim_date)

        lines = []
        for inv in created:
            n_lines = random.randint(1, 3)
            order_total = Decimal('0.00')
            for _ in range(n_lines):
                bp = random.choice(prices)
                qty = random.randint(1, 20)
                line_total = Decimal(qty * bp.unit_price)
                order_total += line_total
                lines.append(InvoiceLine(
                    invoice=inv, bread_price=bp, quantity=qty,
                    unit_price=bp.unit_price, line_total=line_total,
                ))
            inv.order_total = order_total
            inv.debt_after = order_total
            inv.payment_amount = order_total
        InvoiceLine.objects.bulk_create(lines, batch_size=2000)
        Invoice.objects.bulk_update(created, ['order_total', 'debt_after', 'payment_amount'], batch_size=2000)

        total_invoices += len(created)
        total_lines += len(lines)
        log(f"Jour simulé {sim_date} : {len(created)} factures, {len(lines)} lignes créées.")

    log(f"TOTAL factures : {total_invoices} | TOTAL lignes : {total_lines}")
    return today - datetime.timedelta(days=1)


def seed_cashbook(nodes, n_entries=500):
    """
    Entrées fictives du Livre de Caisse Direction, pour mesurer uniquement
    le temps de LISTE (déjà protégée par `select_related`) — PAS pour
    revalider la chaîne de hash elle-même (déjà couverte par les tests de
    concurrence d'`ingenieur-blockchain`, 8 threads). Les hash sont
    calculés de façon déterministe et séquentielle ici (pas de vraie
    fonction métier appelée) : NE PAS utiliser cette donnée pour tester
    `verify_cashbook_chain`.
    """
    entries = []
    previous_hash = ''
    balance = Decimal('0.00')
    node_list = list(nodes.values())
    for i in range(n_entries):
        node = node_list[i % len(node_list)]
        entry_amount = Decimal(random.randint(10000, 500000))
        exit_amount = Decimal(random.randint(0, 100000))
        balance += entry_amount - exit_amount
        raw = f"{node.code}|{entry_amount}|{exit_amount}|{balance}|{previous_hash}|{i}"
        block_hash = hashlib.sha256(raw.encode()).hexdigest()
        entries.append(CashbookEntry(
            node=node, date=datetime.date.today() - datetime.timedelta(days=n_entries - i),
            piece_number=f"PC-{i + 1:06d}", imputation='7000',
            label=f"Entrée fictive de charge #{i + 1}",
            entry_amount=entry_amount, exit_amount=exit_amount, running_balance=balance,
            block_hash=block_hash, previous_hash=previous_hash or f"GENESIS-{i}",
        ))
        previous_hash = block_hash
    CashbookEntry.objects.bulk_create(entries, batch_size=500)
    log(f"{len(entries)} écritures fictives du Livre de Caisse créées (hash non vérifiable, usage liste seulement).")


def measure(label, fn, repeats=5):
    """
    Un premier appel « à froid » (compilation des regex d'URL, résolution
    DRF, etc. — coût fixe au niveau du processus, pas du volume de
    données) est exécuté et ignoré ; le temps rapporté est la MÉDIANE de
    `repeats` appels « à chaud » qui suivent, représentative d'un p95
    opérationnel réel (serveur déjà démarré, requêtes répétées).
    """
    response = fn()  # warmup, ignoré
    timings = []
    n_queries = None
    status = getattr(response, 'status_code', 'N/A')
    for _ in range(repeats):
        with CaptureQueriesContext(connection) as ctx:
            t0 = time.perf_counter()
            response = fn()
            timings.append((time.perf_counter() - t0) * 1000)
        n_queries = len(ctx.captured_queries)
        status = getattr(response, 'status_code', 'N/A')
    timings.sort()
    median_ms = timings[len(timings) // 2]
    print(
        f"  {label:<55} status={status} médiane={median_ms:8.1f} ms "
        f"(min={min(timings):.1f}/max={max(timings):.1f})  requêtes SQL={n_queries}"
    )
    return {'label': label, 'status': status, 'elapsed_ms': median_ms, 'n_queries': n_queries}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=10)
    parser.add_argument('--invoices-per-day-per-node', type=int, default=300)
    parser.add_argument('--n-clients', type=int, default=700)
    args = parser.parse_args()

    log(f"Base temporaire : {TMP_DB_PATH}")
    log("Migration de la base temporaire...")
    call_command('migrate', verbosity=0, interactive=False)

    log("Seed des données de base (nœuds, prix, admin)...")
    nodes, prices, hq = seed_master_data()

    log(f"Seed de {args.n_clients} clients fictifs...")
    clients = seed_clients(nodes, args.n_clients)

    log(f"Seed de {args.days} jours à {args.invoices_per_day_per_node} factures/jour/boulangerie...")
    t0 = time.perf_counter()
    last_day = seed_invoices(nodes, clients, prices, args.days, args.invoices_per_day_per_node)
    log(f"Seed factures terminé en {time.perf_counter() - t0:.1f} s.")

    log("Seed d'écritures fictives du Livre de Caisse (mesure de liste uniquement)...")
    seed_cashbook(nodes)

    fy = FinancialYear.objects.create(year=last_day.year, is_current=True)
    FinancialYear.objects.create(year=last_day.year - 1)

    api = APIClient()
    api.force_authenticate(user=hq)
    sample_node = nodes['K1']

    print("\n=== Mesures (base temporaire, hors db.sqlite3) ===")
    results = []
    results.append(measure(
        "Recherche client (nom partiel, ~700 clients)",
        lambda: api.get('/api/clients/clients/', {'search': 'ClientCharge1'}),
    ))
    results.append(measure(
        "Liste factures — filtrée nœud+jour (volume réel d'une journée)",
        lambda: api.get('/api/sales/invoices/', {'node': str(sample_node.pk), 'invoice_date': str(last_day)}),
    ))
    results.append(measure(
        "Liste factures — NON filtrée (1ère page, pagination)",
        lambda: api.get('/api/sales/invoices/'),
    ))
    results.append(measure(
        "Commissions — summary() (agrégats par période)",
        lambda: api.get('/api/finance/years/summary/', {'year': last_day.year}),
    ))
    results.append(measure(
        "Finance — comparative() (bilan/résultat/cashflow N/N-1)",
        lambda: api.get(f'/api/finance/years/{fy.pk}/comparative/'),
    ))
    results.append(measure(
        "Production — reconciliation() (écart production/ventes/retours)",
        lambda: api.get('/api/production/sessions/reconciliation/', {'node': str(sample_node.pk), 'date': str(last_day)}),
    ))
    results.append(measure(
        "Livre de Caisse Direction — liste (lecture seule, HQ)",
        lambda: api.get('/api/treasury/cashbook/'),
    ))

    print("\n=== Détection N+1 : nombre de requêtes SQL doit rester borné,")
    print("    PAS proportionnel au nombre de lignes retournées (pagination=25 par défaut) ===")
    for r in results:
        flag = "  <-- SUSPECT (>30 requêtes pour une page)" if r['n_queries'] > 30 else ""
        print(f"  {r['label']:<55} {r['n_queries']:>4} requêtes{flag}")

    print("\nRésumé objectifs de référence (à confirmer par le coordinateur) :")
    for r in results:
        verdict = "OK" if r['elapsed_ms'] < 500 else "A SURVEILLER (> 500 ms)"
        print(f"  {r['label']:<55} {r['elapsed_ms']:8.1f} ms  [{verdict}]")


if __name__ == '__main__':
    try:
        main()
    finally:
        from django.db import connections
        connections.close_all()
        try:
            TMP_DB_PATH.unlink()
        except FileNotFoundError:
            pass
        for suffix in ('-wal', '-shm', '-journal'):
            p = Path(str(TMP_DB_PATH) + suffix)
            if p.exists():
                p.unlink()
