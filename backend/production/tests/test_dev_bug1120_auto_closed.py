"""
BUG-1120 : la clôture automatique est visible dans `shift-end-status`
(`auto_closed_days`, additif) et dans `daily-closure` (`auto_closed`, persistant).
Données fictives.
"""
from datetime import time, timedelta

from production.models import _adjust_bread_stock
from production.tests.test_restes_journee_cloture_auto_a import CLOSURE, D, SHIFT, _now, _Base
from rest_framework.test import APIClient
from core.testing import make_node, make_user


class AutoClosedIndicatorTests(_Base):
    def setUp(self):
        super().setUp()
        self.node.block_sales_after_closure = True
        self.node.handover_time = time(18, 0)
        self.node.save()
        _adjust_bread_stock(self.node, self.bp, produced=100)

    def test_shift_end_status_signale_la_cloture_automatique_puis_se_tait(self):
        s = self._session()
        self._sale()
        with _now(19, 0, d=D + timedelta(days=1)):
            r1 = self.api.get(SHIFT, {'node': 'K1'})
        self.assertEqual(r1.status_code, 200, r1.data)
        self.assertEqual(r1.data['auto_closed_days'], [
            {'date': str(D), 'teams': ['A'], 'sessions': [s.pk]},
        ])
        # idempotence : rien de nouveau au second appel, corps inchangé
        with _now(19, 5, d=D + timedelta(days=1)):
            r2 = self.api.get(SHIFT, {'node': 'K1'})
        self.assertNotIn('auto_closed_days', r2.data)

    def test_pas_de_champ_sans_cloture(self):
        with _now(10, 0):
            r = self.api.get(SHIFT, {'node': 'K1'})
        self.assertEqual(r.data, {'pending_validation': False})

    def test_daily_closure_auto_closed_persistant(self):
        self._session()
        self._sale()
        self.assertFalse(self.api.get(CLOSURE, {'date': str(D)}).data['auto_closed'])
        with _now(19, 0, d=D + timedelta(days=1)):
            self.api.get(SHIFT, {'node': 'K1'})
        self.assertTrue(self.api.get(CLOSURE, {'date': str(D)}).data['auto_closed'])
        from core.models import SystemNotification
        SystemNotification.objects.update(is_read=True)  # la notification lue ne change rien
        self.assertTrue(self.api.get(CLOSURE, {'date': str(D)}).data['auto_closed'])

    def test_cloture_manuelle_n_est_pas_auto(self):
        self._session(closed=True)
        self.assertFalse(self.api.get(CLOSURE, {'date': str(D)}).data['auto_closed'])

    def test_isolation_par_boulangerie(self):
        self._session()
        self._sale()
        with _now(19, 0, d=D + timedelta(days=1)):
            self.api.get(SHIFT, {'node': 'K1'})
        other = make_node(code='K2')
        g2 = APIClient()
        g2.force_authenticate(make_user('GERANT', node=other, team='A'))
        r = g2.get(CLOSURE, {'date': str(D), 'node': 'K1'})  # `node` ignoré pour un non-HQ
        self.assertEqual(r.data['node'], 'K2')
        self.assertFalse(r.data['auto_closed'])
