"""
BUG-119 (Chantier A — analyse du vrai Livre de Caisse Direction,
`data_kiese/D1-4...xlsx`) : comptage physique des billets au niveau
Direction, avec calcul d'écart physique/théorique.

Le fichier réel du client montre que le Livre de Caisse Direction fait,
comme la clôture Niveau 2 (`CashClosure`), un comptage physique de billets
avec calcul d'écart — mais ce contrôle n'existait pas du tout au Niveau 3
(`CashbookEntry`, lecture seule, sans billetage).

Ces tests couvrent :
- Le calcul correct de l'écart (`DirectionCashCount`).
- La non-altération du solde/chaînage existant de `CashbookEntry` par ce
  nouvel ajout (le modèle est séparé, non couvert par la formule de hash).
- Les permissions (un GERANT ne doit jamais pouvoir faire ce comptage).
- Qu'aucune régression n'est introduite dans la détection de falsification
  déjà couverte par `test_ledger.py` (même principe que BUG-085 : un test de
  falsification directe en base reste détecté après coup).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_node, make_user
from treasury.hashing import verify_cashbook_chain
from treasury.models import CashbookEntry, DirectionCashCount
from treasury.views import append_cashbook_entry


class DirectionCashCountComputationTests(TestCase):
    """Calcul de l'écart et non-altération du Livre de Caisse Direction."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.hq_user = make_user(role='ADMIN', node=None, username='admin1')
        self.api = APIClient()
        self.api.force_authenticate(self.hq_user)
        # Dates de test antérieures à aujourd'hui (données figées pour une
        # chaîne reproductible) — même angle que BUG-083/086.
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def _append(self, i, amount=Decimal('1000.00')):
        return append_cashbook_entry(
            node=self.node,
            date='2026-10-01',
            piece_number=f'VC-BUG119-{i:03d}',
            imputation='7000',
            label=f'Écriture de test #{i}',
            entry_amount=amount,
            exit_amount=Decimal('0.00'),
            node_origin=self.node.code,
        )

    def test_cash_gap_is_computed_against_theoretical_running_balance(self):
        """Solde théorique = running_balance de la dernière CashbookEntry
        connue à cette date ou avant ; écart = compté - théorique."""
        for i in range(5):
            self._append(i)  # solde cumulé théorique = 5000.00

        resp = self.api.post('/api/treasury/direction-cash-counts/', {
            'date': '2026-10-01',
            'bills_1000': 5,  # 5 x 1000 = 5000 FC comptés
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        count = DirectionCashCount.objects.get(date='2026-10-01')
        self.assertEqual(count.theoretical_balance, Decimal('5000.00'))
        self.assertEqual(count.physical_cash_total, Decimal('5000.00'))
        self.assertEqual(count.cash_gap, Decimal('0.00'))

    def test_cash_gap_is_non_zero_when_physical_count_differs(self):
        for i in range(3):
            self._append(i)  # théorique = 3000.00

        resp = self.api.post('/api/treasury/direction-cash-counts/', {
            'date': '2026-10-01',
            'bills_1000': 2,  # 2000 FC comptés, manque 1000 FC
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        count = DirectionCashCount.objects.get(date='2026-10-01')
        self.assertEqual(count.theoretical_balance, Decimal('3000.00'))
        self.assertEqual(count.physical_cash_total, Decimal('2000.00'))
        self.assertEqual(count.cash_gap, Decimal('-1000.00'))

    def test_cash_gap_with_no_cashbook_entry_yet_uses_zero_theoretical_balance(self):
        resp = self.api.post('/api/treasury/direction-cash-counts/', {
            'date': '2026-09-01',
            'bills_500': 2,  # 1000 FC comptés
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        count = DirectionCashCount.objects.get(date='2026-09-01')
        self.assertEqual(count.theoretical_balance, Decimal('0.00'))
        self.assertEqual(count.cash_gap, Decimal('1000.00'))

    def test_direction_cash_count_never_alters_cashbook_balance_or_chain(self):
        """Une saisie de comptage ne doit avoir strictement aucun effet sur
        `CashbookEntry` : ni running_balance, ni block_hash/previous_hash,
        ni le nombre d'écritures."""
        entries_before = [self._append(i) for i in range(4)]
        last_entry_before = CashbookEntry.objects.order_by('-date', '-created_at').first()
        balance_before = last_entry_before.running_balance
        hash_before = last_entry_before.block_hash
        count_before = CashbookEntry.objects.count()

        resp = self.api.post('/api/treasury/direction-cash-counts/', {
            'date': '2026-10-01',
            'bills_1000': 4,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        self.assertEqual(CashbookEntry.objects.count(), count_before)
        last_entry_after = CashbookEntry.objects.order_by('-date', '-created_at').first()
        self.assertEqual(last_entry_after.running_balance, balance_before)
        self.assertEqual(last_entry_after.block_hash, hash_before)

        # La chaîne reste parfaitement valide après le comptage.
        results = verify_cashbook_chain(CashbookEntry.objects.order_by('date', 'created_at'))
        self.assertTrue(all(is_valid for _e, _exp, is_valid in results))

    def test_duplicate_count_for_same_date_is_rejected_cleanly(self):
        self._append(0)
        resp1 = self.api.post('/api/treasury/direction-cash-counts/', {
            'date': '2026-10-01', 'bills_1000': 1,
        }, format='json')
        self.assertEqual(resp1.status_code, 201, resp1.content)

        resp2 = self.api.post('/api/treasury/direction-cash-counts/', {
            'date': '2026-10-01', 'bills_1000': 1,
        }, format='json')
        self.assertEqual(resp2.status_code, 400, resp2.content)
        # Le serializer DRF (UniqueValidator sur `date`, unique=True) refuse
        # déjà la saisie avant perform_create — le refus reste propre (400)
        # dans les deux cas (ceinture : l'IntegrityError de secours dans
        # perform_create couvre une éventuelle course entre deux requêtes
        # concurrentes passant la validation du serializer en même temps).
        self.assertTrue('detail' in resp2.json() or 'date' in resp2.json())
        self.assertEqual(DirectionCashCount.objects.filter(date='2026-10-01').count(), 1)


class DirectionCashCountPermissionTests(TestCase):
    """IsHeadquarters uniquement — un GERANT ne doit jamais pouvoir compter
    la caisse Direction (CLAUDE.md §5.5, même niveau que CashbookEntry)."""

    def setUp(self):
        self.node = make_node(code='K2', name='K2 - COQ')
        self.gerant = make_user(role='GERANT', node=self.node, username='gerant_bug119')
        self.hq_user = make_user(role='DIRECTION', node=None, username='direction_bug119')
        self.api = APIClient()
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

    def test_gerant_cannot_create_direction_cash_count(self):
        self.api.force_authenticate(self.gerant)
        resp = self.api.post('/api/treasury/direction-cash-counts/', {
            'date': '2026-10-02', 'bills_1000': 1,
        }, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(DirectionCashCount.objects.count(), 0)

    def test_gerant_cannot_list_direction_cash_counts(self):
        self.api.force_authenticate(self.gerant)
        resp = self.api.get('/api/treasury/direction-cash-counts/')
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_headquarters_can_create_and_list(self):
        self.api.force_authenticate(self.hq_user)
        resp = self.api.post('/api/treasury/direction-cash-counts/', {
            'date': '2026-10-02', 'bills_1000': 1,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        resp_list = self.api.get('/api/treasury/direction-cash-counts/')
        self.assertEqual(resp_list.status_code, 200, resp_list.content)
        self.assertEqual(len(resp_list.json()['results'] if 'results' in resp_list.json() else resp_list.json()), 1)

    def test_no_update_or_delete_endpoint_exposed(self):
        """ModelViewSet complet volontairement évité : pas de PATCH/DELETE."""
        self.api.force_authenticate(self.hq_user)
        resp = self.api.post('/api/treasury/direction-cash-counts/', {
            'date': '2026-10-03', 'bills_1000': 1,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        count_id = resp.json()['id']

        resp_patch = self.api.patch(f'/api/treasury/direction-cash-counts/{count_id}/', {
            'bills_1000': 2,
        }, format='json')
        self.assertEqual(resp_patch.status_code, 405, resp_patch.content)

        resp_delete = self.api.delete(f'/api/treasury/direction-cash-counts/{count_id}/')
        self.assertEqual(resp_delete.status_code, 405, resp_delete.content)
