"""
BUG-144 (remarque.md, ligne ajoutée après l.396 ; coordinateur, 2026-11-10) :

« Au niveau de "Production & Stocks" pour les sections "Stock Pains Actuel"
et "Historique des Fournées" on doit pouvoir sélectionner un jour et voir
les résultats du jour [...] ».

Volet backend (ce ticket) : fournir un endpoint permettant d'interroger le
stock de pains d'un jour PASSÉ (reconstitué via `DailyBreadStockSnapshot`,
BUG-118/120/135, déjà vérifié), pas seulement le solde courant
(`BreadStock.qty_available`). Le ticket BUG-145 (dev-frontend, séparé)
consommera `GET /api/production/bread-stocks/by-date/`.

Couverture :
  A) Date omise / aujourd'hui → `source: "live"`, identique au solde
     courant `BreadStock.qty_available` (non-régression).
  B) Date passée, une seule équipe (A) a clôturé ce jour-là → la quantité
     renvoyée est celle de l'équipe A seule (équipe B absente = 0), et
     DIFFÉRENTE du solde courant `BreadStock.qty_available`.
  C) Date passée, les deux équipes (A et B) ont clôturé ce jour-là → somme
     des deux `qty_at_close`.
  D) Date future → 400 propre.
  E) Permissions : GERANT/FACTURIER ne peuvent jamais lire un autre nœud
     (valeur `node` forgée dans la requête ignorée) ; HQ doit préciser
     `node` explicitement.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import BreadStock, DailyBreadStockSnapshot


class BreadStockByDateLiveTests(TestCase):
    """Cas A — aujourd'hui/omise : identique au solde courant (non-régression)."""

    def setUp(self):
        self.node = make_node()
        self.bp = make_bread_price(category='MOYEN', label='Pain Test 500 FC', unit_price=500)
        self.user = make_user(role='GERANT', node=self.node)
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_produced=80, qty_disposed=30)
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_no_date_param_returns_live_current_balance(self):
        resp = self.api.get('/api/production/bread-stocks/by-date/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['source'], 'live')
        cats = {c['bread_price']: c for c in resp.data['categories']}
        self.assertEqual(cats[self.bp.pk]['qty_available'], 50)

    def test_today_date_param_matches_existing_bread_stock_endpoint(self):
        import datetime
        from django.utils import timezone

        today = timezone.localdate().isoformat()
        resp = self.api.get(f'/api/production/bread-stocks/by-date/?date={today}')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['source'], 'live')

        legacy = self.api.get('/api/production/bread-stocks/')
        self.assertEqual(legacy.status_code, 200, legacy.data)
        legacy_rows = legacy.data['results'] if isinstance(legacy.data, dict) else legacy.data
        legacy_qty = {row['bread_price']: row['qty_available'] for row in legacy_rows}
        new_qty = {row['bread_price']: row['qty_available'] for row in resp.data['categories']}
        self.assertEqual(legacy_qty, new_qty)


class BreadStockByDateSnapshotTests(TestCase):
    """Cas B/C — date passée reconstituée via DailyBreadStockSnapshot."""

    def setUp(self):
        self.node = make_node()
        self.bp = make_bread_price(category='MOYEN', label='Pain Test 500 FC', unit_price=500)
        self.user = make_user(role='GERANT', node=self.node)
        # Solde courant volontairement différent du passé, pour prouver que
        # l'endpoint ne retombe jamais sur `BreadStock.qty_available` pour
        # une date passée.
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_produced=999)
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_past_date_single_team_closed_returns_that_team_only(self):
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp, date='2026-11-05', team='A', qty_at_close=40,
        )
        resp = self.api.get('/api/production/bread-stocks/by-date/?date=2026-11-05')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['source'], 'snapshot')
        cats = {c['bread_price']: c for c in resp.data['categories']}
        self.assertEqual(cats[self.bp.pk]['qty_available'], 40)
        self.assertNotEqual(cats[self.bp.pk]['qty_available'], 999)

    def test_past_date_both_teams_closed_sums_both(self):
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp, date='2026-11-05', team='A', qty_at_close=40,
        )
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp, date='2026-11-05', team='B', qty_at_close=15,
        )
        resp = self.api.get('/api/production/bread-stocks/by-date/?date=2026-11-05')
        self.assertEqual(resp.status_code, 200, resp.data)
        cats = {c['bread_price']: c for c in resp.data['categories']}
        self.assertEqual(cats[self.bp.pk]['qty_available'], 55)

    def test_past_date_with_no_snapshot_at_all_returns_empty_categories(self):
        resp = self.api.get('/api/production/bread-stocks/by-date/?date=2026-01-01')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['source'], 'snapshot')
        self.assertEqual(resp.data['categories'], [])

    def test_future_date_rejected_with_400(self):
        resp = self.api.get('/api/production/bread-stocks/by-date/?date=2099-01-01')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.data)

    def test_invalid_date_format_rejected_with_400(self):
        resp = self.api.get('/api/production/bread-stocks/by-date/?date=not-a-date')
        self.assertEqual(resp.status_code, 400)


class BreadStockByDatePermissionTests(TestCase):
    """Cas E — isolation par nœud (motif BUG-022/025/056/120)."""

    def setUp(self):
        self.node = make_node()
        self.other_node = make_node()
        self.bp = make_bread_price(category='MOYEN', label='Pain Test 500 FC', unit_price=500)
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_produced=10)
        BreadStock.objects.create(node=self.other_node, bread_price=self.bp, qty_produced=777)

    def test_gerant_forged_node_param_is_ignored(self):
        user = make_user(role='GERANT', node=self.node)
        api = APIClient()
        api.force_authenticate(user)
        resp = api.get(f'/api/production/bread-stocks/by-date/?node={self.other_node.pk}')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['node'], self.node.pk)
        cats = {c['bread_price']: c for c in resp.data['categories']}
        self.assertEqual(cats[self.bp.pk]['qty_available'], 10)

    def test_facturier_forged_node_param_is_ignored(self):
        user = make_user(role='FACTURIER', node=self.node)
        api = APIClient()
        api.force_authenticate(user)
        resp = api.get(f'/api/production/bread-stocks/by-date/?node={self.other_node.pk}')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['node'], self.node.pk)

    def test_hq_must_specify_node_explicitly(self):
        hq_user = make_user(role='DIRECTION', node=None)
        api = APIClient()
        api.force_authenticate(hq_user)
        resp = api.get('/api/production/bread-stocks/by-date/')
        self.assertEqual(resp.status_code, 400)

    def test_hq_can_read_any_node_when_specified(self):
        hq_user = make_user(role='DIRECTION', node=None)
        api = APIClient()
        api.force_authenticate(hq_user)
        resp = api.get(f'/api/production/bread-stocks/by-date/?node={self.other_node.pk}')
        self.assertEqual(resp.status_code, 200, resp.data)
        cats = {c['bread_price']: c for c in resp.data['categories']}
        self.assertEqual(cats[self.bp.pk]['qty_available'], 777)

    def test_unauthenticated_rejected(self):
        api = APIClient()
        resp = api.get(f'/api/production/bread-stocks/by-date/?node={self.node.pk}')
        self.assertIn(resp.status_code, (401, 403))
