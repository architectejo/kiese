"""
B-1 (Q-026, ferme) : "Taux de Commission" propre a chaque boulangerie (Node.default_commission_rate).
Defaut a la creation d'un client (REST, import Excel, push sync), repli sur Config, client existant jamais
ecrase, commissions deja generees figees, isolation entre boulangeries, migration de donnees.
Donnees FICTIVES.
"""
import io
import os
import tempfile
import unittest
import uuid
from decimal import Decimal as D

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from commissions.models import ClientCommission
from core.models import Config, Node, effective_commission_rate
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


class Base(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', social=D('2000'), card_fee=D('1000'))
        self.k2 = make_node(code='K2', social=D('2000'), card_fee=D('1000'))
        self.direction = make_user('DIRECTION', node=None, team='')
        self.admin = make_user('ADMIN', node=None, team='')
        self.g1 = make_user('GERANT', node=self.k1, team='')
        self.f1 = make_user('FACTURIER', node=self.k1, team='A')
        cfg = Config.get_instance()
        cfg.default_commission_rate = D('0.25')
        cfg.save()

    def set_rate(self, node, rate):
        Node.objects.filter(pk=node.pk).update(default_commission_rate=rate)
        node.refresh_from_db()

    def create_client(self, user, node, **extra):
        body = {'first_name': 'Fictif', 'last_name': 'Client', 'node': node.pk}
        body.update(extra)
        r = api(user).post(CL, body, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))
        return Client.objects.get(pk=r.data['id'])


class DefautALaCreation(Base):
    def test_helper_taux_boulangerie_puis_repli_config(self):
        self.assertIsNone(self.k1.default_commission_rate)
        self.assertEqual(effective_commission_rate(self.k1), D('0.25'))
        self.assertEqual(effective_commission_rate(None), D('0.25'))
        self.set_rate(self.k1, D('0.30'))
        self.assertEqual(effective_commission_rate(self.k1), D('0.30'))
        self.set_rate(self.k1, D('0.00'))  # 0 est un taux valide, pas "vide"
        self.assertEqual(effective_commission_rate(self.k1), D('0.00'))

    def test_creation_rest_sans_taux_prend_celui_de_la_boulangerie(self):
        self.set_rate(self.k1, D('0.30'))
        self.assertEqual(self.create_client(self.g1, self.k1).commission_rate, D('0.30'))

    def test_creation_rest_boulangerie_vide_replie_sur_config(self):
        cfg = Config.get_instance()
        cfg.default_commission_rate = D('0.28')
        cfg.save()
        self.assertEqual(self.create_client(self.direction, self.k1).commission_rate, D('0.28'))

    def test_taux_explicite_a_la_creation_prevaut(self):
        self.set_rate(self.k1, D('0.30'))
        self.assertEqual(self.create_client(self.g1, self.k1, commission_rate='0.25').commission_rate, D('0.25'))

    def test_deux_boulangeries_deux_taux(self):
        self.set_rate(self.k1, D('0.30'))
        self.set_rate(self.k2, D('0.20'))
        self.assertEqual(self.create_client(self.direction, self.k1).commission_rate, D('0.30'))
        self.assertEqual(self.create_client(self.direction, self.k2).commission_rate, D('0.20'))

    def test_creation_directe_modele_et_relecture_inchangee(self):
        self.set_rate(self.k1, D('0.30'))
        c = Client.objects.create(node=self.k1, first_name='A', last_name='B', node_origin='K1')
        self.assertEqual(Client.objects.get(pk=c.pk).commission_rate, D('0.30'))
        # une relecture puis save() ne touche pas au taux
        self.set_rate(self.k1, D('0.20'))
        c2 = Client.objects.get(pk=c.pk)
        c2.phone = '0810000000'
        c2.save()
        self.assertEqual(Client.objects.get(pk=c.pk).commission_rate, D('0.30'))


class ClientExistantInchange(Base):
    def test_patch_du_noeud_ne_change_pas_les_clients_existants(self):
        a = make_client(self.k1, commission_rate=D('0.25'))
        b = make_client(self.k1, commission_rate=D('0.30'))
        r = api(self.direction).patch(f'{NODES}{self.k1.pk}/', {'default_commission_rate': '0.20'}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertEqual(r.data['default_commission_rate'], '0.20')
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.commission_rate, b.commission_rate), (D('0.25'), D('0.30')))

    def test_patch_client_apres_changement_du_noeud_garde_son_taux(self):
        c = self.create_client(self.g1, self.k1)
        self.set_rate(self.k1, D('0.10'))
        r = api(self.g1).patch(f'{CL}{c.pk}/', {'phone': '0811111111'}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        c.refresh_from_db()
        self.assertEqual(c.commission_rate, D('0.25'))


class CommissionDejaGeneree(Base):
    def test_commission_generee_garde_son_taux_fige(self):
        p500 = make_bread_price('GRAND', 'Pain 500 FC', 500)
        c = make_client(self.k1, commission_rate=D('0.30'))
        i = Invoice.objects.create(node=self.k1, client=c, payment_type='CREDIT', status='DELIVERED',
                                   payment_amount=D('0'), invoice_date='2026-02-10', node_origin='K1')
        InvoiceLine.objects.create(invoice=i, bread_price=p500, quantity=10)
        i.compute_order_total()
        i.save(update_fields=['order_total'])
        r = api(self.direction).post(GEN, {'node': self.k1.pk, 'month': 2, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))
        row = ClientCommission.objects.get(client=c)
        self.assertEqual(row.commission_rate, D('0.30'))
        api(self.direction).patch(f'{NODES}{self.k1.pk}/', {'default_commission_rate': '0.10'}, format='json')
        row.refresh_from_db()
        self.assertEqual(row.commission_rate, D('0.30'))


class IsolationEtPermissions(Base):
    def test_gerant_ne_modifie_aucun_taux_de_boulangerie(self):
        self.set_rate(self.k2, D('0.20'))
        for node in (self.k1, self.k2):
            r = api(self.g1).patch(f'{NODES}{node.pk}/', {'default_commission_rate': '0.10'}, format='json')
            self.assertIn(r.status_code, (403, 404))
        self.k1.refresh_from_db()
        self.k2.refresh_from_db()
        self.assertIsNone(self.k1.default_commission_rate)
        self.assertEqual(self.k2.default_commission_rate, D('0.20'))

    def test_facturier_ne_modifie_pas_le_taux(self):
        r = api(self.f1).patch(f'{NODES}{self.k1.pk}/', {'default_commission_rate': '0.10'}, format='json')
        self.assertIn(r.status_code, (403, 404))

    def test_direction_et_admin_modifient_le_taux_sans_toucher_l_autre_boulangerie(self):
        self.set_rate(self.k2, D('0.20'))
        for u in (self.direction, self.admin):
            r = api(u).patch(f'{NODES}{self.k1.pk}/', {'default_commission_rate': '0.27'}, format='json')
            self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.k1.refresh_from_db()
        self.k2.refresh_from_db()
        self.assertEqual((self.k1.default_commission_rate, self.k2.default_commission_rate), (D('0.27'), D('0.20')))

    def test_bornes_et_valeurs_invalides_refusees_et_vide_accepte(self):
        for bad in ('0.31', '-0.01', 'abc', '٠.25', '0.255'):
            r = api(self.direction).patch(f'{NODES}{self.k1.pk}/', {'default_commission_rate': bad}, format='json')
            self.assertEqual(r.status_code, 400, bad)
        self.set_rate(self.k1, D('0.30'))
        r = api(self.direction).patch(f'{NODES}{self.k1.pk}/', {'default_commission_rate': None}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.k1.refresh_from_db()
        self.assertIsNone(self.k1.default_commission_rate)
        for ok in ('0', '0.30', '0.25'):
            r = api(self.direction).patch(f'{NODES}{self.k1.pk}/', {'default_commission_rate': ok}, format='json')
            self.assertEqual(r.status_code, 200, ok)


class ImportExcel(Base):
    def test_import_excel_applique_le_taux_de_la_boulangerie(self):
        self.set_rate(self.k1, D('0.30'))
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        ws = wb.create_sheet('CL-K1 TABO')
        ws.append(['LISTE FICTIVE'])
        ws.append(['DATE', 'CODE', 'NOM'])
        ws.append([None, 'X', 'Alpha Importe'])
        buf = io.BytesIO()
        wb.save(buf)
        f = SimpleUploadedFile('c.xlsx', buf.getvalue(),
                               content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        r = api(self.direction).post(CL + 'import_excel/', {'file': f}, format='multipart')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        imported = Client.objects.filter(node=self.k1)
        self.assertEqual(imported.count(), 1)
        self.assertEqual(imported.get().commission_rate, D('0.30'))


class PushSync(Base):
    def push_client(self, node, **extra):
        _, raw = NodeAuthToken.issue_for_node(node)
        c = APIClient(raise_request_exception=False)
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
        rec = {'id': str(uuid.uuid4()), 'node': node.code, 'node_origin': node.code,
               'code': f'{node.code}-9001', 'first_name': 'Sync', 'last_name': 'Fictif'}
        rec.update(extra)
        r = c.post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {'clients.Client': [rec]}}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        return rec, r.data['results']['clients.Client'][0]

    def test_push_nouveau_client_sans_taux_prend_celui_de_la_boulangerie(self):
        self.set_rate(self.k1, D('0.30'))
        rec, res = self.push_client(self.k1)
        self.assertEqual(res['status'], 'ACCEPTED', res)
        self.assertEqual(Client.objects.get(pk=rec['id']).commission_rate, D('0.30'))

    def test_push_avec_taux_explicite_le_garde(self):
        self.set_rate(self.k1, D('0.30'))
        rec, res = self.push_client(self.k1, commission_rate='0.25')
        self.assertEqual(res['status'], 'ACCEPTED', res)
        self.assertEqual(Client.objects.get(pk=rec['id']).commission_rate, D('0.25'))


class MigrationDonnees(unittest.TestCase):
    """Base SQLite jetable : boulangeries a core 0024, puis application de 0025."""
    ALIAS = 'core_0025'
    L24 = ('core', '0024_node_block_sales_after_closure')
    L25 = ('core', '0025_node_default_commission_rate')

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.sqlite3')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.remove(self.db_path))
        connections.databases[self.ALIAS] = {
            'ENGINE': 'django.db.backends.sqlite3', 'NAME': self.db_path, 'ATOMIC_REQUESTS': False,
            'TIME_ZONE': None, 'CONN_HEALTH_CHECKS': False, 'CONN_MAX_AGE': 0, 'AUTOCOMMIT': True, 'OPTIONS': {},
        }
        self.addCleanup(connections[self.ALIAS].close)
        self.addCleanup(lambda: connections.databases.pop(self.ALIAS, None))
        alias = self.ALIAS

        class _Router:
            def db_for_read(self, model, **hints):
                return alias

            db_for_write = db_for_read

            def allow_migrate(self, db, app_label, **hints):
                return db == alias

        from django.db import router as _db_router
        self._old_routers = list(_db_router.routers)
        _db_router.routers = [_Router()]
        self.addCleanup(lambda: setattr(_db_router, 'routers', self._old_routers))
        self.executor = MigrationExecutor(connections[self.ALIAS])

    def _state(self, targets):
        self.executor.loader.build_graph()
        return self.executor.loader.project_state(targets).apps

    def _migrate(self, targets):
        self.executor.loader.build_graph()
        self.executor.migrate(targets)
        return self._state(targets)

    def test_taux_de_config_copie_dans_les_boulangeries_siege_reste_vide(self):
        old = self._migrate([self.L24])
        Node, Config_ = old.get_model('core', 'Node'), old.get_model('core', 'Config')
        Config_.objects.using(self.ALIAS).create(default_commission_rate=D('0.28'))
        for code in ('ZA', 'ZB', 'SIEGE'):
            Node.objects.using(self.ALIAS).get_or_create(code=code, defaults={'name': f'Fictif {code}'})
        new = self._migrate([self.L25])
        rates = {n.code: n.default_commission_rate for n in new.get_model('core', 'Node').objects.using(self.ALIAS)}
        self.assertEqual((rates['ZA'], rates['ZB'], rates['SIEGE']), (D('0.28'), D('0.28'), None))
        self.assertTrue(all(r == D('0.28') for c, r in rates.items() if c != 'SIEGE'), rates)

    def test_sans_config_les_boulangeries_restent_vides(self):
        old = self._migrate([self.L24])
        old.get_model('core', 'Node').objects.using(self.ALIAS).create(code='ZA', name='Fictif')
        new = self._migrate([self.L25])
        node = new.get_model('core', 'Node').objects.using(self.ALIAS).get(code='ZA')
        self.assertIsNone(node.default_commission_rate)

    def test_clients_existants_non_modifies_et_migration_reversible(self):
        self._migrate([('clients', '0010_bug289')])
        self._migrate([self.L24, ('clients', '0010_bug289')])
        old = self._state([self.L24, ('clients', '0010_bug289')])
        Node, Config_, OldClient = (old.get_model('core', 'Node'), old.get_model('core', 'Config'),
                                    old.get_model('clients', 'Client'))
        Config_.objects.using(self.ALIAS).create(default_commission_rate=D('0.25'))
        node = Node.objects.using(self.ALIAS).create(code='ZA', name='Fictif')
        OldClient.objects.using(self.ALIAS).create(code='ZA-0001', first_name='A', last_name='B', node=node,
                                                    node_origin='ZA', commission_rate=D('0.30'))
        self._migrate([self.L25, ('clients', '0010_bug289')])
        state = self._migrate([self.L24, ('clients', '0010_bug289')])  # retour arriere sans erreur
        client = state.get_model('clients', 'Client').objects.using(self.ALIAS).get()
        self.assertEqual(client.commission_rate, D('0.30'))
