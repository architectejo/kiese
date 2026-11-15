"""BUG-295 : remise annuelle = INDICE x TARIF + MERITE (classeur B2, feuille REMISE
`=(E4*F4)+G4`, TOTAL A PAYER = TOTAL SOCIAL + REMISE), versee avec la
distribution de la caisse sociale, jamais ajoutee au net mensuel des commissions.
INDICE = nombre de mois de cotisation payes ; TARIF fixe par la direction par an
et par boulangerie. Valeurs calculees a la main ; donnees fictives."""
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import SocialContribution, SocialDistribution, SocialDistributionLine
from commissions.models import ClientCommission, CommissionPeriod
from core.testing import make_client, make_node, make_user

DIST = '/api/clients/distributions/'
LINES = '/api/clients/distribution-lines/'


def _api(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


class Bug295RemiseAnnuelle(TestCase):
    def setUp(self):
        self.node = make_node(code='K2')
        self.node.monthly_social_contribution = D('2000')
        self.node.save()
        self.gerant = make_user('GERANT', node=self.node, team='', username='b295_g')
        self.a = make_client(self.node, first_name='A', last_name='Alpha')
        self.b = make_client(self.node, first_name='B', last_name='Beta')
        for m in range(1, 11):                                    # A : 10 mois payes
            SocialContribution.objects.create(client=self.a, node=self.node, month=m, year=2023,
                                              amount=D('2000'), is_paid=True)
        for m in range(1, 5):                                     # B : 4 mois, dont 3 payes
            SocialContribution.objects.create(client=self.b, node=self.node, month=m, year=2023,
                                              amount=D('2000'), is_paid=(m != 4))
        self.api = _api(self.gerant)
        r = self.api.post(DIST, {'node': self.node.pk, 'year': 2023, 'tarif': '700'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.dist = SocialDistribution.objects.get(pk=r.data['id'])
        r = self.api.post(f'{DIST}{self.dist.pk}/auto_populate_lines/')
        self.assertEqual(r.status_code, 200, r.data)

    def line(self, c):
        return SocialDistributionLine.objects.get(distribution=self.dist, client=c)

    def test_indice_tarif_merite_total_a_payer(self):
        la = self.line(self.a)
        self.assertEqual(la.indice, 10)
        self.assertEqual(la.total_social, D('20000.00'))
        self.assertEqual(la.remise, D('7000.00'))                 # 10 x 700
        r = self.api.patch(f'{LINES}{la.pk}/', {'merite': '1500'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        la.refresh_from_db()
        self.assertEqual(la.total_payer, D('28500.00'))           # 20 000 + 7 000 + 1 500
        lb = self.line(self.b)
        self.assertEqual(lb.indice, 3)                            # le mois impaye ne compte pas
        self.assertEqual(lb.remise, D('2100.00'))                 # 3 x 700
        self.assertEqual(lb.total_payer, D('6000.00') + D('2100.00'))

    def test_changement_de_tarif_recalcule_les_lignes_ouvertes(self):
        la = self.line(self.a)
        self.api.patch(f'{LINES}{la.pk}/', {'merite': '1500'}, format='json')
        r = self.api.patch(f'{DIST}{self.dist.pk}/', {'tarif': '600'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        la.refresh_from_db()
        self.assertEqual(la.remise, D('6000.00'))                 # 10 x 600
        self.assertEqual(la.total_payer, D('27500.00'))           # 20 000 + 6 000 + 1 500
        self.assertEqual(self.line(self.b).remise, D('1800.00'))  # 3 x 600

    def test_tarif_d_une_distribution_cloturee_est_fige(self):
        self.api.patch(f'{DIST}{self.dist.pk}/', {'is_closed': True}, format='json')
        r = self.api.patch(f'{DIST}{self.dist.pk}/', {'tarif': '500'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.dist.refresh_from_db()
        self.assertEqual(self.dist.tarif, D('700.00'))
        self.assertEqual(self.line(self.a).remise, D('7000.00'))

    def test_refresh_indices_apres_un_nouveau_paiement(self):
        la = self.line(self.a)
        self.api.patch(f'{LINES}{la.pk}/', {'merite': '1500'}, format='json')
        SocialContribution.objects.create(client=self.a, node=self.node, month=11, year=2023,
                                          amount=D('2000'), is_paid=True)
        r = self.api.post(f'{DIST}{self.dist.pk}/refresh_indices/')
        self.assertEqual(r.status_code, 200, r.data)
        la.refresh_from_db()
        self.assertEqual(la.indice, 11)
        self.assertEqual(la.total_social, D('22000.00'))
        self.assertEqual(la.remise, D('7700.00'))                 # 11 x 700
        self.assertEqual(la.total_payer, D('31200.00'))           # 22 000 + 7 700 + 1 500 (merite conserve)
        self.dist.is_closed = True
        self.dist.save()
        self.assertEqual(self.api.post(f'{DIST}{self.dist.pk}/refresh_indices/').status_code, 400)

    def test_tarif_par_boulangerie_et_par_annee(self):
        autre = make_node(code='K4')
        d2 = SocialDistribution.objects.create(node=autre, year=2023, tarif=D('600'))
        d3 = SocialDistribution.objects.create(node=self.node, year=2024, tarif=D('800'))
        self.assertEqual({d.tarif for d in (self.dist, d2, d3)}, {D('700.00'), D('600.00'), D('800.00')})

    def test_la_remise_annuelle_n_entre_plus_dans_le_net_mensuel(self):
        period = CommissionPeriod.objects.create(node=self.node, month=timezone.now().month,
                                                 year=timezone.now().year)
        cc = ClientCommission(period=period, client=self.a, total_breads=4000,
                              order_value=D('200000.00'), commission_rate=D('0.25'),
                              annual_bonus_incorporated=True)
        cc.compute(annual_bonus_rate=0.025)
        self.assertEqual(cc.annual_bonus, D('0.00'))              # plus de volume x 0,025
        self.assertEqual(cc.net_payable, D('50000.00'))           # CM seule, remise non ajoutee
        cc.manuel_adjustment = D('42000')
        cc.compute()
        self.assertEqual(cc.net_payable, D('42000.00'))
