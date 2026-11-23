"""
Clients / Commissions - ronde b22 (testeur clients/commissions, 2026-11-23). Verification independante de
BUG-1027 (taux de la boulangerie applique a la creation par facturier/livreur ; BUG-250 conserve) et
BUG-1028 (card_applied en lecture seule). Donnees FICTIVES.
"""
from decimal import Decimal as D

from commissions.models import ClientCommission, CommissionPeriod
from core.models import Config, Node
from clients.models import Client
from clients.tests.test_clients_v17 import CL, Base17, api


class Facturier1027(Base17):
    def setUp(self):
        super().setUp()
        self.rate(self.k1, D('0.30'))
        self.f2 = None
        from core.testing import make_user
        self.f2 = make_user('FACTURIER', node=self.k2, team='A')

    def create(self, user, **body):
        return super().create(type(user).objects.get(pk=user.pk), **body)  # utilisateur relu (requete reelle)

    def body(self, **extra):
        b = {'first_name': 'Fictif', 'last_name': 'Client'}
        b.update(extra)
        return b

    def test_facturier_et_livreur_prennent_le_taux_de_leur_boulangerie_k1_030_k2_025(self):
        for u in (self.f1, self.l1):
            self.assertEqual(self.create(u, **self.body()).commission_rate, D('0.30'))
        self.assertEqual(self.create(self.f2, **self.body()).commission_rate, D('0.25'))

    def test_bug250_facturier_ne_choisit_ni_taux_ni_plafond(self):
        for u in (self.f1, self.l1):
            c = self.create(u, **self.body(commission_rate='0.05', credit_limit='999999'))
            self.assertEqual(c.commission_rate, D('0.30'))
            self.assertEqual(c.credit_limit, D('50000.00'))
        c = self.create(self.f1, **self.body(commission_rate=0, credit_limit=0))
        self.assertEqual((c.commission_rate, c.credit_limit), (D('0.30'), D('50000.00')))

    def test_facturier_ne_peut_pas_cibler_une_autre_boulangerie_pour_son_taux(self):
        c = self.create(self.f1, **self.body(node=self.k2.pk))
        self.assertEqual(c.node, self.k1)
        self.assertEqual(c.commission_rate, D('0.30'))

    def test_boulangerie_a_zero_facturier_cree_a_zero_pas_de_repli_sur_config(self):
        self.rate(self.k1, D('0.00'))
        self.assertEqual(self.create(self.f1, **self.body()).commission_rate, D('0.00'))

    def test_boulangerie_sans_taux_repli_sur_config_pour_facturier(self):
        Node.objects.filter(pk=self.k1.pk).update(default_commission_rate=None)
        cfg = Config.get_instance()
        cfg.default_commission_rate = D('0.27')
        cfg.save()
        self.assertEqual(self.create(self.f1, **self.body()).commission_rate, D('0.27'))

    def test_facturier_ne_modifie_pas_le_taux_d_un_client_existant(self):
        c = self.create(self.f1, **self.body())
        r = api(self.f1).patch(f'{CL}{c.pk}/', {'commission_rate': '0.10', 'credit_limit': '1'}, format='json')
        c.refresh_from_db()
        self.assertEqual((c.commission_rate, c.credit_limit), (D('0.30'), D('50000.00')), r.status_code)

    def test_gerant_direction_taux_explicite_prioritaire_et_zero_valide(self):
        self.assertEqual(self.create(self.g1, **self.body(commission_rate='0.25')).commission_rate, D('0.25'))
        self.assertEqual(self.create(self.g1, **self.body(commission_rate='0')).commission_rate, D('0.00'))
        self.assertEqual(self.create(self.g1, **self.body()).commission_rate, D('0.30'))
        c = self.create(self.direction, **self.body(node=self.k2.pk, commission_rate='0.00'))
        self.assertEqual((c.node, c.commission_rate), (self.k2, D('0.00')))
        c = self.create(self.direction, **self.body(node=self.k2.pk))
        self.assertEqual(c.commission_rate, D('0.25'))

    def test_client_cree_a_030_genere_une_commission_a_030(self):
        from core.testing import make_bread_price
        from sales.models import Invoice, InvoiceLine
        c = self.create(self.f1, **self.body())
        p = make_bread_price(unit_price=500)
        i = Invoice.objects.create(node=self.k1, client=c, payment_type='CREDIT', status='DELIVERED',
                                   payment_amount=D('0'), invoice_date='2026-03-10', node_origin='K1')
        InvoiceLine.objects.create(invoice=i, bread_price=p, quantity=100)
        i.compute_order_total()
        i.save(update_fields=['order_total'])
        r = api(self.direction).post('/api/commissions/periods/generate/',
                                     {'node': self.k1.pk, 'month': 3, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))
        cc = ClientCommission.objects.get(client=c)
        self.assertEqual((cc.order_value, cc.commission_rate, cc.commission_gross),
                         (D('50000.00'), D('0.30'), D('15000.00')))


class CardApplied1028(Base17):
    def setUp(self):
        super().setUp()
        from core.testing import make_bread_price
        from sales.models import Invoice, InvoiceLine
        self.c = make_client_k1(self.k1)
        p = make_bread_price(unit_price=500)
        i = Invoice.objects.create(node=self.k1, client=self.c, payment_type='CREDIT', status='DELIVERED',
                                   payment_amount=D('0'), invoice_date='2026-03-10', node_origin='K1')
        InvoiceLine.objects.create(invoice=i, bread_price=p, quantity=100)
        i.compute_order_total()
        i.save(update_fields=['order_total'])
        r = api(self.direction).post('/api/commissions/periods/generate/',
                                     {'node': self.k1.pk, 'month': 3, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))
        self.cc = ClientCommission.objects.get(client=self.c)

    def test_expose_vrai_sur_la_porteuse_en_liste_et_detail(self):
        self.assertTrue(self.cc.card_applied)
        d = api(self.g1).get(f'/api/commissions/commissions/{self.cc.pk}/').data
        self.assertIs(d['card_applied'], True)
        rows = api(self.g1).get('/api/commissions/commissions/').data
        rows = rows['results'] if isinstance(rows, dict) else rows
        self.assertTrue(all('card_applied' in x for x in rows))

    def test_patch_ne_modifie_pas_card_applied(self):
        for role_user in (self.direction, self.g1):
            r = api(role_user).patch(f'/api/commissions/commissions/{self.cc.pk}/',
                                     {'card_applied': False, 'deduction_other': '10'}, format='json')
            self.cc.refresh_from_db()
            self.assertTrue(self.cc.card_applied, (r.status_code, getattr(r, 'data', None)))
            self.assertEqual(self.cc.deduction_prints, D('1000.00'))
            api(role_user).patch(f'/api/commissions/commissions/{self.cc.pk}/', {'deduction_other': '0'},
                                 format='json')

    def test_post_manuel_ne_pose_pas_card_applied(self):
        c2 = make_client_k1(self.k1)
        per = CommissionPeriod.objects.get(node=self.k1, month=3, year=2026)
        r = api(self.direction).post('/api/commissions/commissions/',
                                     {'period': per.pk, 'client': c2.pk, 'card_applied': True,
                                      'order_value': '1000', 'commission_rate': '0.25'}, format='json')
        if r.status_code == 201:
            self.assertFalse(ClientCommission.objects.get(pk=r.data['id']).card_applied)
            self.assertIs(r.data['card_applied'], False)
        else:
            self.assertLess(r.status_code, 500)


def make_client_k1(node):
    from core.testing import make_client
    return make_client(node, current_debt=D('0'))
