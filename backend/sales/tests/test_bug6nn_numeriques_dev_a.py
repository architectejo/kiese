"""BUG-6NN (sales) : identifiants et quantités entrants durcis (NaN, Infinity, exposants,
booléens, flottants, chaînes énormes) : 400 en français, jamais 500 ni troncature.
Données fictives uniquement."""
from sales.models import Invoice
from sales.tests.test_bug318_non_servi_livraison_partielle import Base, INV

HUGE = 10 ** 30


class DeliverServedLines(Base):
    def raw_deliver(self, inv, lines_json):
        return self.api(self.fact).post(
            f'{INV}{inv.pk}/deliver/', '{"lines": %s}' % lines_json, content_type='application/json')

    def test_nan_inf_float_id_and_huge_are_400_not_500(self):
        inv = self.post()
        lid = inv.lines.first().pk
        for lines in ('[{"id": %d, "quantity": NaN}]' % lid,
                      '[{"id": %d, "quantity": Infinity}]' % lid,
                      '[{"id": %d, "quantity": -Infinity}]' % lid,
                      '[{"id": %d, "quantity": 1e400}]' % lid,
                      '[{"id": 1e400, "quantity": 1}]',
                      '[{"id": NaN, "quantity": 1}]',
                      '[{"id": %d.5, "quantity": 1}]' % lid,
                      '[{"id": %d.0, "quantity": 1}]' % lid,
                      '[{"id": [%d], "quantity": 1}]' % lid,
                      '[{"id": "%s", "quantity": 1}]' % ('9' * 5000),
                      '[{"id": %d, "quantity": "%s"}]' % (lid, '9' * 5000)):
            r = self.raw_deliver(inv, lines)
            self.assertEqual(r.status_code, 400, (lines[:60], r.status_code))
            self.assertIn('detail', r.data)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PENDING)


class AdjustLines(Base):
    def delivered(self):
        inv = self.post()
        r = self.deliver(inv)
        self.assertEqual(r.status_code, 200, r.content)
        return inv

    def raw_adjust(self, inv, lines_json):
        return self.api(self.gerant).post(
            f'{INV}{inv.pk}/adjust/', '{"adjustment_sign": 1, "payment_amount": "0", "lines": %s}' % lines_json,
            content_type='application/json')

    def test_adjust_bad_ids_and_quantities_are_400(self):
        inv = self.delivered()
        bp = self.bp.pk
        for lines in ('[{"bread_price": true, "quantity": 1}]',
                      '[{"bread_price": %d.5, "quantity": 1}]' % bp,
                      '[{"bread_price": 1e400, "quantity": 1}]',
                      '[{"bread_price": %d, "quantity": 1e400}]' % bp,
                      '[{"bread_price": %d, "quantity": NaN}]' % bp,
                      '[{"bread_price": %d, "quantity": 2.5}]' % bp,
                      '[{"bread_price": %d, "quantity": %d}]' % (bp, HUGE),
                      '[{"bread_price": %d, "quantity": 100001}]' % bp,
                      '[{"bread_price": %d, "quantity": true}]' % bp,
                      '[{"bread_price": %d, "quantity": "%s"}]' % (bp, '9' * 5000),
                      '[{"bread_price": %d, "quantity": 1}]' % HUGE):
            r = self.raw_adjust(inv, lines)
            self.assertEqual(r.status_code, 400, (lines[:70], r.status_code))
            self.assertIn('detail', r.data)
        self.assertFalse(Invoice.objects.filter(adjusts=inv).exists())


class CreateInputs(Base):
    def test_payment_amount_and_node_extremes_are_400(self):
        for pay in ('1e400', '-1e400', 'NaN', 'Infinity', '9' * 5000):
            r = self.api(self.fact).post(INV, {
                'payment_type': 'CREDIT', 'payment_amount': pay, 'client': str(self.cl.pk),
                'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}, format='json')
            self.assertEqual(r.status_code, 400, (pay[:20], r.status_code))
        for node in (HUGE, True, 1.5, '1e400'):
            r = self.api(self.fact).post(INV, {
                'payment_type': 'CREDIT', 'payment_amount': '0', 'node': node,
                'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}, format='json')
            self.assertLess(r.status_code, 500, (str(node)[:20], r.status_code))


class BreadSummaryNodeParam(Base):
    def test_node_param_extremes_are_400_for_hq(self):
        hq = __import__('core.testing', fromlist=['make_user']).make_user('ADMIN', node=None)
        for bad in ('abc', '1.5', '1e400', '9' * 5000, '-1', '1_0'):
            r = self.api(hq).get(f'{INV}bread_summary/', {'node': bad})
            self.assertEqual(r.status_code, 400, (bad[:20], r.status_code))
        self.assertEqual(self.api(hq).get(f'{INV}bread_summary/', {'node': self.node.pk}).status_code, 200)
