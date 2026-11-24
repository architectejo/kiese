"""
B-2 (remarque.md l.508, BUG-1116) : un client qui vient d'etre enregistre ne doit pas etre
« SUSPENDU » (is_active=False) ni « a risque » sans dette. Donnees FICTIVES.

Cause : en multipart (formulaire avec photo), un champ booleen ABSENT est lu « faux » par DRF,
donc le client etait cree is_active=False ; et refresh_category classait RISK dette 0 >= plafond 0.
"""
import io
from decimal import Decimal as D

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from clients.models import Client
from clients.tests.test_clients_v2 import Base, api, results
from core.models import Node

CL = '/api/clients/clients/'
def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (2, 2), 'white').save(buf, 'PNG')
    return buf.getvalue()


PNG = _png()


class NouveauClient(Base):
    def roles(self):
        return {'gerant': self.g1, 'facturier': self.f1, 'livreur': self.l1, 'direction': self.direction}

    def assert_normal(self, cid, who):
        for resp in (api(self.direction).get(f'{CL}{cid}/'), api(self.direction).get(CL, {'search': who})):
            self.assertEqual(resp.status_code, 200)
            rows = results(resp) if isinstance(results(resp), list) else [resp.data]
            row = next(r for r in rows if str(r['id']) == str(cid))
            self.assertTrue(row['is_active'], who)
            self.assertEqual(row['category'], Client.Category.NORMAL, who)
        c = Client.objects.get(pk=cid)
        self.assertTrue(c.is_active)
        self.assertEqual(c.category, Client.Category.NORMAL)

    def post(self, user, multipart, limit, name):
        body = {'first_name': 'Neuf', 'last_name': name, 'phone': '0990001234', 'node': str(self.k1.pk)}
        if limit is not None:
            body['credit_limit'] = str(limit)
        if multipart:
            body['photo'] = SimpleUploadedFile('p.png', PNG, content_type='image/png')
            return api(user).post(CL, body, format='multipart')
        return api(user).post(CL, body, format='json')

    def test_creation_par_chaque_role_json_et_multipart_plafonds(self):
        n = 0
        for who, user in self.roles().items():
            for multipart in (False, True):
                for limit in (None, '50000', '0'):
                    n += 1
                    name = f'{who}{n}'
                    r = self.post(user, multipart, limit, name)
                    self.assertEqual(r.status_code, 201, (who, multipart, limit, r.data))
                    self.assert_normal(r.data['id'], name)

    def test_creation_multipart_sans_photo(self):
        r = api(self.g1).post(CL, {'first_name': 'A', 'last_name': 'Multi', 'node': str(self.k1.pk)},
                              format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assert_normal(r.data['id'], 'Multi')

    def test_desactivation_explicite_toujours_possible(self):
        r = api(self.g1).post(CL, {'first_name': 'A', 'last_name': 'Inactif', 'is_active': 'false',
                                   'node': str(self.k1.pk)}, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(Client.objects.get(pk=r.data['id']).is_active)
        r = api(self.g1).post(CL, {'first_name': 'A', 'last_name': 'Inactif2', 'is_active': False,
                                   'node': str(self.k1.pk)}, format='json')
        self.assertFalse(Client.objects.get(pk=r.data['id']).is_active)

    def test_plafond_zero_dette_zero_pas_a_risque_mais_dette_positive_oui(self):
        c = self.mk(self.k1, 'Zero', 'Plafond', credit_limit=D('0'))
        c.refresh_category()
        self.assertEqual(c.category, Client.Category.NORMAL)
        c.current_debt = D('1')
        c.refresh_category()
        self.assertEqual(c.category, Client.Category.RISK)

    def test_dette_egale_plafond_reste_a_risque(self):
        c = self.mk(self.k1, 'Egal', 'Plafond', credit_limit=D('50000'))
        c.current_debt = D('50000')
        c.refresh_category()
        self.assertEqual(c.category, Client.Category.RISK)

    def test_recalcul_et_modification_plafond_a_zero_ne_suspend_pas(self):
        c = self.mk(self.k1, 'Mod', 'Plafond')
        r = api(self.g1).patch(f'{CL}{c.pk}/', {'credit_limit': '0'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        c.refresh_from_db()
        self.assertTrue(c.is_active)
        self.assertEqual(c.category, Client.Category.NORMAL)
