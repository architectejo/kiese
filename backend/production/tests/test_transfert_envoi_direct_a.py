"""BUG-380 : envoi direct de pains entre boulangeries (remarque.md, section
« Transferts Inter-Boulangeries » : envoyer sans avoir reçu de demande).

Second flux `DIRECT` à côté de « demande -> réponse -> confirmation » (REQUEST) :
`POST /api/production/transfers/send/`, statut RESPONDED d'emblée, stock de
l'émettrice déduit tout de suite, validation par la réceptrice (écart ->
litige + blocage de clôture), somme nulle au niveau du groupe (CLAUDE.md §5.4).
Données fictives uniquement.
"""
from django.db.models import Sum

from core.models import ActivityLog, SystemNotification
from core.tests.test_permissions_regression_2026_11_19 import cl, mk
from core.tests.test_verif_isolation_a_c import IsoBase
from core.workday import work_date_for
from production.models import BreadStock, BreadTransfer, BreadTransferLine, _adjust_bread_stock
from production.services import transfers_by_bread_price
from production.views import _build_daily_closure_report
from treasury.views import _unresolved_incoming_transfer_gap

URL = '/api/production/transfers/send/'


def avail(node, bp):
    s = BreadStock.objects.filter(node=node, bread_price=bp).first()
    return s.qty_available if s else 0


def group_total(bp):
    return sum(s.qty_available for s in BreadStock.objects.filter(bread_price=bp))


class DirectBase(IsoBase):
    def setUp(self):
        _adjust_bread_stock(self.k1, self.bp, produced=50)

    def send(self, user, to, lines=None, **extra):
        body = {'to_node': to, 'lines': lines if lines is not None else
                [{'bread_price': self.bp.pk, 'quantity_sent': 10}]}
        body.update(extra)
        return cl(user).post(URL, body, format='json')

    def assert_nothing_written(self, before_stock=50):
        self.assertEqual(BreadTransfer.objects.filter(flow='DIRECT').count(), 0)
        self.assertEqual(avail(self.k1, self.bp), before_stock)


class DirectSendNominal(DirectBase):
    def test_send_creates_responded_direct_and_deducts_sender_now(self):
        n_notif = SystemNotification.objects.filter(title__startswith='Pains Envoyés').count()
        r = self.send(self.u['GERANT'], self.k2.pk, notes='Dépannage')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['flow'], 'DIRECT')
        self.assertEqual(r.data['transfer_status'], 'RESPONDED')
        self.assertEqual((r.data['from_node'], r.data['to_node']), (self.k1.pk, self.k2.pk))
        self.assertEqual(r.data['lines'][0]['quantity_sent'], 10)
        self.assertEqual(avail(self.k1, self.bp), 40)
        self.assertEqual(avail(self.k2, self.bp), 0)  # rien chez la réceptrice avant validation
        t = BreadTransfer.objects.get(pk=r.data['id'])
        self.assertEqual((t.initiated_by_id, t.node_origin, t.notes), (self.u['GERANT'].pk, 'P1', 'Dépannage'))
        n = SystemNotification.objects.filter(title__startswith='Pains Envoyés').order_by('-id').first()
        self.assertEqual(SystemNotification.objects.filter(title__startswith='Pains Envoyés').count(), n_notif + 1)
        self.assertEqual(n.node_origin, 'P2')
        self.assertIn('P1', n.message)
        self.assertTrue(ActivityLog.objects.filter(action='Envoi Direct de Pains').exists())

    def test_to_node_by_code_and_forged_from_node_ignored(self):
        r = self.send(self.u['GERANT'], 'p2', from_node=self.k3.pk)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['from_node'], self.k1.pk)  # forcé côté serveur
        self.assertEqual(r.data['to_node'], self.k2.pk)

    def test_flow_and_status_not_forgeable_on_request_create(self):
        r = cl(self.u2['GERANT']).post('/api/production/transfers/', {
            'from_node': self.k1.pk, 'flow': 'DIRECT', 'transfer_status': 'CONFIRMED',
            'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 3}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((r.data['flow'], r.data['transfer_status']), ('REQUEST', 'PENDING'))

    def test_multi_lines_and_duplicate_category_merged(self):
        from core.models import BreadPrice
        bp2 = BreadPrice.objects.create(category='MICRO', label='Pain 200', unit_price=200)
        _adjust_bread_stock(self.k1, bp2, produced=5)
        r = self.send(self.u['GERANT'], self.k2.pk, lines=[
            {'bread_price': self.bp.pk, 'quantity_sent': 4},
            {'bread_price': self.bp.pk, 'quantity_sent': 6},
            {'bread_price': bp2.pk, 'quantity_sent': '5'}])
        self.assertEqual(r.status_code, 201, r.content)
        got = {l['bread_price']: l['quantity_sent'] for l in r.data['lines']}
        self.assertEqual(got, {self.bp.pk: 10, bp2.pk: 5})
        self.assertEqual((avail(self.k1, self.bp), avail(self.k1, bp2)), (40, 0))

    def test_default_flow_for_existing_rows_is_request(self):
        t = BreadTransfer.objects.create(from_node=self.k2, to_node=self.k1, node_origin='P1')
        self.assertEqual(t.flow, 'REQUEST')

    def test_both_sides_see_it_third_does_not(self):
        r = self.send(self.u['GERANT'], self.k2.pk)
        tid = r.data['id']

        def ids(user):
            d = cl(user).get('/api/production/transfers/').data
            return {x['id'] for x in (d['results'] if isinstance(d, dict) else d)}
        self.assertIn(tid, ids(self.u['GERANT']))
        self.assertIn(tid, ids(self.u2['GERANT']))
        self.assertNotIn(tid, ids(self.u3))
        flt = cl(self.u2['GERANT']).get('/api/production/transfers/?to_node=%d' % self.k2.pk)
        self.assertEqual(flt.status_code, 200)


class DirectReception(DirectBase):
    def _sent(self, qty=10):
        r = self.send(self.u['GERANT'], self.k2.pk, lines=[{'bread_price': self.bp.pk, 'quantity_sent': qty}])
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def confirm(self, user, tid, qty):
        return cl(user).post(f'/api/production/transfers/{tid}/confirm_reception/',
                             {'lines': [{'bread_price': self.bp.pk, 'quantity_received': qty}]}, format='json')

    def test_full_reception_mirror_and_group_sum_zero(self):
        before = group_total(self.bp)
        tid = self._sent(10)
        r = self.confirm(self.u2['GERANT'], tid, 10)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['transfer_status'], 'CONFIRMED')
        self.assertEqual(r.data['flow'], 'DIRECT')
        self.assertEqual((avail(self.k1, self.bp), avail(self.k2, self.bp)), (40, 10))
        s1 = BreadStock.objects.get(node=self.k1, bread_price=self.bp)
        s2 = BreadStock.objects.get(node=self.k2, bread_price=self.bp)
        self.assertEqual((s1.qty_sent, s2.qty_received), (10, 10))  # marqués « envoyés » / « reçus »
        self.assertEqual(group_total(self.bp), before)  # somme nulle
        self.assertEqual(_unresolved_incoming_transfer_gap(self.k2), '')

    def test_gap_disputes_alerts_and_blocks_closure_then_resolution_unblocks(self):
        tid = self._sent(10)
        n0 = SystemNotification.objects.filter(severity='DANGER').count()
        r = self.confirm(self.u2['GERANT'], tid, 8)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['transfer_status'], 'DISPUTED')
        self.assertEqual(SystemNotification.objects.filter(severity='DANGER').count(), n0 + 1)
        self.assertNotEqual(_unresolved_incoming_transfer_gap(self.k2), '')
        # la clôture de la réceptrice est bloquée
        from core.models import Config
        c = Config.get_instance()
        c.allow_backdated_sales = True
        c.save(update_fields=['allow_backdated_sales'])
        rc = cl(self.u2['GERANT']).post('/api/treasury/closures/', {'date': str(work_date_for(self.k2))}, format='json')
        self.assertEqual(rc.status_code, 400, rc.content)
        self.assertIn('Clôture bloquée', rc.data['detail'])
        # le groupe a perdu 2 pains tant que le litige n'est pas résolu ; la résolution rééquilibre
        rr = cl(self.u['GERANT']).post(f'/api/production/transfers/{tid}/resolve_dispute/',
                                       {'resolution': 'ALIGN_ON_RECEIVED', 'reason': 'recomptage'}, format='json')
        self.assertEqual(rr.status_code, 200, rr.content)
        self.assertEqual(_unresolved_incoming_transfer_gap(self.k2), '')
        self.assertEqual(avail(self.k1, self.bp), 42)  # 2 pains restitués à l'émettrice
        self.assertEqual(avail(self.k2, self.bp), 8)
        self.assertEqual(group_total(self.bp), 50)

    def test_only_receiver_can_confirm(self):
        tid = self._sent(10)
        r = self.confirm(self.u['GERANT'], tid, 10)  # l'émettrice elle-même
        self.assertEqual(r.status_code, 403, r.content)
        r = self.confirm(self.u3, tid, 10)  # une tierce : transfert invisible (404) ou refusé
        self.assertIn(r.status_code, (403, 404), r.content)
        self.assertEqual(BreadTransfer.objects.get(pk=tid).transfer_status, 'RESPONDED')
        self.assertEqual(avail(self.k2, self.bp), 0)

    def test_double_confirmation_credits_once(self):
        tid = self._sent(10)
        self.confirm(self.u2['GERANT'], tid, 10)
        r = self.confirm(self.u2['GERANT'], tid, 10)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(avail(self.k2, self.bp), 10)

    def test_sent_transfer_frozen_and_not_respondable(self):
        tid = self._sent(10)
        url = f'/api/production/transfers/{tid}/'
        self.assertEqual(cl(self.u['GERANT']).patch(url, {'notes': 'x'}, format='json').status_code, 400)
        self.assertEqual(cl(self.u['GERANT']).delete(url).status_code, 400)
        r = cl(self.u['GERANT']).post(url + 'respond_to_request/',
                                      {'approved': True, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 99}]},
                                      format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(avail(self.k1, self.bp), 40)  # pas de double déstockage

    def test_daily_closure_counts_direct_sends_like_other_transfers(self):
        tid = self._sent(10)
        self.confirm(self.u2['GERANT'], tid, 10)
        today = work_date_for(self.k1)
        sent, _recv = transfers_by_bread_price(self.k1, today)
        _s, received = transfers_by_bread_price(self.k2, today)
        self.assertEqual(sent.get(self.bp.pk), 10)
        self.assertEqual(received.get(self.bp.pk), 10)
        for node, key, expected in ((self.k1, 'appro_effectue', 10), (self.k2, 'appro_recu', 10)):
            rep = _build_daily_closure_report(node, today)
            row = next(c for c in rep['categories'] if c['bread_price'] == self.bp.pk)
            self.assertEqual(row[key]['quantity'], expected, key)
        # non confirmé : pas compté (même règle que le flux demande/réponse)
        tid2 = self._sent(5)
        sent, _ = transfers_by_bread_price(self.k1, today)
        self.assertEqual(sent.get(self.bp.pk), 10)
        self.assertEqual(BreadTransfer.objects.get(pk=tid2).transfer_status, 'RESPONDED')


class DirectSendGuards(DirectBase):
    def test_facturier_livreur_anonymous_refused(self):
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(self.send(self.u[role], self.k2.pk).status_code, 403, role)
        self.assertIn(cl().post(URL, {}, format='json').status_code, (401, 403))
        self.assert_nothing_written()

    def test_node_less_accounts(self):
        orphan = mk('orph_a6', 'GERANT', None)
        self.assertEqual(self.send(orphan, self.k2.pk).status_code, 403)
        # siège sans boulangerie : règle de la création de demande (400 français)
        r = self.send(self.u['DIRECTION'], self.k2.pk)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('detail', r.data)
        self.assert_nothing_written()

    def test_hq_account_attached_to_a_node_sends_from_that_node(self):
        hq = mk('hq_k1_a6', 'DIRECTION', self.k1)
        r = self.send(hq, self.k2.pk)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['from_node'], self.k1.pk)

    def test_gerant_cannot_send_from_another_bakery(self):
        # K2 n'a pas de pains ; K1 en a : l'envoi du gérant K2 part de K2 (refusé : stock), jamais de K1.
        r = self.send(self.u2['GERANT'], self.k1.pk, from_node=self.k1.pk)
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(avail(self.k1, self.bp), 50)

    def test_destination_validation(self):
        for to, label in ((self.k1.pk, 'soi-même par pk'), ('P1', 'soi-même par code'), (None, 'absent'),
                          ('', 'vide'), (99999, 'inconnu'), ('9' * 40, 'entier géant'), (10 ** 40, 'entier géant num'), ('ZZZ', 'code inconnu'), (True, 'booléen')):
            r = self.send(self.u['GERANT'], to)
            self.assertEqual(r.status_code, 400, (label, r.content))
            self.assertIn('detail', r.data, label)
        self.assert_nothing_written()

    def test_lines_validation_never_writes_never_500(self):
        bp = self.bp.pk
        bad = [
            [], None, 'x', {'bread_price': bp},
            ['x'], [{'bread_price': 99999, 'quantity_sent': 1}], [{'quantity_sent': 1}],
            [{'bread_price': 'abc', 'quantity_sent': 1}],
            [{'bread_price': bp, 'quantity_sent': 0}], [{'bread_price': bp, 'quantity_sent': -3}],
            [{'bread_price': bp, 'quantity_sent': 1.5}], [{'bread_price': bp, 'quantity_sent': 'abc'}],
            [{'bread_price': bp, 'quantity_sent': True}], [{'bread_price': bp}],
            [{'bread_price': bp, 'quantity_sent': 10 ** 12}],
            [{'bread_price': bp, 'quantity_sent': 1}, {'bread_price': 99999, 'quantity_sent': 1}],
        ]
        for lines in bad:
            body = {'to_node': self.k2.pk}
            if lines is not None:
                body['lines'] = lines
            r = cl(self.u['GERANT']).post(URL, body, format='json')
            self.assertEqual(r.status_code, 400, (lines, r.content))
            self.assertIn('detail', r.data, lines)
        r = cl(self.u['GERANT']).post(URL, [1, 2], format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = self.send(self.u['GERANT'], self.k2.pk, notes=['x'])
        self.assertEqual(r.status_code, 400, r.content)
        self.assert_nothing_written()

    def test_insufficient_stock_refused_atomically(self):
        from core.models import BreadPrice
        bp2 = BreadPrice.objects.create(category='MICRO', label='Pain 200', unit_price=200)  # aucun stock
        r = self.send(self.u['GERANT'], self.k2.pk, lines=[
            {'bread_price': self.bp.pk, 'quantity_sent': 10}, {'bread_price': bp2.pk, 'quantity_sent': 1}])
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('Stock insuffisant', r.data['detail'])
        self.assertIn('Pain 200', r.data['detail'])
        self.assert_nothing_written()  # rien de déduit sur la 1re ligne non plus
        r = self.send(self.u['GERANT'], self.k2.pk, lines=[{'bread_price': self.bp.pk, 'quantity_sent': 51}])
        self.assertEqual(r.status_code, 400, r.content)
        self.assert_nothing_written()

    def test_sequential_sends_cannot_oversell_stock(self):
        # concurrence simulée : deux envois de 30 sur 50 -> le second voit le stock déjà déduit
        r1 = self.send(self.u['GERANT'], self.k2.pk, lines=[{'bread_price': self.bp.pk, 'quantity_sent': 30}])
        r2 = self.send(self.u['GERANT'], self.k3.pk, lines=[{'bread_price': self.bp.pk, 'quantity_sent': 30}])
        self.assertEqual((r1.status_code, r2.status_code), (201, 400), (r1.content, r2.content))
        self.assertEqual(avail(self.k1, self.bp), 20)
        self.assertEqual(BreadTransfer.objects.filter(flow='DIRECT').count(), 1)
        # exactement le solde : accepté, stock à 0 (jamais négatif)
        r3 = self.send(self.u['GERANT'], self.k3.pk, lines=[{'bread_price': self.bp.pk, 'quantity_sent': 20}])
        self.assertEqual(r3.status_code, 201, r3.content)
        self.assertEqual(avail(self.k1, self.bp), 0)

    def test_stock_row_locked_with_select_for_update(self):
        from unittest import mock
        from django.db.models.query import QuerySet
        calls = []
        orig = QuerySet.select_for_update

        def spy(self_, *a, **k):
            calls.append(self_.model)
            return orig(self_, *a, **k)
        with mock.patch.object(QuerySet, 'select_for_update', spy):
            self.assertEqual(self.send(self.u['GERANT'], self.k2.pk).status_code, 201)
        self.assertIn(BreadStock, calls)


class RequestFlowNonRegression(DirectBase):
    """Le flux demande -> réponse -> confirmation est inchangé."""

    def test_request_respond_confirm_still_works(self):
        k2 = cl(self.u2['GERANT'])
        r = k2.post('/api/production/transfers/', {
            'from_node': self.k1.pk, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 7}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        tid = r.data['id']
        self.assertEqual((r.data['flow'], r.data['transfer_status'], r.data['to_node']), ('REQUEST', 'PENDING', self.k2.pk))
        self.assertEqual(avail(self.k1, self.bp), 50)  # pas de déstockage à la demande
        r = cl(self.u['GERANT']).post(f'/api/production/transfers/{tid}/respond_to_request/',
                                      {'approved': True, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 7}]},
                                      format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.data['transfer_status'], r.data['flow']), ('RESPONDED', 'REQUEST'))
        self.assertEqual(avail(self.k1, self.bp), 43)
        r = k2.post(f'/api/production/transfers/{tid}/confirm_reception/',
                    {'lines': [{'bread_price': self.bp.pk, 'quantity_received': 7}]}, format='json')
        self.assertEqual(r.data['transfer_status'], 'CONFIRMED')
        self.assertEqual((avail(self.k1, self.bp), avail(self.k2, self.bp), group_total(self.bp)), (43, 7, 50))

    def test_send_route_does_not_shadow_detail_routes(self):
        r = cl(self.u['GERANT']).get('/api/production/transfers/')
        self.assertEqual(r.status_code, 200)
        r = cl(self.u['GERANT']).get(URL)
        self.assertEqual(r.status_code, 405)
