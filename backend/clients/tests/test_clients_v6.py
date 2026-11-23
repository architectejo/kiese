"""Clients / Commissions / Caisse sociale / Sync - ronde b9 (testeur Clients/Commissions, 2026-11-23).

1. Regression des flux legitimes (valeurs realistes calculees a la main) apres
   AsciiDigitsMixin elargi, gel des periodes (BUG-893/889), caisse sociale close
   (BUG-872/887) : creation, import Excel, generation de paie, retenues BUG-737,
   mark_paid, cloture de distribution.
2. Push sync (Client, DebtMovement, SocialContribution, SocialDistribution(+Line),
   ClientCommission) compare aux regles REST (bornes, ASCII, scope noeud).
Donnees FICTIVES. Code applicatif non modifie.
"""
import io
import uuid
from datetime import date
from decimal import Decimal as D
from unittest import expectedFailure

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from clients.models import (
    Client, SocialContribution, SocialDistribution, SocialDistributionLine,
)
from clients.tests.test_clients_v2 import CL, CONTRIB, DISTRIB, LINES, Base, api
from commissions.models import ClientCommission, CommissionPeriod
from core.models import Node
from core.testing import make_bread_price, make_client, make_user
from sales.models import Invoice, InvoiceLine
from sync.models import DebtMovement, NodeAuthToken

PERIODS = '/api/commissions/periods/'
COMMS = '/api/commissions/commissions/'
PUSH = '/api/sync/push/'
TODAY = date.today()


def _delivered(node, client, bp, qty):
    inv = Invoice.objects.create(
        node=node, client=client, payment_type=Invoice.PaymentType.CASH,
        status=Invoice.Status.DELIVERED, payment_amount=D('0.00'), node_origin=node.code)
    InvoiceLine.objects.create(invoice=inv, bread_price=bp, quantity=qty)
    inv.compute_order_total()
    inv.save(update_fields=['order_total'])
    return inv


def node_api(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    c = APIClient(raise_request_exception=False)
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return c


def push(c, label, rec):
    r = c.post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {label: [rec]}}, format='json')
    assert r.status_code == 200, (r.status_code, getattr(r, 'data', None))
    return r.data['results'][label][0]


# ----------------------------------------------------------------------------
# 1. Regression des flux legitimes
# ----------------------------------------------------------------------------
class RegressionFluxLegitimes(Base):
    def setUp(self):
        super().setUp()
        Node.objects.filter(pk=self.k1.pk).update(monthly_social_contribution=D('2000.00'), card_fee_fc=D('1000.00'))
        Node.objects.filter(pk=self.k3.pk).update(monthly_social_contribution=D('2000.00'), card_fee_fc=D('500.00'))
        self.k1.refresh_from_db()
        self.k3.refresh_from_db()
        self.bp = make_bread_price(category='MOYEN', unit_price=500)

    def test_creation_client_import_excel_et_paie_complete(self):
        # creation REST par le gerant K1, valeurs realistes
        r = api(self.g1).post(CL, {'first_name': 'Mireille', 'last_name': 'Kimbembe', 'phone': '0990001122',
                                   'credit_limit': '50000', 'commission_rate': '0.25', 'client_type': 'DETAILLANT'},
                              format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['code'].startswith('K1-'))
        # import Excel fictif
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        ws = wb.create_sheet('CL-K1 TABO')
        ws.append(['DATE', 'CODE', 'NOM'])
        ws.append(['2026-11-01', 'C1', 'Jean Pierre DEMO'])
        ws.append(['2026-11-02', 'C2', 'Mireille Kimbembe'])  # doublon du client cree
        buf = io.BytesIO()
        wb.save(buf)
        f = SimpleUploadedFile('fictif.xlsx', buf.getvalue(),
                               content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        r = api(self.direction).post(CL + 'import_excel/', {'file': f}, format='multipart')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['created'], 1)
        self.assertEqual(Client.objects.filter(node=self.k1).count(), 2)

    def test_paie_mark_paid_regeneration_cloture(self):
        a = make_client(self.k1, last_name='AAA', current_debt=D('3000.00'))
        b = make_client(self.k1, last_name='BBB', commission_rate=D('0.30'))
        _delivered(self.k1, a, self.bp, 80)   # 40 000 -> CM 10 000
        _delivered(self.k1, b, self.bp, 100)  # 50 000 -> CM 15 000 a 30 %
        r = api(self.direction).post(PERIODS + 'generate/', {'node': str(self.k1.pk), 'month': TODAY.month,
                                                             'year': TODAY.year}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        ca = ClientCommission.objects.get(client=a)
        cb = ClientCommission.objects.get(client=b)
        # AAA : 10000 - dette 3000 - social 2000 - carte 1000 = 4000
        self.assertEqual((ca.commission_gross, ca.total_deductions, ca.net_payable),
                         (D('10000.00'), D('6000.00'), D('4000.00')))
        # BBB : 15000 - 0 - 2000 - 1000 = 12000
        self.assertEqual((cb.commission_gross, cb.net_payable), (D('15000.00'), D('12000.00')))
        s = api(self.direction).get(COMMS + 'summary/', {'period__month': TODAY.month, 'period__year': TODAY.year})
        self.assertEqual((D(s.data['total_cm']), D(s.data['total_net']), D(s.data['total_deductions'])),
                         (D('25000'), D('16000'), D('9000')))
        # mark_paid
        r = api(self.direction).post(f'{COMMS}{ca.pk}/mark_paid/', {'paid_by': 'Caissier'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        # regeneration : la commission payee reste intacte, l'autre est rafraichie
        _delivered(self.k1, b, self.bp, 20)  # +10 000 -> 60 000 -> CM 18 000
        r = api(self.direction).post(PERIODS + 'generate/', {'node': str(self.k1.pk), 'month': TODAY.month,
                                                             'year': TODAY.year}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        ca.refresh_from_db(); cb.refresh_from_db()
        self.assertTrue(ca.is_paid)
        self.assertEqual(ca.net_payable, D('4000.00'))
        self.assertEqual(cb.net_payable, D('15000.00'))
        # modification de la commission payee et cloture
        self.assertEqual(api(self.direction).patch(f'{COMMS}{ca.pk}/', {'deduction_other': '10'}, format='json').status_code, 400)
        period = CommissionPeriod.objects.get(node=self.k1)
        r = api(self.direction).post(f'{PERIODS}{period.pk}/close_period/')
        self.assertEqual(r.status_code, 200, r.data)
        # periode close : generation, modif, creation refusees ; lecture OK
        self.assertEqual(api(self.direction).post(PERIODS + 'generate/', {'node': str(self.k1.pk), 'month': TODAY.month,
                         'year': TODAY.year}, format='json').status_code, 400)
        self.assertEqual(api(self.direction).patch(f'{COMMS}{cb.pk}/', {'deduction_other': '10'}, format='json').status_code, 400)
        self.assertEqual(api(self.g1).get(COMMS, {'period': str(period.pk)}).status_code, 200)

    def test_bug737_client_facture_dans_deux_boulangeries_retenu_une_fois(self):
        c = make_client(self.k1, last_name='MULTI', current_debt=D('2500.00'))
        _delivered(self.k1, c, self.bp, 40)  # 20 000 -> CM 5 000
        _delivered(self.k3, c, self.bp, 40)
        for n in (self.k1, self.k3):
            r = api(self.direction).post(PERIODS + 'generate/', {'node': str(n.pk), 'month': TODAY.month,
                                                                 'year': TODAY.year}, format='json')
            self.assertEqual(r.status_code, 201, r.data)
        k1 = ClientCommission.objects.get(client=c, period__node=self.k1)
        k3 = ClientCommission.objects.get(client=c, period__node=self.k3)
        # K1 (premiere) : 5000 - 2500 - 2000 - 1000 = -500 ; K3 : 5000 - 0 - 0 - 500 = 4500
        self.assertEqual(k1.net_payable, D('-500.00'))
        self.assertEqual((k3.deduction_debt, k3.deduction_social, k3.net_payable), (D('0.00'), D('0.00'), D('4500.00')))
        # un net negatif ne se paie pas
        self.assertEqual(api(self.direction).post(f'{COMMS}{k1.pk}/mark_paid/', {}, format='json').status_code, 400)

    def test_caisse_sociale_cycle_complet_et_cloture(self):
        c = make_client(self.k1, last_name='SOC')
        r = api(self.g1).post(CONTRIB + 'bulk_create_month/', {'node': str(self.k1.pk), 'month': 1, 'year': 2026}, format='json')
        self.assertEqual((r.status_code, r.data['created']), (200, 1))
        for m in (2, 3):
            self.assertEqual(api(self.g1).post(CONTRIB, {'client': str(c.id), 'node': self.k1.pk, 'month': m,
                                                         'year': 2026, 'amount': '2000'}, format='json').status_code, 201)
        for contrib in SocialContribution.objects.filter(client=c):
            self.assertEqual(api(self.g1).post(f'{CONTRIB}{contrib.pk}/toggle_paid/').status_code, 200)
        r = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2026, 'tarif': '700'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        d = r.data['id']
        r = api(self.g1).post(f'{DISTRIB}{d}/auto_populate_lines/')
        self.assertEqual(r.status_code, 200, r.data)
        line = SocialDistributionLine.objects.get(client=c)
        # indice 3, total social 6000, remise 3 x 700 = 2100, total 8100
        self.assertEqual((line.indice, line.total_social, line.remise, line.total_payer),
                         (3, D('6000.00'), D('2100.00'), D('8100.00')))
        r = api(self.g1).patch(f'{LINES}{line.pk}/', {'merite': '900'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['total_payer'], '9000.00')
        self.assertEqual(api(self.direction).patch(f'{DISTRIB}{d}/', {'is_closed': True}, format='json').status_code, 200)
        # lecture et reprise de la liste apres cloture
        self.assertEqual(api(self.g1).get(f'{DISTRIB}{d}/').data['lines'][0]['total_payer'], '9000.00')
        self.assertEqual(api(self.g1).post(f'{DISTRIB}{d}/refresh_indices/').status_code, 400)
        self.assertEqual(api(self.direction).delete(f'{DISTRIB}{d}/').status_code, 400)
        # une nouvelle annee reste possible
        self.assertEqual(api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2027, 'tarif': '800'},
                                                  format='json').status_code, 201)


# ----------------------------------------------------------------------------
# 2. Chiffres non ASCII sur les serializers clients / commissions restants (REST)
# ----------------------------------------------------------------------------
class AsciiRest(Base):
    def setUp(self):
        super().setUp()
        self.c1 = self.mk(self.k1, 'A', 'A')

    def test_BUG_915_cotisation_montant_chiffres_arabes_refuse(self):
        r = api(self.g1).post(CONTRIB, {'client': str(self.c1.id), 'node': self.k1.pk, 'month': 5,
                                        'year': 2026, 'amount': '٣٠٠٠'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(SocialContribution.objects.filter(client=self.c1).exists())

    def test_BUG_915_distribution_tarif_et_ligne_chiffres_arabes_refuses(self):
        r = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2026, 'tarif': '٧٠٠'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(SocialDistribution.objects.exists())
        d = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2026, 'tarif': '700'}, format='json').data['id']
        r = api(self.g1).post(LINES, {'distribution': d, 'client': str(self.c1.id), 'merite': '٥٠٠'},
                              format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(SocialDistributionLine.objects.exists())

    def test_BUG_915_bulk_create_month_et_generate_chiffres_non_ascii_refuses(self):
        r = api(self.g1).post(CONTRIB + 'bulk_create_month/', {'node': str(self.k1.pk), 'month': '１１',
                                                               'year': 2026}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        r = api(self.direction).post(PERIODS + 'generate/', {'node': str(self.k1.pk), 'month': '１１',
                                                             'year': 2026}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(CommissionPeriod.objects.exists())

    def test_ascii_legitimes_toujours_acceptes_sur_ces_routes(self):
        r = api(self.g1).post(CONTRIB, {'client': str(self.c1.id), 'node': self.k1.pk, 'month': 5, 'year': 2026,
                                        'amount': 2000.5},
                              format='json')
        self.assertEqual(r.status_code, 201, r.data)
        r = api(self.direction).post(PERIODS, {'node': self.k1.pk, 'month': 6, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 201, r.data)


# ----------------------------------------------------------------------------
# 3. Push sync vs regles REST
# ----------------------------------------------------------------------------
class PushSync(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.own = self.mk(self.k1, 'Own', 'Own')
        self.foreign = self.mk(self.k3, 'For', 'Eign')

    # --- chemins legitimes (regression) ---
    def test_push_legitime_client_cotisation_distribution_ligne_mouvement(self):
        cid = str(uuid.uuid4())
        r = push(self.n1, 'clients.Client', {'id': cid, 'code': 'K1-9001', 'first_name': 'Aline', 'last_name': 'Demo',
                                              'credit_limit': '50000.00', 'commission_rate': '0.25',
                                              'client_type': 'DETAILLANT', 'node': 'K1', 'node_origin': 'K1'})
        self.assertEqual(r['status'], 'ACCEPTED', r)
        sid = str(uuid.uuid4())
        r = push(self.n1, 'clients.SocialContribution', {'id': sid, 'client': cid, 'node': 'K1', 'month': 3,
                                                         'year': 2026, 'amount': '2000.00', 'is_paid': True})
        self.assertEqual(r['status'], 'ACCEPTED', r)
        did = str(uuid.uuid4())
        r = push(self.n1, 'clients.SocialDistribution', {'id': did, 'node': 'K1', 'year': 2026, 'tarif': '700.00'})
        self.assertEqual(r['status'], 'ACCEPTED', r)
        lid = str(uuid.uuid4())
        r = push(self.n1, 'clients.SocialDistributionLine', {'id': lid, 'distribution': did, 'client': cid, 'indice': 1,
                                                              'total_social': '2000.00', 'remise': '700.00',
                                                              'merite': '0.00', 'total_payer': '2700.00'})
        self.assertEqual(r['status'], 'ACCEPTED', r)
        r = push(self.n1, 'sync.DebtMovement', {'id': str(uuid.uuid4()), 'client': cid, 'amount': '15000.00',
                                                'kind': 'ORDER'})
        self.assertEqual(r['status'], 'ACCEPTED', r)
        self.assertEqual(Client.objects.get(pk=cid).current_debt, D('15000.00'))
        # cloture de distribution par push puis ligne figee
        r = push(self.n1, 'clients.SocialDistribution', {'id': did, 'is_closed': True})
        self.assertEqual(r['status'], 'ACCEPTED')
        r = push(self.n1, 'clients.SocialDistributionLine', {'id': lid, 'distribution': did, 'merite': '5000'})
        self.assertEqual(r['status'], 'REJECTED')
        self.assertEqual(SocialDistributionLine.objects.get(pk=lid).merite, D('0.00'))

    def test_push_debt_movement_client_d_une_autre_boulangerie_est_legitime(self):
        r = push(self.n1, 'sync.DebtMovement', {'id': str(uuid.uuid4()), 'client': str(self.foreign.id),
                                                'amount': '1000', 'kind': 'ORDER'})
        self.assertEqual(r['status'], 'ACCEPTED', r)

    def test_push_modele_commission_non_supporte_rien_ne_change(self):
        period = CommissionPeriod.objects.create(node=self.k1, month=10, year=2026, is_closed=True)
        cc = ClientCommission.objects.create(period=period, client=self.own, order_value=D('1000'), is_paid=True,
                                             net_payable=D('250'))
        pid = str(uuid.uuid4())
        for label, rec in (('commissions.ClientCommission', {'id': str(cc.pk), 'net_payable': '999999', 'is_paid': False}),
                           ('commissions.CommissionPeriod', {'id': str(period.pk), 'is_closed': False}),
                           ('commissions.CommissionPeriod', {'id': pid, 'node': 'K1', 'month': 11, 'year': 2026})):
            r = push(self.n1, label, rec)
            self.assertEqual(r['status'], 'REJECTED', (label, r))
        cc.refresh_from_db(); period.refresh_from_db()
        self.assertEqual((cc.net_payable, cc.is_paid, period.is_closed), (D('250.00'), True, True))
        self.assertFalse(CommissionPeriod.objects.filter(pk=pid).exists())

    def test_push_scope_noeud_refuse(self):
        r = push(self.n1, 'clients.SocialContribution', {'id': str(uuid.uuid4()), 'client': str(self.own.id),
                                                         'node': 'K3', 'month': 3, 'year': 2026})
        self.assertEqual(r['status'], 'REJECTED', r)
        r = push(self.n1, 'clients.Client', {'id': str(uuid.uuid4()), 'first_name': 'X', 'last_name': 'Y', 'node': 'K3'})
        self.assertEqual(r['status'], 'REJECTED', r)
        r = push(self.n1, 'clients.SocialDistribution', {'id': str(uuid.uuid4()), 'node': 'K3', 'year': 2026})
        self.assertEqual(r['status'], 'REJECTED', r)

    def test_push_cotisation_doublon_client_mois_annee_rejete_sans_500(self):
        SocialContribution.objects.create(client=self.own, node=self.k1, month=3, year=2026, amount=D('2000'))
        r = push(self.n1, 'clients.SocialContribution', {'id': str(uuid.uuid4()), 'client': str(self.own.id),
                                                         'node': 'K1', 'month': 3, 'year': 2026, 'amount': '2000'})
        self.assertEqual(r['status'], 'REJECTED', r)
        self.assertEqual(SocialContribution.objects.filter(client=self.own).count(), 1)

    # --- bornes (REST) ---
    def _client_rec(self, **kw):
        rec = {'id': str(uuid.uuid4()), 'first_name': 'Bo', 'last_name': 'Rne', 'node': 'K1', 'node_origin': 'K1'}
        rec.update(kw)
        return rec

    def test_BUG_916_push_client_taux_commission_hors_borne_rejete(self):
        for rate in ('0.95', '5.00', '-0.10'):
            rec = self._client_rec(commission_rate=rate)
            r = push(self.n1, 'clients.Client', rec)
            self.assertEqual(r['status'], 'REJECTED', (rate, r))
            self.assertFalse(Client.objects.filter(pk=rec['id']).exists(), rate)

    def test_BUG_916_push_client_plafond_negatif_ou_superieur_a_10_millions_rejete(self):
        for limit in ('-5000', '99999999999.00', '10000000.01'):
            rec = self._client_rec(credit_limit=limit)
            r = push(self.n1, 'clients.Client', rec)
            self.assertEqual(r['status'], 'REJECTED', (limit, r))
            self.assertFalse(Client.objects.filter(pk=rec['id']).exists(), limit)

    def test_BUG_916_push_client_cotisation_negative_ou_noms_vides_rejetes(self):
        for kw in ({'cotisation_sociale': '-100'}, {'first_name': ''}, {'last_name': ''}):
            rec = self._client_rec(**kw)
            r = push(self.n1, 'clients.Client', rec)
            self.assertEqual(r['status'], 'REJECTED', (kw, r))
            self.assertFalse(Client.objects.filter(pk=rec['id']).exists(), kw)

    def test_BUG_917_push_cotisation_montant_negatif_ou_mois_hors_borne_rejete(self):
        for kw in ({'amount': '-2000'}, {'month': 13}, {'month': 99}):
            rec = {'id': str(uuid.uuid4()), 'client': str(self.own.id), 'node': 'K1', 'month': 3, 'year': 2026,
                   'amount': '2000'}
            rec.update(kw)
            r = push(self.n1, 'clients.SocialContribution', rec)
            self.assertEqual(r['status'], 'REJECTED', (kw, r))
            self.assertFalse(SocialContribution.objects.filter(pk=rec['id']).exists(), kw)

    def test_BUG_917_push_modif_cotisation_existante_montant_negatif_rejetee(self):
        sc = SocialContribution.objects.create(client=self.own, node=self.k1, month=3, year=2026, amount=D('2000'))
        r = push(self.n1, 'clients.SocialContribution', {'id': str(sc.pk), 'amount': '-2000'})
        self.assertEqual(r['status'], 'REJECTED', r)
        sc.refresh_from_db()
        self.assertEqual(sc.amount, D('2000.00'))

    def test_BUG_917_push_cotisation_pour_client_d_une_autre_boulangerie_rejete(self):
        # REST : « Ce client n'appartient pas a la boulangerie indiquee » (BUG-249)
        rec = {'id': str(uuid.uuid4()), 'client': str(self.foreign.id), 'node': 'K1', 'month': 3, 'year': 2026,
               'amount': '2000'}
        r = push(self.n1, 'clients.SocialContribution', rec)
        self.assertEqual(r['status'], 'REJECTED', r)
        self.assertFalse(SocialContribution.objects.filter(pk=rec['id']).exists())

    def test_BUG_918_push_ligne_distribution_indice_merite_et_client_hors_regles(self):
        did = str(uuid.uuid4())
        self.assertEqual(push(self.n1, 'clients.SocialDistribution', {'id': did, 'node': 'K1', 'year': 2026,
                                                                       'tarif': '700'})['status'], 'ACCEPTED')
        cases = ({'client': str(self.own.id), 'indice': 99},
                 {'client': str(self.own.id), 'merite': '-500'},
                 {'client': str(self.foreign.id), 'indice': 1})
        for kw in cases:
            rec = {'id': str(uuid.uuid4()), 'distribution': did}
            rec.update(kw)
            r = push(self.n1, 'clients.SocialDistributionLine', rec)
            self.assertEqual(r['status'], 'REJECTED', (kw, r))
            self.assertFalse(SocialDistributionLine.objects.filter(pk=rec['id']).exists(), kw)

    def test_BUG_918_push_ligne_total_a_recevoir_incoherent_non_stocke_tel_quel(self):
        # REST : remise et total_payer sont calcules (read-only) : remise = indice x tarif.
        did = str(uuid.uuid4())
        push(self.n1, 'clients.SocialDistribution', {'id': did, 'node': 'K1', 'year': 2026, 'tarif': '700'})
        rec = {'id': str(uuid.uuid4()), 'distribution': did, 'client': str(self.own.id), 'indice': 2,
               'total_social': '4000', 'remise': '9999999', 'merite': '0', 'total_payer': '1.00'}
        push(self.n1, 'clients.SocialDistributionLine', rec)
        line = SocialDistributionLine.objects.filter(pk=rec['id']).first()
        # soit rejetee, soit recalculee : 2 x 700 = 1400 ; 4000 + 1400 = 5400
        if line is not None:
            self.assertEqual((line.remise, line.total_payer), (D('1400.00'), D('5400.00')))

    # --- ASCII (push) ---
    def test_push_chiffres_arabes_refuses_sur_montants_clients_et_caisse_sociale(self):
        arabic = '٣٠٠٠'
        did = str(uuid.uuid4())
        push(self.n1, 'clients.SocialDistribution', {'id': did, 'node': 'K1', 'year': 2026, 'tarif': '700'})
        sc_id, cl_id, ln_id, mv_id = (str(uuid.uuid4()) for _ in range(4))
        recs = (
            ('clients.SocialContribution', {'id': sc_id, 'client': str(self.own.id), 'node': 'K1', 'month': 4,
                                            'year': 2026, 'amount': arabic}, SocialContribution, sc_id),
            ('clients.Client', {'id': cl_id, 'first_name': 'A', 'last_name': 'B', 'node': 'K1',
                                'credit_limit': arabic}, Client, cl_id),
            ('clients.SocialDistributionLine', {'id': ln_id, 'distribution': did, 'client': str(self.own.id),
                                                'merite': arabic}, SocialDistributionLine, ln_id),
            ('sync.DebtMovement', {'id': mv_id, 'client': str(self.own.id), 'amount': arabic, 'kind': 'ORDER'},
             DebtMovement, mv_id),
        )
        for label, rec, model, pk in recs:
            r = push(self.n1, label, rec)
            self.assertEqual(r['status'], 'REJECTED', (label, r))
            self.assertFalse(model.objects.filter(pk=pk).exists(), label)
        self.own.refresh_from_db()
        self.assertEqual(self.own.current_debt, D('0.00'))

    def test_push_chiffres_ascii_legitimes_toujours_acceptes(self):
        r = push(self.n1, 'sync.DebtMovement', {'id': str(uuid.uuid4()), 'client': str(self.own.id),
                                                'amount': 2500.5, 'kind': 'ORDER'})
        self.assertEqual(r['status'], 'ACCEPTED', r)
        self.assertEqual(Client.objects.get(pk=self.own.pk).current_debt, D('2500.50'))

    # --- cotisation d'une annee dont la distribution est close ---
    def test_push_cotisation_existante_is_paid_paid_at_invalide_pas_de_500(self):
        sc = SocialContribution.objects.create(client=self.own, node=self.k1, month=3, year=2026, amount=D('2000'))
        r = push(self.n1, 'clients.SocialContribution', {'id': str(sc.pk), 'is_paid': True, 'paid_at': 'pas-une-date'})
        self.assertEqual(r['status'], 'REJECTED', r)
        sc.refresh_from_db()
        self.assertFalse(sc.is_paid)
