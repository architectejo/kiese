"""
BUG-1050 (A-1, client Q-027 : « le livreur a les memes ecrans que le facturier »).

Matrice role x route : le LIVREUR doit obtenir, sur chaque route de ventes et de
production ouverte au FACTURIER, exactement le meme resultat que le FACTURIER
(meme statut), avec l'isolation par boulangerie inchangee et sans rien de plus
(adjust, cleanup-expired, PATCH commission_exempt, clotures, transferts,
mouvements de consommables : refuses aux deux).

Point note dans la fiche : la creation de facture (et donc le remboursement,
qui passe par POST /invoices/) par un livreur est ouverte, car le facturier le
peut et le client demande les memes ecrans.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client

INV = '/api/sales/invoices/'
PROD = '/api/production/'


def _api(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


class LivreurCommeFacturierBase(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.u = {
            'FACTURIER': make_user('FACTURIER', node=self.k1),
            'LIVREUR': make_user('LIVREUR', node=self.k1),
            'GERANT': make_user('GERANT', node=self.k1),
        }
        self.autre = {
            'FACTURIER': make_user('FACTURIER', node=self.k2),
            'LIVREUR': make_user('LIVREUR', node=self.k2),
        }
        self.sans_node = {
            'FACTURIER': make_user('FACTURIER', node=None),
            'LIVREUR': make_user('LIVREUR', node=None),
        }
        self.client_k1 = make_client(self.k1)

    def payload(self, qty=2, paid='1000.00'):
        return {
            'client': str(self.client_k1.pk),
            'payment_type': 'CASH',
            'payment_amount': paid,
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }

    def new_invoice(self):
        r = _api(self.u['FACTURIER']).post(INV, self.payload(), format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def both(self, fn):
        """Applique `fn(user) -> status` au facturier puis au livreur, verifie l'egalite."""
        res = {role: fn(self.u[role]) for role in ('FACTURIER', 'LIVREUR')}
        self.assertEqual(res['LIVREUR'], res['FACTURIER'], res)
        return res['FACTURIER']


class VentesLivreurTests(LivreurCommeFacturierBase):
    def test_creation_facture(self):
        for role in ('FACTURIER', 'LIVREUR', 'GERANT'):
            r = _api(self.u[role]).post(INV, self.payload(), format='json')
            self.assertEqual(r.status_code, 201, (role, r.data))
        self.assertEqual(_api().post(INV, self.payload(), format='json').status_code, 401)

    def test_creation_rattachee_a_la_boulangerie_de_l_utilisateur(self):
        """Le livreur d'une autre boulangerie facture un client de K1 comme le
        facturier (recherche inter-boulangeries inchangee) : la facture est
        rattachee a SA boulangerie."""
        res = {}
        for role in ('FACTURIER', 'LIVREUR'):
            r = _api(self.autre[role]).post(INV, self.payload(), format='json')
            res[role] = r.status_code
            if r.status_code == 201:
                self.assertEqual(r.data['node'], self.k2.pk, role)
        self.assertEqual(res['LIVREUR'], res['FACTURIER'], res)

    def test_remboursement_sans_ligne(self):
        corps = {'client': str(self.client_k1.pk), 'payment_type': 'CASH',
                 'payment_amount': '500.00', 'lines': []}
        statut = self.both(lambda u: _api(u).post(INV, corps, format='json').status_code)
        self.assertIn(statut, (201, 400))  # meme resultat ; jamais 403 pour le livreur
        r = _api(self.u['LIVREUR']).post(INV, corps, format='json')
        self.assertNotEqual(r.status_code, 403, r.data)

    def test_livraison_non_servi_annulation(self):
        for action in ('deliver', 'mark-not-served', 'cancel'):
            for role in ('FACTURIER', 'LIVREUR'):
                pk = self.new_invoice()
                r = _api(self.u[role]).post(f'{INV}{pk}/{action}/', {}, format='json')
                self.assertEqual(r.status_code, 200, (action, role, r.data))
            pk = self.new_invoice()
            self.assertEqual(_api().post(f'{INV}{pk}/{action}/').status_code, 401, action)
            # autre boulangerie : facture hors perimetre -> 404 pour les deux
            for role in ('FACTURIER', 'LIVREUR'):
                r = _api(self.autre[role]).post(f'{INV}{pk}/{action}/', {}, format='json')
                self.assertEqual(r.status_code, 404, (action, role, r.status_code))
            # compte sans boulangerie : rien (meme resultat que le facturier, jamais 200)
            statut = self.both(lambda u, a=action, p=pk: _api(
                self.sans_node[u.role]).post(f'{INV}{p}/{a}/', {}, format='json').status_code)
            self.assertIn(statut, (403, 404), action)

    def test_actions_reservees_au_gerant_refusees_aux_deux(self):
        pk = self.new_invoice()
        cas = [
            ('post', f'{INV}{pk}/adjust/', {}),
            ('post', f'{INV}cleanup_expired/', {}),
            ('patch', f'{INV}{pk}/', {'commission_exempt': True}),
            ('put', f'{INV}{pk}/', {}),
            ('delete', f'{INV}{pk}/', None),
        ]
        for method, url, data in cas:
            for role in ('FACTURIER', 'LIVREUR'):
                r = getattr(_api(self.u[role]), method)(url, data, format='json') if data is not None \
                    else getattr(_api(self.u[role]), method)(url)
                self.assertIn(r.status_code, (403, 405), (method, url, role, r.status_code))
        r = _api(self.u['GERANT']).post(f'{INV}{pk}/adjust/', {}, format='json')
        self.assertNotEqual(r.status_code, 403, r.data)

    def test_lectures(self):
        pk = self.new_invoice()
        routes = [
            INV, f'{INV}{pk}/', f'{INV}pending_deliveries/',
            f'{INV}daily_summary/', f'{INV}bread_summary/',
            f'{INV}?search=Client', f'{INV}?status=PENDING',
        ]
        for url in routes:
            statut = self.both(lambda u, url=url: _api(u).get(url).status_code)
            self.assertEqual(statut, 200, url)
            self.assertEqual(_api().get(url).status_code, 401, url)
        # le livreur voit la meme liste que le facturier (meme boulangerie)
        a = _api(self.u['FACTURIER']).get(INV).data
        b = _api(self.u['LIVREUR']).get(INV).data
        ids = lambda d: sorted(x['id'] for x in (d['results'] if isinstance(d, dict) else d))
        self.assertEqual(ids(a), ids(b))
        self.assertIn(pk, ids(b))

    def test_isolation_lecture_autre_boulangerie_et_sans_boulangerie(self):
        pk = self.new_invoice()
        ids = lambda d: [x['id'] for x in (d['results'] if isinstance(d, dict) else d)]
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertNotIn(pk, ids(_api(self.autre[role]).get(INV).data), role)
            self.assertEqual(_api(self.autre[role]).get(f'{INV}{pk}/').status_code, 404, role)
            r = _api(self.sans_node[role]).get(INV)
            self.assertEqual(r.status_code, 200, role)
            self.assertEqual(ids(r.data), [], role)
            self.assertEqual(_api(self.sans_node[role]).get(f'{INV}{pk}/').status_code, 404, role)


class ProductionLivreurTests(LivreurCommeFacturierBase):
    LECTURES = [
        'sessions/', 'bread-stocks/', 'stocks/', 'transfers/', 'disposals/',
        'consumable-types/', 'opening-confirmation/', 'team-assignment/',
        'shift-end-status/', 'sessions/shift-end-status/',
    ]

    def test_lectures_autorisees_au_facturier(self):
        for rel in self.LECTURES:
            statut = self.both(lambda u, rel=rel: _api(u).get(PROD + rel).status_code)
            if statut == 404:
                continue  # route inexistante (liste indicative)
            # disposals : IsGerant (refuse aux deux) ; le reste lisible
            if rel == 'disposals/':
                self.assertEqual(statut, 403, rel)
            else:
                self.assertEqual(statut, 200, rel)

    def test_confirmation_ouverture_et_equipe(self):
        for url, corps in (('opening-confirmation/', None), ('team-assignment/', {'team': 'A'})):
            r = _api(self.u['LIVREUR']).get(PROD + url)
            self.assertEqual(r.status_code, 200, (url, r.data))
            self.assertEqual(_api().get(PROD + url).status_code, 401, url)
            if corps:
                for role in ('FACTURIER', 'LIVREUR'):
                    r = _api(self.u[role]).post(PROD + url, corps, format='json')
                    self.assertEqual(r.status_code, 200, (url, role, r.data))

    def test_ecritures_reservees_au_gerant_refusees_aux_deux(self):
        cas = [
            ('post', 'sessions/'), ('post', 'transfers/'), ('post', 'movements/'),
            ('post', 'stocks/'), ('post', 'disposals/'), ('get', 'daily-closure/'),
            ('get', 'daily-closure/clients/'), ('get', 'movements/'), ('get', 'counts/'),
        ]
        for method, rel in cas:
            for role in ('FACTURIER', 'LIVREUR'):
                r = getattr(_api(self.u[role]), method)(PROD + rel, *( [{}] if method == 'post' else []),
                                                         **({'format': 'json'} if method == 'post' else {}))
                self.assertEqual(r.status_code, 403, (method, rel, role, r.status_code))

    def test_isolation_autre_boulangerie_et_sans_boulangerie(self):
        for role in ('FACTURIER', 'LIVREUR'):
            r = _api(self.autre[role]).get(PROD + 'sessions/')
            self.assertEqual(r.status_code, 200, role)
            r = _api(self.sans_node[role]).get(PROD + 'sessions/')
            self.assertEqual(r.status_code, 200, role)
            data = r.data['results'] if isinstance(r.data, dict) else r.data
            self.assertEqual(list(data), [], role)
            # compte sans boulangerie : jamais de confirmation d'ouverture
            r = _api(self.sans_node[role]).get(PROD + 'opening-confirmation/')
            self.assertEqual(r.status_code, 400, role)
