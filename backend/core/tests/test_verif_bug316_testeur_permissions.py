"""Verification BUG-316 (testeur-permissions, 2026-11-20b).

Matrice role x verbe pour tarif / is_closed d'une SocialDistribution :
  - COMPTABLE et GERANT : 403 francais sur PATCH/PUT modifiant tarif ou is_closed ;
  - PUT inchange accepte ; creation : tarif/is_closed ignores ;
  - ADMIN et DIRECTION : OK ; FACTURIER/LIVREUR : refuses (ecriture impossible) ;
  - autres noeuds : gerant K1 ne touche pas K2 (404), gerant K2 ne touche pas K1.
Donnees fictives.
"""
from decimal import Decimal as Dc

from clients.models import SocialDistribution
from core.tests.test_permissions_regression_2026_11_19 import Base, cl


class Bug316Matrice(Base):
    def url(self, d=None):
        return f'/api/clients/distributions/{(d or self.dist1).pk}/'

    def put_body(self, d, **over):
        body = {'node': str(d.node_id), 'year': d.year, 'tarif': str(d.tarif),
                'is_closed': d.is_closed}
        body.update(over)
        return body

    def test_comptable_403_patch_and_put(self):
        c = cl(self.u['COMPTABLE'])
        for r in (c.patch(self.url(), {'tarif': '1'}, format='json'),
                  c.patch(self.url(), {'is_closed': True}, format='json'),
                  c.put(self.url(), self.put_body(self.dist1, tarif='1'), format='json'),
                  c.put(self.url(), self.put_body(self.dist1, is_closed=True), format='json')):
            self.assertEqual(r.status_code, 403, r.content)
            self.assertIn('direction', r.data['detail'])
        self.dist1.refresh_from_db()
        self.assertEqual((self.dist1.tarif, self.dist1.is_closed), (Dc('700'), False))

    def test_gerant_403_put_modified(self):
        g = cl(self.u['GERANT'])
        for over in ({'tarif': '5'}, {'is_closed': True}):
            r = g.put(self.url(), self.put_body(self.dist1, **over), format='json')
            self.assertEqual(r.status_code, 403, r.content)
            self.assertIn('direction', r.data['detail'])
        self.dist1.refresh_from_db()
        self.assertEqual((self.dist1.tarif, self.dist1.is_closed), (Dc('700'), False))

    def test_gerant_put_unchanged_ok_and_tarif_equivalent_decimal(self):
        g = cl(self.u['GERANT'])
        self.assertEqual(g.put(self.url(), self.put_body(self.dist1), format='json').status_code, 200)
        # 700.00 == 700 : meme valeur numerique -> pas de faux 403
        self.assertEqual(g.patch(self.url(), {'tarif': '700.00'}, format='json').status_code, 200)

    def test_comptable_put_unchanged(self):
        r = cl(self.u['COMPTABLE']).put(self.url(), self.put_body(self.dist1), format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_gerant_create_ignores_fields_comptable_too(self):
        for i, role in enumerate(('GERANT', 'COMPTABLE')):
            body = {'node': str(self.k1.pk), 'year': 2050 + i, 'tarif': '4242', 'is_closed': True}
            r = cl(self.u[role]).post('/api/clients/distributions/', body, format='json')
            if r.status_code == 201:
                d = SocialDistribution.objects.get(year=2050 + i)
                self.assertEqual((d.tarif, d.is_closed), (Dc('700'), False), role)
            else:
                self.assertIn(r.status_code, (400, 403), r.content)

    def test_admin_and_direction_ok_and_superuser(self):
        for i, role in enumerate(('ADMIN', 'DIRECTION')):
            d = SocialDistribution.objects.create(node=self.k1, year=2060 + i, tarif=Dc('700'))
            r = cl(self.u[role]).patch(self.url(d), {'tarif': '810', 'is_closed': True}, format='json')
            self.assertEqual(r.status_code, 200, (role, r.content))
            d.refresh_from_db()
            self.assertEqual((d.tarif, d.is_closed), (Dc('810'), True), role)

    def test_direction_put_changes_tarif_on_k2(self):
        r = cl(self.u['DIRECTION']).put(self.url(self.dist2), self.put_body(self.dist2, tarif='950'),
                                        format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.dist2.refresh_from_db()
        self.assertEqual(self.dist2.tarif, Dc('950'))

    def test_facturier_livreur_cannot_write(self):
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for r in (c.patch(self.url(), {'tarif': '1'}, format='json'),
                      c.patch(self.url(), {'is_closed': True}, format='json'),
                      c.put(self.url(), self.put_body(self.dist1, tarif='1'), format='json'),
                      c.post('/api/clients/distributions/',
                             {'node': str(self.k1.pk), 'year': 2070, 'tarif': '1'}, format='json')):
                self.assertEqual(r.status_code, 403, (role, r.content))
        self.dist1.refresh_from_db()
        self.assertEqual((self.dist1.tarif, self.dist1.is_closed), (Dc('700'), False))
        self.assertFalse(SocialDistribution.objects.filter(year=2070).exists())

    def test_anonymous_401(self):
        r = cl().patch(self.url(), {'tarif': '1'}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_other_node_isolation(self):
        # gerant K1 -> distribution K2 introuvable ; gerant K2 -> K1 introuvable
        g1, g2 = cl(self.u['GERANT']), cl(self.u2['GERANT'])
        for verb, body in (('patch', {'tarif': '1'}), ('patch', {'is_closed': True})):
            self.assertEqual(getattr(g1, verb)(self.url(self.dist2), body, format='json').status_code, 404)
            self.assertEqual(getattr(g2, verb)(self.url(self.dist1), body, format='json').status_code, 404)
        self.assertEqual(g1.put(self.url(self.dist2), self.put_body(self.dist2, tarif='1'),
                                format='json').status_code, 404)
        self.dist1.refresh_from_db(); self.dist2.refresh_from_db()
        self.assertEqual((self.dist1.tarif, self.dist2.tarif), (Dc('700'), Dc('900')))
        # gerant K2 sur sa propre distribution : 403 aussi
        r = g2.patch(self.url(self.dist2), {'tarif': '1'}, format='json')
        self.assertEqual(r.status_code, 403, r.content)

    def test_gerant_forged_node_with_tarif_creates_in_own_node_default_tarif(self):
        r = cl(self.u['GERANT']).post('/api/clients/distributions/',
                                      {'node': str(self.k2.pk), 'year': 2080, 'tarif': '1'}, format='json')
        if r.status_code == 201:
            d = SocialDistribution.objects.get(year=2080)
            self.assertEqual((d.node_id, d.tarif), (self.k1.pk, Dc('700')))
        self.assertFalse(SocialDistribution.objects.filter(node=self.k2, year=2080).exists())
