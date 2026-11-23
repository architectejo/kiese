"""BUG-1005 (d49) : retenue unique (BUG-737) déterministe même quand les `created_at` sont ex aequo
(horloge grossière) et que l'ordre des UUID est l'inverse de l'ordre de création. Données fictives."""
import uuid
from datetime import datetime, timezone as dt_tz
from decimal import Decimal as D
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from commissions.models import ClientCommission
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine


class RetenueUniqueHorlogeGrossiere(TestCase):
    def setUp(self):
        self.ns = [make_node(code=c, social=D('1500'), card_fee=D('700')) for c in ('W1', 'W2', 'W3')]
        p = make_bread_price('GRAND', 'Pain 500 FC', 500)
        self.api = APIClient(raise_request_exception=True)
        self.api.force_authenticate(make_user('DIRECTION', node=None, team='', username='d49_hq'))
        self.c = make_client(self.ns[2], current_debt=D('10000'))
        for n in self.ns:
            inv = Invoice.objects.create(node=n, client=self.c, payment_type='CREDIT', status='DELIVERED',
                                         payment_amount=D('0'), invoice_date='2026-02-10', node_origin=n.code)
            InvoiceLine.objects.create(invoice=inv, bread_price=p, quantity=100)
            inv.compute_order_total()
            inv.save(update_fields=['order_total'])

    def gen(self, node):
        r = self.api.post('/api/commissions/periods/generate/', {'node': node.pk, 'month': 2, 'year': 2026},
                          format='json')
        self.assertEqual(r.status_code, 201)

    def test_imbrication_a_trois_created_at_identiques_et_uuid_inverses(self):
        mgr_cls = type(ClientCommission.objects)
        real = mgr_cls.get_or_create
        done = set()
        # Ordre de création : W2 (1re), W1, W3 ; UUID décroissants dans l'ordre inverse de création.
        ids = {self.ns[1].pk: uuid.UUID(int=(0xF << 124)), self.ns[0].pk: uuid.UUID(int=(0x8 << 124)),
               self.ns[2].pk: uuid.UUID(int=1)}

        def interleaved(mgr, *a, **kw):
            if mgr.model is ClientCommission and kw.get('period') is not None:
                node_id = kw['period'].node_id
                if node_id == self.ns[2].pk and 'a' not in done:
                    done.add('a')
                    self.gen(self.ns[0])
                elif node_id == self.ns[0].pk and 'b' not in done and 'a' in done:
                    done.add('b')
                    self.gen(self.ns[1])
                kw['defaults'] = dict(kw.get('defaults') or {}, id=ids[node_id])
            return real(mgr, *a, **kw)

        fixed = datetime(2026, 2, 20, 12, 0, 0, tzinfo=dt_tz.utc)
        with patch.object(mgr_cls, 'get_or_create', interleaved), \
                patch('django.utils.timezone.now', return_value=fixed):
            self.gen(self.ns[2])
        rows = ClientCommission.objects.filter(client=self.c)
        self.assertEqual(rows.count(), 3)
        self.assertEqual(len({r.created_at for r in rows}), 1)  # ex aequo, comme voulu
        self.assertEqual((sum(r.deduction_debt for r in rows), sum(r.deduction_social for r in rows)),
                         (D('10000.00'), D('1500.00')))
