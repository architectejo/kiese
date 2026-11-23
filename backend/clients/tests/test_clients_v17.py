"""
Clients - ronde b21 (testeur clients/commissions, 2026-11-23). Verification independante de BUG-1103 (taux de
commission par boulangerie, Node.default_commission_rate) : creation REST/modele/import/push, jamais d'ecrasement,
changement de taux apres creation, taux 0, diffusion aux postes locaux (pull). Donnees FICTIVES.
"""
import io
import uuid
from decimal import Decimal as D
from unittest import expectedFailure

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from commissions.models import ClientCommission
from core.models import Config, Node
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine
from sync.models import NodeAuthToken

NODES = '/api/core/nodes/'
CL = '/api/clients/clients/'
GEN = '/api/commissions/periods/generate/'
PUSH = '/api/sync/push/'


def api(user):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(user)
    return c


def node_api(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    c = APIClient(raise_request_exception=False)
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return c


class Base17(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', social=D('2000'), card_fee=D('1000'))
        self.k2 = make_node(code='K2', social=D('2000'), card_fee=D('1000'))
        self.k3 = make_node(code='K3', social=D('2000'), card_fee=D('1000'))
        self.direction = make_user('DIRECTION', node=None, team='')
        self.g1 = make_user('GERANT', node=self.k1, team='')
        self.f1 = make_user('FACTURIER', node=self.k1, team='A')
        self.l1 = make_user('LIVREUR', node=self.k1, team='A')
        cfg = Config.get_instance()
        cfg.default_commission_rate = D('0.25')
        cfg.save()

    def rate(self, node, rate):
        Node.objects.filter(pk=node.pk).update(default_commission_rate=rate)
        node.refresh_from_db()

    def create(self, user, **body):
        r = api(user).post(CL, body, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))
        return Client.objects.get(pk=r.data['id'])


class CreationDefauts(Base17):
    def test_facturier_sans_champ_node_ni_taux_prend_le_taux_de_sa_boulangerie(self):
        """BUG-1027 : ClientViewSet.perform_create force commission_rate = 0,25 (defaut du champ) pour tout role
        hors ADMIN/DIRECTION/COMPTABLE/GERANT : le defaut par boulangerie n'est jamais applique aux clients
        crees par un facturier ou un livreur."""
        self.rate(self.k1, D('0.30'))
        c = self.create(self.f1, first_name='Fictif', last_name='Un')
        self.assertEqual((c.node, c.commission_rate), (self.k1, D('0.30')))

    def test_livreur_cree_un_client_avec_le_taux_de_sa_boulangerie(self):
        """BUG-1027 (meme cause, livreur)."""
        self.rate(self.k1, D('0.20'))
        c = self.create(self.l1, first_name='Fictif', last_name='Livreur')
        self.assertEqual(c.commission_rate, D('0.20'))

    def test_gerant_sans_champ_node_prend_le_taux_de_sa_boulangerie(self):
        self.rate(self.k1, D('0.30'))
        c = self.create(self.g1, first_name='Fictif', last_name='Gerant')
        self.assertEqual((c.node, c.commission_rate), (self.k1, D('0.30')))

    def test_taux_explicite_025_sur_boulangerie_030_est_conserve_par_le_modele_et_l_api(self):
        self.rate(self.k1, D('0.30'))
        self.assertEqual(self.create(self.g1, first_name='A', last_name='B', commission_rate='0.25').commission_rate,
                         D('0.25'))
        self.assertEqual(self.create(self.g1, first_name='A', last_name='C', commission_rate=0.25).commission_rate,
                         D('0.25'))
        direct = Client.objects.create(node=self.k1, node_origin='K1', first_name='D', last_name='E',
                                       commission_rate=D('0.25'))
        direct.refresh_from_db()
        self.assertEqual(direct.commission_rate, D('0.25'))

    def test_boulangerie_a_taux_zero_cree_des_clients_a_zero_et_aucune_commission(self):
        self.rate(self.k1, D('0.00'))
        c = self.create(self.g1, first_name='Zero', last_name='Taux')
        self.assertEqual(c.commission_rate, D('0.00'))
        make_bread_price('GRAND', 'Pain 500 FC', 500)
        i = Invoice.objects.create(node=self.k1, client=c, payment_type='CREDIT', status='DELIVERED',
                                   payment_amount=D('0'), invoice_date='2026-02-10', node_origin='K1',
                                   commission_rate=c.commission_rate)
        InvoiceLine.objects.create(invoice=i, bread_price=make_bread_price('GRAND', 'Pain 500 FC', 500), quantity=10)
        i.compute_order_total()
        i.save(update_fields=['order_total'])
        r = api(self.direction).post(GEN, {'node': self.k1.pk, 'month': 2, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))
        self.assertEqual(ClientCommission.objects.filter(client=c).count(), 0)

    def test_changement_du_taux_de_la_boulangerie_ne_touche_ni_clients_ni_commissions_generees(self):
        self.rate(self.k1, D('0.25'))
        c = self.create(self.g1, first_name='Stable', last_name='Taux')
        p = make_bread_price('GRAND', 'Pain 500 FC', 500)
        i = Invoice.objects.create(node=self.k1, client=c, payment_type='CREDIT', status='DELIVERED',
                                   payment_amount=D('0'), invoice_date='2026-02-10', node_origin='K1',
                                   commission_rate=c.commission_rate)
        InvoiceLine.objects.create(invoice=i, bread_price=p, quantity=100)
        i.compute_order_total()
        i.save(update_fields=['order_total'])
        gen = lambda: api(self.direction).post(GEN, {'node': self.k1.pk, 'month': 2, 'year': 2026}, format='json')
        self.assertEqual(gen().status_code, 201)
        r = api(self.direction).patch(f'{NODES}{self.k1.pk}/', {'default_commission_rate': '0.30'}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.k1.refresh_from_db()  # g1.node est le meme objet Python que k1 (cache de test)
        self.assertEqual(gen().status_code, 201)
        c.refresh_from_db()
        row = ClientCommission.objects.get(client=c)
        self.assertEqual(c.commission_rate, D('0.25'))
        self.assertEqual((row.commission_rate, row.commission_gross), (D('0.25'), D('12500.00')))
        # et un NOUVEAU client prend 0,30
        self.assertEqual(self.create(self.g1, first_name='Neuf', last_name='Client').commission_rate, D('0.30'))

    def test_transfert_de_boulangerie_d_un_client_ne_change_pas_son_taux(self):
        self.rate(self.k1, D('0.30'))
        self.rate(self.k2, D('0.20'))
        c = self.create(self.g1, first_name='Mobile', last_name='Client')
        r = api(self.direction).patch(f'{CL}{c.pk}/', {'node': self.k2.pk}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        c.refresh_from_db()
        self.assertEqual((c.node, c.commission_rate), (self.k2, D('0.30')))

    def test_client_relu_puis_sauvegarde_apres_changement_du_taux_de_la_boulangerie_reste_inchange(self):
        c = make_client(self.k1)
        self.rate(self.k1, D('0.30'))
        c = Client.objects.get(pk=c.pk)
        c.notes = 'x'
        c.save()
        c.refresh_from_db()
        self.assertEqual(c.commission_rate, D('0.25'))

    def test_boulangerie_sans_taux_repli_sur_config_modifiee(self):
        cfg = Config.get_instance()
        cfg.default_commission_rate = D('0.27')
        cfg.save()
        self.assertEqual(self.create(self.g1, first_name='C', last_name='D').commission_rate, D('0.27'))

    def test_trois_boulangeries_trois_taux_un_client_chacune(self):
        for n, r in ((self.k1, '0.30'), (self.k2, '0.20'), (self.k3, '0.10')):
            self.rate(n, D(r))
        got = [self.create(self.direction, first_name='M', last_name=f'N{n.code}', node=n.pk).commission_rate
               for n in (self.k1, self.k2, self.k3)]
        self.assertEqual(got, [D('0.30'), D('0.20'), D('0.10')])


class SaisieDuTauxDeLaBoulangerie(Base17):
    def patch(self, user, node, value):
        return api(user).patch(f'{NODES}{node.pk}/', {'default_commission_rate': value}, format='json')

    def test_droits(self):
        for u in (self.g1, self.f1, self.l1):
            self.assertEqual(self.patch(u, self.k1, '0.30').status_code, 403)
        self.k1.refresh_from_db()
        self.assertIsNone(self.k1.default_commission_rate)
        self.assertEqual(self.patch(self.direction, self.k1, '0.30').status_code, 200)

    def test_formes_de_saisie_refusees_et_acceptees(self):
        for bad in ('25', '0.31', '-0.01', '0.255', 'abc', '١', 'NaN', 'Infinity', [0.2], {'a': 1}, True):
            r = self.patch(self.direction, self.k1, bad)
            self.assertEqual(r.status_code, 400, (bad, getattr(r, 'data', None)))
            self.k1.refresh_from_db()
            self.assertIsNone(self.k1.default_commission_rate, bad)
        for good, expected in (('0.30', D('0.30')), ('0', D('0.00')), (0.2, D('0.20')), (None, None), ('', None)):
            r = self.patch(self.direction, self.k1, good)
            self.assertEqual(r.status_code, 200, (good, getattr(r, 'data', None)))
            self.k1.refresh_from_db()
            self.assertEqual(self.k1.default_commission_rate, expected, good)

    def test_lecture_par_le_gerant_et_nulle_pour_une_boulangerie_vide(self):
        r = api(self.g1).get(f'{NODES}{self.k1.pk}/')
        if r.status_code == 200:
            self.assertIn('default_commission_rate', r.data)
            self.assertIsNone(r.data['default_commission_rate'])


class ImportExcel(Base17):
    def xlsx(self, sheet, names):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        ws = wb.create_sheet(sheet)
        ws.append(['LISTE FICTIVE'])
        ws.append(['DATE', 'CODE', 'NOM'])
        for n in names:
            ws.append([None, 'X', n])
        buf = io.BytesIO()
        wb.save(buf)
        return SimpleUploadedFile('c.xlsx', buf.getvalue(),
                                  content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_import_deux_boulangeries_deux_taux_et_reimport_sans_modification(self):
        self.rate(self.k1, D('0.30'))
        self.rate(self.k2, D('0.20'))
        for sheet, names in (('CL-K1 TABO', ['Alpha Un', 'Beta Deux']), ('CL-K2 COQ', ['Gamma Trois'])):
            r = api(self.direction).post(CL + 'import_excel/', {'file': self.xlsx(sheet, names)}, format='multipart')
            self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertEqual(set(Client.objects.filter(node=self.k1).values_list('commission_rate', flat=True)),
                         {D('0.30')})
        self.assertEqual(set(Client.objects.filter(node=self.k2).values_list('commission_rate', flat=True)),
                         {D('0.20')})
        # le taux change, reimport du meme fichier : doublons ignores, anciens clients inchanges
        self.rate(self.k1, D('0.10'))
        r = api(self.direction).post(CL + 'import_excel/', {'file': self.xlsx('CL-K1 TABO', ['Alpha Un', 'Delta Quatre'])},
                                     format='multipart')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        rates = dict(Client.objects.filter(node=self.k1).values_list('first_name', 'commission_rate'))
        self.assertEqual(sorted(rates.values()), [D('0.10'), D('0.30'), D('0.30')], rates)


class PushSync(Base17):
    def push(self, node, record_id=None, **extra):
        rid = record_id or str(uuid.uuid4())
        rec = {'id': rid, 'first_name': 'Poste', 'last_name': 'Distant', 'node': node.code,
               'code': f'{node.code}-{uuid.uuid4().hex[:6].upper()}', 'node_origin': node.code}
        rec.update(extra)
        r = node_api(node).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {'clients.Client': [rec]}},
                                format='json')
        return rid, r

    def pushed(self, rid):
        return Client.objects.get(pk=rid)

    def test_push_sans_taux_null_ou_vide_prend_le_taux_de_la_boulangerie(self):
        self.rate(self.k2, D('0.30'))
        for extra in ({}, {'commission_rate': None}, {'commission_rate': ''}):
            rid, r = self.push(self.k2, **extra)
            self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
            self.assertEqual(self.pushed(rid).commission_rate, D('0.30'), extra)

    def test_push_avec_taux_conserve_meme_025_et_zero(self):
        self.rate(self.k2, D('0.30'))
        for val, exp in (('0.25', D('0.25')), ('0.00', D('0.00')), (0.2, D('0.20'))):
            rid, r = self.push(self.k2, commission_rate=val)
            self.assertEqual(self.pushed(rid).commission_rate, exp, val)

    def test_repush_sans_taux_d_un_client_existant_ne_le_modifie_pas(self):
        self.rate(self.k2, D('0.30'))
        rid, _ = self.push(self.k2, commission_rate='0.25')
        self.rate(self.k2, D('0.10'))
        rec = {'id': rid, 'first_name': 'Poste', 'last_name': 'Modifie',
               'node': 'K2', 'node_origin': 'K2'}
        r = node_api(self.k2).post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {'clients.Client': [rec]}},
                                     format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        c = self.pushed(rid)
        self.assertEqual((c.last_name, c.commission_rate), ('Modifie', D('0.25')))

    def test_push_sans_taux_boulangerie_vide_repli_sur_config(self):
        cfg = Config.get_instance()
        cfg.default_commission_rate = D('0.28')
        cfg.save()
        rid, _ = self.push(self.k3)
        self.assertEqual(self.pushed(rid).commission_rate, D('0.28'))

    def test_le_taux_par_boulangerie_arrive_aux_postes_locaux_par_le_pull(self):
        """BUG-1030 : `/api/sync/pull/` ne diffuse que la config globale (default_commission_rate global) ;
        aucun parametre de boulangerie (taux, carte, cotisation, valeur du sac) n'atteint les postes locaux."""
        self.rate(self.k1, D('0.30'))
        r = node_api(self.k1).get('/api/sync/pull/')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        blob = str(r.data)
        self.assertIn("'0.30'", blob.replace('"', "'").replace("Decimal('0.30')", "'0.30'"))
