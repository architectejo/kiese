"""
Vague 2 « base réelle » (testeur-clients-commissions, 2026-11-12) : scénarios rejoués sur
la vraie base (K4, comptes zz_clients_*, clients « ZZTEST Clients n ») et reproduits ici sur
une base de test avec des données fictives. Les défauts constatés sont marqués
@expectedFailure avec la référence du ticket du registre.
"""
import io
import tempfile
from decimal import Decimal
from unittest import expectedFailure

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from clients.models import Client, SocialContribution, SocialDistribution
from core.models import Config
from core.testing import make_client, make_node, make_user

CLIENTS = '/api/clients/clients/'
def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (2, 2), (200, 100, 50)).save(buf, 'PNG')
    return buf.getvalue()


PNG = _png()


def _api(user):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(user)
    return c


class Base(TestCase):
    def setUp(self):
        self.k4 = make_node(code='V4')
        self.k3 = make_node(code='V3')
        self.gerant = make_user('GERANT', node=self.k4, team='')
        self.facturier = make_user('FACTURIER', node=self.k4, team='A')
        self.comptable = make_user('COMPTABLE', node=None, team='')


class CreationEtRechercheTests(Base):
    def test_code_unique_auto_et_plafond_par_defaut_50000(self):
        r = _api(self.gerant).post(CLIENTS, {'first_name': 'ZZTEST', 'last_name': 'Un', 'code': 'V4-9999', 'node': self.k3.pk})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertNotEqual(r.data['code'], 'V4-9999')
        self.assertTrue(r.data['code'].startswith('V4-'))
        c = Client.objects.get(pk=r.data['id'])
        self.assertEqual(c.node, self.k4)
        self.assertEqual(c.credit_limit, Decimal('50000.00'))
        r2 = _api(self.facturier).post(CLIENTS, {'first_name': 'ZZTEST', 'last_name': 'Deux'})
        self.assertEqual(r2.status_code, 201)
        self.assertNotEqual(r2.data['code'], r.data['code'])

    def test_facturier_k4_trouve_un_client_k3_par_code_et_nom_partiel_gerant_non(self):
        autre = make_client(self.k3, last_name='Mukendi')
        api = _api(self.facturier)
        for q in (autre.code, 'Mukend', 'mukendi'):
            codes = [x['code'] for x in api.get(CLIENTS, {'search': q}).data['results']]
            self.assertIn(autre.code, codes, q)
        codes = [x['code'] for x in _api(self.gerant).get(CLIENTS, {'search': autre.code}).data['results']]
        self.assertNotIn(autre.code, codes)

    def test_plafond_modifiable_par_gerant_et_comptable_refuse_au_facturier(self):
        c = make_client(self.k4)
        self.assertEqual(_api(self.facturier).patch(f'{CLIENTS}{c.pk}/', {'credit_limit': '80000'}).status_code, 403)
        self.assertEqual(_api(self.gerant).patch(f'{CLIENTS}{c.pk}/', {'credit_limit': '80000'}).status_code, 200)
        self.assertEqual(_api(self.comptable).patch(f'{CLIENTS}{c.pk}/', {'credit_limit': '60000'}).status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.credit_limit, Decimal('60000.00'))

    def test_categories_aux_bornes_meilleur_client_et_risque(self):
        th = Config.get_instance().best_client_threshold
        c = make_client(self.k4)
        api = _api(self.gerant)
        # BUG-259 : total_breads_received n'est plus modifiable par l'API -> mise en place directe en base.
        Client.objects.filter(pk=c.pk).update(total_breads_received=th - 1)
        self.assertEqual(api.patch(f'{CLIENTS}{c.pk}/', {'notes': 'x'}).data['category'], 'NORMAL')
        Client.objects.filter(pk=c.pk).update(total_breads_received=th)
        self.assertEqual(api.patch(f'{CLIENTS}{c.pk}/', {'notes': 'y'}).data['category'], 'BEST')
        Client.objects.filter(pk=c.pk).update(current_debt=Decimal('50000'))
        self.assertEqual(api.patch(f'{CLIENTS}{c.pk}/', {'credit_limit': '50001'}).data['category'], 'BEST')
        self.assertEqual(api.patch(f'{CLIENTS}{c.pk}/', {'credit_limit': '50000'}).data['category'], 'RISK')

    def test_validations_champs_obligatoires_et_type_invalide(self):
        api = _api(self.gerant)
        self.assertEqual(api.post(CLIENTS, {'first_name': 'ZZTEST'}).status_code, 400)
        self.assertEqual(api.post(CLIENTS, {'first_name': 'A', 'last_name': 'B', 'client_type': 'XXX'}).status_code, 400)
        self.assertEqual(api.post(CLIENTS, {'first_name': '  ', 'last_name': 'B'}).status_code, 400)

    def test_bug257_plafond_taux_et_cotisation_invalides_refuses(self):
        api = _api(self.gerant)
        base = {'first_name': 'ZZTEST', 'last_name': 'Valid'}
        for extra in ({'credit_limit': '-100'}, {'commission_rate': '0.99'}, {'commission_rate': '-0.10'},
                      {'cotisation_sociale': '-3000'}):
            r = api.post(CLIENTS, {**base, **extra})
            self.assertEqual(r.status_code, 400, extra)

    def test_bug259_bp_et_total_pains_non_modifiables_a_la_main(self):
        c = make_client(self.k4)
        r = _api(self.gerant).patch(f'{CLIENTS}{c.pk}/', {'current_debt': '-999999', 'total_breads_received': 5000})
        c.refresh_from_db()
        self.assertEqual(c.current_debt, Decimal('0.00'))
        self.assertEqual(c.total_breads_received, 0)

    def test_bug258_photo_de_plus_de_5_mo_refusee(self):
        c = make_client(self.k4)
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            gros = SimpleUploadedFile('big.png', PNG + b'\0' * (12 * 1024 * 1024), content_type='image/png')
            r = _api(self.gerant).patch(f'{CLIENTS}{c.pk}/', {'photo': gros}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_photo_non_image_refusee_et_png_valide_acceptee(self):
        c = make_client(self.k4)
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            api = _api(self.gerant)
            r = api.patch(f'{CLIENTS}{c.pk}/', {'photo': SimpleUploadedFile('a.txt', b'pas une image', content_type='text/plain')}, format='multipart')
            self.assertEqual(r.status_code, 400)
            r = api.patch(f'{CLIENTS}{c.pk}/', {'photo': SimpleUploadedFile('a.png', PNG, content_type='image/png')}, format='multipart')
            self.assertEqual(r.status_code, 200, r.data)


class ImportExcelTests(Base):
    def _xlsx(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'CL-K7 TEST'
        ws.append(['DATE', 'CODE', 'NOM'])
        for n in ['ZZTEST Alpha', 'ZZTEST Bravo', 'zztest bravo', '  ZZTEST   Charlie  ']:
            ws.append([None, None, n])
        ws.append([None, None, None])
        ws.append([None, None, 'ZZTEST Apres Vide'])
        w2 = wb.create_sheet('CL-K9 INCONNU')
        w2.append(['DATE', 'CODE', 'NOM'])
        w2.append([None, None, 'ZZTEST Inconnu'])
        wb.create_sheet('Libre').append(['x'])
        buf = io.BytesIO()
        wb.save(buf)
        return SimpleUploadedFile('fictif.xlsx', buf.getvalue())

    def test_import_dry_run_import_doublons_et_droits(self):
        url = CLIENTS + 'import_excel/'
        k7 = make_node(code='K7')
        self.assertEqual(_api(self.gerant).post(url, {'file': self._xlsx()}, format='multipart').status_code, 403)
        api = _api(self.comptable)
        r = api.post(url, {'file': self._xlsx(), 'dry_run': 'true'}, format='multipart')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['created'], 0)
        self.assertEqual(r.data['report'][0]['to_import'], 3)
        self.assertEqual(r.data['report'][0]['already_existing'], 1)
        self.assertEqual(r.data['unknown_nodes'], ['K9'])
        self.assertEqual(r.data['skipped_sheets'], ['Libre'])
        self.assertEqual(Client.objects.filter(first_name='ZZTEST').count(), 0)
        r = api.post(url, {'file': self._xlsx()}, format='multipart')
        self.assertEqual(r.data['created'], 3)
        r = api.post(url, {'file': self._xlsx()}, format='multipart')
        self.assertEqual(r.data['created'], 0)
        self.assertEqual(Client.objects.filter(first_name='ZZTEST', node=k7).count(), 3)

    def test_import_fichier_invalide_ou_absent(self):
        api = _api(self.comptable)
        r = api.post(CLIENTS + 'import_excel/', {'file': SimpleUploadedFile('x.txt', b'pas excel')}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(api.post(CLIENTS + 'import_excel/', {}, format='multipart').status_code, 400)


class CaisseSocialeTests(Base):
    def setUp(self):
        super().setUp()
        self.cl = make_client(self.k4)   # cotisation_sociale par défaut : 3000.00 (comme les 678 clients réels)

    def test_cotisations_creation_doublon_et_toggle_paid(self):
        api = _api(self.gerant)
        r = api.post('/api/clients/contributions/', {'client': self.cl.pk, 'node': self.k3.pk, 'month': 1, 'year': 2098, 'amount': '3000'})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['node'], self.k4.pk)   # nœud imposé
        self.assertEqual(api.post('/api/clients/contributions/', {'client': self.cl.pk, 'month': 1, 'year': 2098, 'amount': '3000'}).status_code, 400)
        t = api.post(f"/api/clients/contributions/{r.data['id']}/toggle_paid/")
        self.assertTrue(t.data['is_paid'])
        self.assertIsNotNone(t.data['paid_at'])
        self.assertIsNone(api.post(f"/api/clients/contributions/{r.data['id']}/toggle_paid/").data['paid_at'])
        self.assertEqual(_api(self.facturier).get('/api/clients/contributions/').status_code, 403)

    # BUG-256 corrigé (dev-backend) : test de non-régression
    def test_bug256_bulk_create_month_et_auto_populate_trouvent_les_clients_a_cotisation_3000(self):
        api = _api(self.gerant)
        r = api.post('/api/clients/contributions/bulk_create_month/', {'node': self.k4.pk, 'month': 4, 'year': 2098})
        self.assertEqual(r.data['created'], 1)
        d = api.post('/api/clients/distributions/', {'node': self.k4.pk, 'year': 2098, 'tarif': '700'}).data
        r = api.post(f"/api/clients/distributions/{d['id']}/auto_populate_lines/")
        self.assertEqual(r.data['created'], 1)

    # BUG-254 corrigé (dev-backend) : test de non-régression
    def test_bug254_creation_manuelle_d_une_ligne_de_distribution(self):
        api = _api(self.gerant)
        d = api.post('/api/clients/distributions/', {'node': self.k4.pk, 'year': 2098, 'tarif': '700'}).data
        r = api.post('/api/clients/distribution-lines/', {'distribution': d['id'], 'client': self.cl.pk, 'indice': 3,
                                                          'total_social': '9000', 'merite': '500'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Decimal(str(r.data['remise'])), Decimal('2100'))
        self.assertEqual(Decimal(str(r.data['total_payer'])), Decimal('11600'))

    def test_ligne_de_distribution_recalculee_par_patch_quand_elle_existe(self):
        d = SocialDistribution.objects.create(node=self.k4, year=2098, tarif=Decimal('700'))
        from clients.models import SocialDistributionLine
        ln = SocialDistributionLine.objects.create(distribution=d, client=self.cl, indice=3, total_social=Decimal('9000'), merite=Decimal('500'))
        r = _api(self.gerant).patch(f'/api/clients/distribution-lines/{ln.pk}/', {'indice': 5})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Decimal(str(r.data['remise'])), Decimal('3500'))
        self.assertEqual(Decimal(str(r.data['total_payer'])), Decimal('13000'))

    def test_bug260_mois_montant_tarif_invalides_et_cloture_irreversible(self):
        api = _api(self.gerant)
        r = api.post('/api/clients/contributions/', {'client': self.cl.pk, 'month': 13, 'year': 2098, 'amount': '-3000'})
        self.assertEqual(r.status_code, 400)
        d = api.post('/api/clients/distributions/', {'node': self.k4.pk, 'year': 2097, 'tarif': '700'}).data
        self.assertEqual(api.patch(f"/api/clients/distributions/{d['id']}/", {'tarif': '-5'}).status_code, 400)
        api.patch(f"/api/clients/distributions/{d['id']}/", {'is_closed': True})
        r = api.patch(f"/api/clients/distributions/{d['id']}/", {'is_closed': False})
        self.assertTrue(SocialDistribution.objects.get(pk=d['id']).is_closed, 'une distribution clôturée ne doit pas se rouvrir par PATCH')
