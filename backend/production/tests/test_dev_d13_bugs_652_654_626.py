"""Dev B (d13) : non-regression BUG-652/653/654/626/651b. Donnees fictives."""
from datetime import date as ddate, timedelta
from decimal import Decimal as Dc
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from production.models import BreadTransfer, ConsumableCount, _adjust_bread_stock
from production.tests.test_verif_a4_testeur_production import T, TBase, cl


class Bug652Respond(TBase):
    def test_respond_over_stock_refused_like_send(self):
        t = self.request([self.L(self.b3, 10)])
        r = self.respond(t, [self.L(self.b3, 101)])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('Stock insuffisant', r.data['detail'])
        self.assertEqual(self.stock(self.k1, self.b3), 100)
        self.assertEqual(BreadTransfer.objects.get(pk=t).transfer_status, 'PENDING')

    def test_respond_exactly_stock_ok_and_adjusts(self):
        t = self.request([self.L(self.b3, 10)])
        r = self.respond(t, [self.L(self.b3, 100)])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.stock(self.k1, self.b3), 0)

    def test_respond_partial_body_keeps_requested_other_lines(self):
        t = self.request([self.L(self.b3, 10), self.L(self.b5, 5)])
        r = self.respond(t, [self.L(self.b3, 8)])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((self.stock(self.k1, self.b3), self.stock(self.k1, self.b5)), (92, 95))

    def test_respond_without_bread_price_refused(self):
        t = self.request([self.L(self.b3, 10)])
        r = self.respond(t, [{'quantity_sent': 3}])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.stock(self.k1, self.b3), 100)


class Bug653FutureSession(TBase):
    URL = '/api/production/sessions/'

    def test_yesterday_ok_tomorrow_refused(self):
        body = {'team': 'A', 'flour_sacks_used': '1', 'lines': []}
        r = cl(self.g1).post(self.URL, dict(body, date=str(ddate.today() + timedelta(days=1))), format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('futur', r.data['detail'])
        r = cl(self.g1).post(self.URL, dict(body, date=str(ddate.today() - timedelta(days=1))), format='json')
        self.assertEqual(r.status_code, 201, r.content)


class Bug654Ascii(TBase):
    def test_ascii_only_in_strict_int(self):
        from rest_framework.exceptions import ValidationError
        from production.views import _strict_int
        self.assertEqual(_strict_int(' 12 ', 'x'), 12)
        for bad in ('٣', '１２', '٣٤', '-٣'):
            with self.assertRaises(ValidationError, msg=bad):
                _strict_int(bad, 'x')


class Bug626LegacyCountsSync(TestCase):
    def setUp(self):
        from core.testing import make_node
        from sync.tests.test_consumable_inventory_sync import _api
        self.k1 = make_node(code='K1')
        self.api = _api(self.k1)

    def _count(self, **kw):
        d = dict(node=self.k1, consumable_type='FARINE', count_date=ddate(2026, 1, 5),
                 system_quantity=Dc('10.000'), physical_quantity=Dc('9.500'), gap=Dc('-0.500'))
        d.update(kw)
        return ConsumableCount.objects.create(**d)

    def test_legacy_count_extracted_pushed_and_marked_synced_idempotent(self):
        from sync.management.commands.sync_now import apply_push_response, build_outbound_payload
        from sync.tests.test_consumable_inventory_sync import CNT, _push
        c = self._count(is_synced=False)
        payload = build_outbound_payload(self.k1.code)
        recs = payload['records'][CNT]
        self.assertEqual([r['id'] for r in recs], [str(c.pk)])
        r = _push(self.api, {CNT: recs})
        self.assertEqual(r.status_code, 200)
        res = r.data['results'][CNT]
        self.assertEqual(res[0]['status'], 'ACCEPTED')
        apply_push_response({'results': r.data['results']})
        c.refresh_from_db()
        self.assertTrue(c.is_synced)
        self.assertEqual(build_outbound_payload(self.k1.code)['records'][CNT], [])
        # rejeu du meme enregistrement : pas de doublon cote Cloud
        _push(self.api, {CNT: recs})
        self.assertEqual(ConsumableCount.objects.filter(inventory__isnull=True).count(), 1)

    def test_synced_legacy_count_not_resent(self):
        from sync.management.commands.sync_now import build_outbound_payload
        from sync.tests.test_consumable_inventory_sync import CNT
        self._count(is_synced=True)
        self.assertEqual(build_outbound_payload(self.k1.code)['records'][CNT], [])


class Bug651bNodeCode(TBase):
    def test_invoice_serializer_exposes_node_code(self):
        from sales.serializers import InvoiceSerializer
        self.assertIn('node_code', InvoiceSerializer.Meta.fields)
        self.assertIn('node_code', InvoiceSerializer.Meta.read_only_fields)
