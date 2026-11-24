"""Testeur-ventes/production (cycle 22 / a8) : verification independante de BUG-1050 / BUG-1051 (livreur = facturier).
Principe : sur CHAQUE route de /api/sales/ et /api/production/, le LIVREUR ne doit jamais etre admis
la ou le FACTURIER est refuse (jamais plus que le facturier) ; les routes ouvertes par 1050 sont exactement
celles attendues ; aucun role inferieur (CLIENT / role inconnu) n'est admis ; l'isolation par boulangerie tient ;
le push d'une facture dont `facturier` est un livreur est accepte. Donnees fictives.
"""
import uuid
from decimal import Decimal

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice

INV = '/api/sales/invoices/'
FAKE = '00000000-0000-4000-8000-000000000001'


def _api(user):
    a = APIClient(raise_request_exception=False)
    if user is not None:
        a.force_authenticate(user)
    return a


def _routes(prefix):
    """Toutes les routes (chemin avec parametres substitues, methodes) sous `prefix`."""
    out = []

    def walk(patterns, base):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, base + str(p.pattern))
            elif isinstance(p, URLPattern):
                out.append(base + str(p.pattern))

    walk(get_resolver().url_patterns, '')
    paths = []
    for raw in out:
        if not raw.startswith(f'api/{prefix}/'):
            continue
        path = raw
        path = path.replace('^', '').replace('$', '').replace('\\.(?P<format>[a-z0-9]+)/?', '')
        import re
        path = re.sub(r'\(\?P<[a-z_]+>[^)]*\)', FAKE, path)
        path = re.sub(r'<(?:uuid|int|str|slug)?:?[a-z_]*>', FAKE, path)
        if '(' in path or 'drf_format_suffix' in path:
            continue
        path = path.replace('?', '').rstrip('/') + '/'
        paths.append('/' + path)
    return sorted(set(paths))


class RolesNeDepassentJamaisLeFacturier(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.fa = make_user('FACTURIER', node=self.k1)
        self.li = make_user('LIVREUR', node=self.k1)
        self.cl = make_client(self.k1)

    def _status(self, user, method, path):
        c = _api(user)
        body = {}
        return getattr(c, method)(path, body, format='json').status_code

    def test_crawler_le_livreur_n_est_jamais_admis_ou_le_facturier_est_refuse(self):
        paths = _routes('sales') + _routes('production')
        self.assertGreater(len(paths), 40)
        plus = []
        deltas = []
        for path in paths:
            for method in ('get', 'post', 'patch', 'delete'):
                f = self._status(self.fa, method, path)
                l = self._status(self.li, method, path)
                self.assertNotEqual(f, 500, (method, path, 'facturier'))
                self.assertNotEqual(l, 500, (method, path, 'livreur'))
                if l not in (401, 403) and f in (401, 403):
                    plus.append((method, path, f, l))
                if (f in (401, 403)) != (l in (401, 403)):
                    deltas.append((method, path, f, l))
        self.assertEqual(plus, [], 'le livreur obtient plus que le facturier')
        # info : routes ou le livreur est refuse et le facturier admis (ecart restant a la parite Q-027)
        print('\nFACTURIER admis / LIVREUR refuse :', [(m, p) for m, p, f, l in deltas][:40])

    def test_anonyme_et_role_inconnu_refuses_partout(self):
        paths = _routes('sales') + _routes('production')
        bad = []
        for path in paths:
            for method in ('post', 'patch', 'delete'):
                s = self._status(None, method, path)
                if s not in (401, 403):
                    bad.append((method, path, s))
        # routes publiques eventuelles : listees, pas supposees
        self.assertEqual([b for b in bad if b[2] < 400 or b[2] == 500], [], bad)

    def test_routes_ouvertes_par_1050_sont_exactement_les_quatre_attendues(self):
        """Ecart facturier/livreur nul sur les routes de 1050 ; routes qui restent fermees au livreur et au
        facturier : ajustement, nettoyage, PATCH facture, clotures, transferts (gerant)."""
        ouvertes = [('post', INV), ('post', f'{INV}{FAKE}/cancel/'), ('post', '/api/production/opening-confirmation/'),
                    ('post', '/api/production/team-assignment/')]
        for method, path in ouvertes:
            f, l = self._status(self.fa, method, path), self._status(self.li, method, path)
            self.assertNotIn(l, (401, 403), (method, path, l))
            self.assertEqual((f in (401, 403)), (l in (401, 403)), (method, path, f, l))
        fermees = [('post', f'{INV}{FAKE}/adjust/'), ('patch', f'{INV}{FAKE}/'), ('delete', f'{INV}{FAKE}/'),
                   ('post', f'{INV}cleanup-expired/')]
        for method, path in fermees:
            self.assertIn(self._status(self.li, method, path), (403, 404, 405), (method, path))
            self.assertIn(self._status(self.fa, method, path), (403, 404, 405), (method, path))

    def test_livreur_sans_boulangerie_ne_cree_rien_et_pas_de_500(self):
        sans = make_user('LIVREUR', node=None)
        n = Invoice.objects.count()
        r = _api(sans).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': '0',
                                  'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}, format='json')
        self.assertLess(r.status_code, 500)
        f = _api(make_user('FACTURIER', node=None)).post(
            INV, {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': '0',
                  'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, f.status_code)
        if r.status_code >= 400:
            self.assertEqual(Invoice.objects.count(), n)

    def test_annulation_isolee_par_boulangerie_livreur_k2_ne_touche_pas_k1(self):
        r = _api(self.fa).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': '0',
                                     'lines': [{'bread_price': self.bp.pk, 'quantity': 2}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        iid = r.data['id']
        autre = make_user('LIVREUR', node=self.k2)
        r2 = _api(autre).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertIn(r2.status_code, (403, 404), r2.data)
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')
        r3 = _api(self.li).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(r3.status_code, 200, r3.data)
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'CANCELLED')
        # un second POST (idempotence / double annulation) : pas 500, pas de double restitution
        r4 = _api(self.li).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertLess(r4.status_code, 500)

    def test_designation_d_equipe_livreur_ignore_le_parametre_node_et_reste_a_et_b(self):
        li2 = make_user('LIVREUR', node=self.k2)
        base = '/api/production/team-assignment/'
        r = _api(self.li).post(base, {'team': 'A', 'node': 'K2'}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        from production.models import DailyTeamAssignment
        nodes = set(DailyTeamAssignment.objects.values_list('node__code', flat=True))
        self.assertEqual(nodes, {'K1'})  # `node` ignore pour un non-HQ
        for team in ('C', 'J', 'N', '', None, 5, ['A']):
            r = _api(li2).post(base, {'team': team}, format='json')
            self.assertEqual(r.status_code, 400, (team, getattr(r, 'data', None)))
        r = _api(li2).get(base)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(DailyTeamAssignment.objects.values_list('node__code', flat=True)), {'K1'})

    def test_confirmation_stock_de_depart_livreur_meme_resultat_que_facturier_et_isole(self):
        base = '/api/production/opening-confirmation/'
        body = {'team': 'A', 'node': 'K2', 'lines': [{'bread_price': self.bp.pk, 'qty': 5}]}
        r_l = _api(self.li).post(base, body, format='json')
        r_f = _api(self.fa).post(base, body, format='json')
        self.assertEqual(r_l.status_code, r_f.status_code, (r_l.data, r_f.data))
        self.assertLess(r_l.status_code, 500)
        from production.models import DailyOpeningConfirmation
        self.assertEqual(set(DailyOpeningConfirmation.objects.values_list('node__code', flat=True)) - {'K1'}, set())
        # GET : meme verdict
        self.assertEqual(_api(self.li).get(base).status_code, _api(self.fa).get(base).status_code)


class PushFactureFacturierLivreur(TestCase):
    """Point d'attention du testeur de permissions : `Invoice.facturier` = un livreur est-il accepte par la sync ?"""

    def setUp(self):
        from sync.models import NodeAuthToken
        self.k1 = make_node(code='K1')
        self.li = make_user('LIVREUR', node=self.k1)
        self.cl = make_client(self.k1)
        _, raw = NodeAuthToken.issue_for_node(self.k1)
        self.api = APIClient(raise_request_exception=False)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')

    def push(self, rec):
        r = self.api.post('/api/sync/push/', {'batch_id': str(uuid.uuid4()),
                                             'records': {'sales.Invoice': [rec]}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        x = r.data['results']['sales.Invoice'][0]
        return x['status'], x.get('reason')

    def inv(self, **kw):
        d = {'id': str(uuid.uuid4()), 'node': 'K1', 'client': str(self.cl.pk), 'team': 'A', 'status': 'PENDING',
             'payment_type': 'CASH', 'order_total': '5000', 'payment_amount': '5000', 'debt_before': '0',
             'debt_after': '0'}
        d.update(kw)
        return d

    def test_facture_dont_le_facturier_est_un_livreur_acceptee(self):
        rec = self.inv(facturier=str(self.li.pk), livreur=str(self.li.pk))
        status, reason = self.push(rec)
        self.assertEqual(status, 'ACCEPTED', reason)
        inv = Invoice.objects.get(pk=rec['id'])
        self.assertEqual(inv.order_total, Decimal('5000'))

    def test_facturier_inconnu_ou_malforme_ne_fait_pas_de_500(self):
        for f in (str(uuid.uuid4()), 'abc', 123, None, ''):
            status, reason = self.push(self.inv(facturier=f))
            self.assertIn(status, ('ACCEPTED', 'REJECTED'), (f, reason))

    def test_facturier_pousse_est_aujourd_hui_ignore_observation(self):
        """Changement voulu (BUG-1112, sync/services.py::_resolve_invoice_staff) : l'observation « `_push_invoice`
        ne lit pas `facturier` » est perimee. Le facturier / livreur pousse est desormais conserve s'il est valide
        (UUID strict, utilisateur existant, role admis, MEME boulangerie que le jeton de noeud) ; sinon NULL, sans
        rejet. Un facturier d'une autre boulangerie ne peut donc pas etre attribue (pas de regression de securite)."""
        fa = make_user('FACTURIER', node=self.k1)
        rec_f = self.inv(facturier=str(fa.pk))
        rec_l = self.inv(facturier=str(self.li.pk))
        self.push(rec_f)
        self.push(rec_l)
        self.assertEqual(Invoice.objects.get(pk=rec_f['id']).facturier_id, fa.pk)
        self.assertEqual(Invoice.objects.get(pk=rec_l['id']).facturier_id, self.li.pk)
        # facturier d'une autre boulangerie : ignore (NULL), la facture reste acceptee
        k2 = make_node(code='K2')
        other = make_user('FACTURIER', node=k2)
        rec_o = self.inv(facturier=str(other.pk))
        status, reason = self.push(rec_o)
        self.assertEqual(status, 'ACCEPTED', reason)
        self.assertIsNone(Invoice.objects.get(pk=rec_o['id']).facturier_id)
