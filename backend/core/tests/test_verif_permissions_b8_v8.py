"""Verification BUG-1106 / BUG-1203 : LIVREUR vs FACTURIER vs GERANT (testeur-permissions, cycle 21 / ronde b8,
2026-11-23). Donnees fictives. Code applicatif non modifie.

Decision client (reponses-clients.md Q-025 / Q-027) :
  * « le livreur a les MEMES ecrans que le facturier » ;
  * « le livreur voit les clients des autres boulangeries comme le facturier, SEULEMENT en ligne ».

1. Matrice dynamique (EndpointEnumerator) FACTURIER / LIVREUR / GERANT sur TOUTES les routes API :
   - le LIVREUR ne passe jamais ou le FACTURIER est refuse ;
   - tout refus 403 du LIVREUR ou le FACTURIER passe est liste (KNOWN_FACT_ONLY) et rejoue en @expectedFailure.
   Si P21_OUT est defini, la matrice observee (JSON) y est ecrite.
2. Connectivite (sync.connectivity) : cas limites, aucun 500 ; pas d'oracle d'existence pour un client d'une autre boulangerie.
3. Fuite : livreur HORS LIGNE, balayage de toutes les routes GET avec l'identite d'un client de K2.
4. JWT du livreur : memes durees, rotation, blacklist, limitation du login.
"""
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.core.cache import cache
from django.test import override_settings
from django.urls import resolve, Resolver404
from rest_framework.schemas.generators import EndpointEnumerator
from rest_framework.test import APIClient

from clients.models import Client, SocialContribution
from commissions.models import ClientCommission, CommissionPeriod
from core.models import Node
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk
from sales.models import Invoice, InvoiceLine
from sync import connectivity, desktop_client

NIL = '00000000-0000-0000-0000-000000000000'
DENIED = (401, 403)
LOCAL = dict(KIESE_CLOUD_URL='https://etskiese.example')
CL = '/api/clients/clients/'

# Routes (methode, gabarit) ou le FACTURIER passe et le LIVREUR est refuse. Remplir apres le premier balayage.
KNOWN_FACT_ONLY = {
    ('POST', '/api/sales/invoices/'),                      # BUG-1023 (sales/views.py l.304)
    ('POST', '/api/sales/invoices/{pk}/cancel/'),          # BUG-1024 (sales/views.py l.1007)
    ('GET', '/api/production/opening-confirmation/'),      # BUG-1025 (production/views.py l.3626)
    ('POST', '/api/production/opening-confirmation/'),
    ('GET', '/api/production/team-assignment/'),           # BUG-1026 (production/views.py l.4023)
    ('POST', '/api/production/team-assignment/'),
}


def _enumerate():
    seen = set()
    for path, method, _cb in EndpointEnumerator().get_api_endpoints():
        if method in ('HEAD', 'OPTIONS') or '{format}' in path or '.{' in path:
            continue
        if (method, path) in seen:
            continue
        seen.add((method, path))
        yield method, path


def _concrete(path, candidates):
    for cand in candidates:
        url = re.sub(r'\{[^}]+\}', str(cand), path)
        try:
            resolve(url)
            return url
        except Resolver404:
            continue
    return None


def _call(client, method, url, params=None):
    if method in ('GET', 'DELETE'):
        return getattr(client, method.lower())(url, params or {})
    return getattr(client, method.lower())(url, {}, format='json')


class B8(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cx = Client.objects.create(node=cls.k2, node_origin='P2', first_name='Zorglub', last_name='Tsimbalar',
                                       phone='0899911122', credit_limit=Dc('50000'), commission_rate=Dc('0.25'))
        cls.inv2 = Invoice.objects.create(
            node=cls.k2, client=cls.cx, facturier=cls.u2['FACTURIER'], team='A', payment_type='CASH',
            payment_amount=500, debt_before=0, order_total=500, commission_rate='0.25', node_origin='P2',
            receipt_number=f'B8-{uuid.uuid4().hex[:8]}', status=Invoice.Status.DELIVERED)
        InvoiceLine.objects.create(invoice=cls.inv2, bread_price=cls.bp, quantity=1)
        cls.inv1 = Invoice.objects.create(
            node=cls.k1, client=cls.c1, facturier=cls.u['FACTURIER'], team='A', payment_type='CASH',
            payment_amount=500, debt_before=0, order_total=500, commission_rate='0.25', node_origin='P1',
            receipt_number=f'B8-{uuid.uuid4().hex[:8]}', status=Invoice.Status.PENDING)
        InvoiceLine.objects.create(invoice=cls.inv1, bread_price=cls.bp, quantity=1)
        cls.per2 = CommissionPeriod.objects.create(node=cls.k2, month=10, year=2026, node_origin='P2')
        cls.cm2 = ClientCommission.objects.create(period=cls.per2, client=cls.cx, order_value=Dc('100000'),
                                                  node_origin='P2')
        cls.sc2 = SocialContribution.objects.create(client=cls.cx, node=cls.k2, month=1, year=2026, amount=Dc('3000'))

    def setUp(self):
        cache.clear()
        saved = dict(desktop_client._STATE)
        self.addCleanup(lambda: (desktop_client._STATE.clear(), desktop_client._STATE.update(saved)))
        desktop_client._STATE.update(last_push_at=None, last_pull_at=None)

    def tearDown(self):
        cache.clear()

    def go_online(self, minutes_ago=1):
        desktop_client._STATE['last_pull_at'] = time.time() - minutes_ago * 60


# ---------------------------------------------------------------------------
# 1. Matrice dynamique LIVREUR / FACTURIER / GERANT
# ---------------------------------------------------------------------------
class MatriceLivreur(B8):
    _obs = None

    def matrix(self):
        clients = {'GERANT': cl(self.u['GERANT']), 'FACTURIER': cl(self.u['FACTURIER']),
                   'LIVREUR': cl(self.u['LIVREUR'])}
        obs = {}
        for method, path in sorted(_enumerate()):
            if path.startswith('/api/sync/') and path != '/api/sync/local-status/':
                continue  # jeton de noeud, pas de JWT humain
            if path in ('/api/core/auth/login/', '/api/core/auth/login/refresh/'):
                continue
            url = _concrete(path, [NIL, '1', 'P1'])
            if url is None:
                obs[f'{method} {path}'] = {'url': None}
                continue
            row = {'url': url}
            for role, c in clients.items():
                try:
                    row[role] = _call(c, method, url).status_code
                except Exception as exc:  # 500 non gere
                    row[role] = f'EXC:{type(exc).__name__}'
            obs[f'{method} {path}'] = row
        out = os.environ.get('P21_OUT')
        if out:
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(obs, f, ensure_ascii=False, indent=0, sort_keys=True)
        return obs

    def split(self, obs):
        fact_only, liv_only, errs, unres = [], [], [], []
        for key, row in obs.items():
            if row.get('url') is None:
                unres.append(key)
                continue
            for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
                st = row[role]
                if isinstance(st, str) or st >= 500:
                    errs.append(f'{key} {role}={st}')
            if isinstance(row['FACTURIER'], str) or isinstance(row['LIVREUR'], str):
                continue
            f_ok, l_ok = row['FACTURIER'] not in DENIED, row['LIVREUR'] not in DENIED
            m, p = key.split(' ', 1)
            if f_ok and not l_ok:
                fact_only.append((m, p))
            if l_ok and not f_ok:
                liv_only.append((m, p))
        return fact_only, liv_only, errs, unres

    def test_matrice_livreur_vs_facturier(self):
        obs = self.matrix()
        self.assertGreater(len(obs), 150)
        fact_only, liv_only, errs, unres = self.split(obs)
        self.assertEqual(errs, [], '5xx : ' + '\n'.join(errs))
        # le LIVREUR ne doit jamais passer ou le FACTURIER est refuse (« rien de plus »)
        self.assertEqual(liv_only, [], f'LIVREUR passe, FACTURIER refuse : {liv_only}')
        # aucun ecart non repertorie
        inconnu = sorted(set(fact_only) - KNOWN_FACT_ONLY)
        self.assertEqual(inconnu, [], f'FACTURIER passe, LIVREUR 403, non repertorie : {inconnu}')
        # les routes repertoriees doivent encore exister
        for k in sorted(KNOWN_FACT_ONLY - set(fact_only)):
            self.fail(f'ecart repertorie disparu (corrige ? retirer de KNOWN_FACT_ONLY et de expectedFailure) : {k}')

    def test_livreur_jamais_plus_que_gerant(self):
        obs = self.matrix()
        bad = [k for k, r in obs.items() if r.get('url') and not isinstance(r['GERANT'], str)
               and not isinstance(r['LIVREUR'], str) and r['GERANT'] in DENIED and r['LIVREUR'] not in DENIED]
        self.assertEqual(bad, [])


# ---------------------------------------------------------------------------
# 1b. Ecarts connus : le LIVREUR est refuse la ou le FACTURIER passe
# ---------------------------------------------------------------------------
class EcartsLivreurFacturier(B8):
    """Chaque test affirme d'abord que le FACTURIER passe (controle), puis que le LIVREUR passe aussi."""

    def both(self, method, url, body=None):
        f = getattr(cl(self.u['FACTURIER']), method)(url, body or {}, format='json')
        li = getattr(cl(self.u['LIVREUR']), method)(url, body or {}, format='json')
        self.assertNotIn(f.status_code, DENIED, f'controle : le FACTURIER devrait passer ({f.status_code})')
        return f, li

    # BUG-1023 (sales, dev-a) : creation de facture
    @expectedFailure
    def test_bug1023_livreur_cree_facture(self):
        _, li = self.both('post', '/api/sales/invoices/')
        self.assertNotIn(li.status_code, DENIED, 'BUG-1023 : POST /api/sales/invoices/ refuse au LIVREUR')

    # BUG-1024 (sales, dev-a) : annulation d'une facture en attente
    @expectedFailure
    def test_bug1024_livreur_annule_facture_en_attente(self):
        _, li = self.both('post', f'/api/sales/invoices/{self.inv1.pk}/cancel/')
        self.assertNotIn(li.status_code, DENIED, 'BUG-1024 : cancel refuse au LIVREUR')

    # BUG-1025 (production, dev-a) : confirmation du stock de depart
    @expectedFailure
    def test_bug1025_livreur_confirmation_stock_depart(self):
        for m in ('get', 'post'):
            _, li = self.both(m, '/api/production/opening-confirmation/')
            self.assertNotIn(li.status_code, DENIED, f'BUG-1025 : {m} opening-confirmation refuse au LIVREUR')

    # BUG-1026 (production, dev-a) : designation de l'equipe
    @expectedFailure
    def test_bug1026_livreur_designation_equipe(self):
        for m in ('get', 'post'):
            _, li = self.both(m, '/api/production/team-assignment/')
            self.assertNotIn(li.status_code, DENIED, f'BUG-1026 : {m} team-assignment refuse au LIVREUR')

    # Controles positifs : ce que le LIVREUR peut deja (BUG-1203 / BUG-1106)
    def test_livreur_cree_client_comme_facturier(self):
        body = {'first_name': 'Nadia', 'last_name': 'Tsimba', 'phone': '0810000000',
                'credit_limit': '9999999', 'commission_rate': '0.30', 'node': self.k2.pk}
        rf = cl(self.u['FACTURIER']).post(CL, body, format='json')
        rl = cl(self.u['LIVREUR']).post(CL, {**body, 'phone': '0810000001'}, format='json')
        self.assertEqual((rf.status_code, rl.status_code), (201, 201), (rf.content, rl.content))
        for r in (rf, rl):
            c = Client.objects.get(pk=r.json()['id'])
            self.assertEqual(c.node_id, self.k1.pk)  # `node` force ignore
            self.assertEqual(c.credit_limit, Dc('50000'))  # plafond impose
            self.assertEqual(c.commission_rate, Dc(str(Client._meta.get_field('commission_rate').get_default())))
        self.assertFalse(Client.objects.filter(node=self.k2, first_name='Nadia').exists())

    def test_livreur_lit_ce_que_lit_le_facturier_cote_production_ventes(self):
        for url in ('/api/sales/invoices/', f'/api/sales/invoices/{self.inv1.pk}/', '/api/production/sessions/',
                    '/api/production/stocks/', '/api/core/nodes/', '/api/core/bread-prices/',
                    '/api/production/consumable-types/', '/api/core/auth/me/'):
            f = cl(self.u['FACTURIER']).get(url)
            li = cl(self.u['LIVREUR']).get(url)
            self.assertEqual((f.status_code, li.status_code), (200, 200), url)

    def test_livreur_deliver_et_not_served_comme_facturier(self):
        for suffix in ('deliver', 'not_served'):
            f = cl(self.u['FACTURIER']).post(f'/api/sales/invoices/{self.inv1.pk}/{suffix}/', {}, format='json')
            li = cl(self.u['LIVREUR']).post(f'/api/sales/invoices/{uuid.uuid4()}/{suffix}/', {}, format='json')
            self.assertNotIn(f.status_code, DENIED, suffix)
            self.assertNotIn(li.status_code, DENIED, suffix)

    def test_livreur_ferme_sur_clients_modification_suppression_bulk_import(self):
        c = cl(self.u['LIVREUR'])
        for m, url, body in (
                ('patch', f'{CL}{self.c1.pk}/', {'credit_limit': '9999999'}),
                ('put', f'{CL}{self.c1.pk}/', {}),
                ('delete', f'{CL}{self.c1.pk}/', None),
                ('post', f'{CL}bulk_delete/', {'ids': [str(self.c1.pk)]}),
                ('post', f'{CL}bulk_move/', {'ids': [str(self.c1.pk)], 'node': self.k2.pk}),
                ('post', f'{CL}import_excel/', {}),
                ('post', f'{CL}{self.c1.pk}/recalculate_category/', {}),
                ('get', f'{CL}{self.c1.pk}/history/', None),
                ('get', f'{CL}deficit_report/', None)):
            r = getattr(c, m)(url, body or {}, format='json') if m != 'get' else c.get(url)
            self.assertEqual(r.status_code, 403, (m, url, r.status_code))
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.credit_limit, Dc('50000'))

    def test_livreur_ferme_commissions_tresorerie_admin(self):
        c = cl(self.u['LIVREUR'])
        for url in ('/api/commissions/commissions/', '/api/commissions/periods/', '/api/core/users/',
                    '/api/core/activity-logs/', '/api/treasury/cashbook/', '/api/finance/years/'):
            r = c.get(url)
            self.assertIn(r.status_code, (403, 404), (url, r.status_code))
            self.assertNotEqual(r.status_code, 200, url)
        # ecritures de config / prix
        self.assertEqual(c.patch('/api/core/config/', {'best_client_threshold': 1}, format='json').status_code, 403)
        self.assertEqual(c.post('/api/core/bread-prices/', {'category': 'X', 'label': 'x', 'unit_price': 1},
                                format='json').status_code, 403)


# ---------------------------------------------------------------------------
# 2. Connectivite : cas limites
# ---------------------------------------------------------------------------
@override_settings(**LOCAL)
class Connectivite(B8):
    def ids(self, user=None):
        r = cl(user or self.u['LIVREUR']).get(CL)
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        rows = data['results'] if isinstance(data, dict) and 'results' in data else data
        return {str(x['id']) for x in rows}

    def test_etat_corrompu_aucun_500_et_hors_ligne(self):
        for bad in ('x', None, float('nan'), float('inf'), float('-inf'), -1, 1e30, {}, [], True, '2026-11-23'):
            desktop_client._STATE['last_pull_at'] = bad
            desktop_client._STATE['last_push_at'] = bad
            self.assertEqual(self.ids(), {str(self.c1.pk)}, repr(bad))
            self.assertEqual(cl(self.u['LIVREUR']).get(f'{CL}{self.cx.pk}/').status_code, 404, repr(bad))

    def test_etat_absent_ou_modifie(self):
        saved = dict(desktop_client._STATE)
        try:
            desktop_client._STATE.clear()  # cles absentes
            self.assertEqual(self.ids(), {str(self.c1.pk)})
            desktop_client._STATE.update(last_pull_at=time.time())
            self.assertEqual(self.ids(), {str(self.c1.pk), str(self.cx.pk), str(self.c2.pk)})
        finally:
            desktop_client._STATE.clear()
            desktop_client._STATE.update(saved)

    def test_fenetre_invalide_aucun_500(self):
        for raw in ('0', '-5', 'nan', 'abc', '', None, 0, -1, True, '  ', [], {}, '1e999', 'inf', 10 ** 12):
            with override_settings(KIESE_ONLINE_WINDOW_MINUTES=raw):
                self.go_online(5)
                self.assertIsInstance(connectivity.node_is_online(self.k1), bool, repr(raw))
                r = cl(self.u['LIVREUR']).get(CL)
                self.assertEqual(r.status_code, 200, repr(raw))

    def test_fenetre_invalide_retombe_sur_15(self):
        for raw in ('0', '-5', 'nan', 'abc', '', None, 0, -1, '  '):
            with override_settings(KIESE_ONLINE_WINDOW_MINUTES=raw):
                self.assertEqual(connectivity.online_window_minutes(), 15, repr(raw))
                self.go_online(10)
                self.assertTrue(connectivity.node_is_online(self.k1), repr(raw))
                self.go_online(20)
                self.assertFalse(connectivity.node_is_online(self.k1), repr(raw))

    def test_node_none_et_last_sync_absent(self):
        self.assertFalse(connectivity.node_is_online(None))
        Node.objects.filter(pk=self.k1.pk).update(last_sync=None)
        self.k1.refresh_from_db()
        self.assertFalse(connectivity.node_is_online(self.k1))
        self.assertEqual(self.ids(), {str(self.c1.pk)})

    def test_livreur_sans_boulangerie_ne_voit_rien_et_pas_de_500(self):
        sans = mk('b8_sans_noeud', 'LIVREUR', None)
        r = cl(sans).get(CL)
        self.assertEqual(r.status_code, 200, r.content)
        self.go_online()
        self.assertEqual(self.ids(sans), set())
        self.assertEqual(cl(sans).get(f'{CL}{self.c1.pk}/').status_code, 404)

    def test_bornes_de_la_fenetre_et_horloge(self):
        from django.utils import timezone as tz
        now = tz.now()
        for delta, attendu in ((0, True), (900, True), (901, False), (-1, False), (-3600, False), (10 ** 9, False)):
            Node.objects.filter(pk=self.k1.pk).update(last_sync=datetime.fromtimestamp(now.timestamp() - delta, dt_timezone.utc))
            self.k1.refresh_from_db()
            self.assertEqual(connectivity.node_is_online(self.k1, now=now), attendu, delta)

    def test_bascule_en_ligne_puis_hors_ligne_dans_la_meme_session(self):
        c = cl(self.u['LIVREUR'])
        self.assertEqual(c.get(f'{CL}{self.cx.pk}/').status_code, 404)
        self.go_online(1)
        self.assertEqual(c.get(f'{CL}{self.cx.pk}/').status_code, 200)
        self.go_online(30)
        self.assertEqual(c.get(f'{CL}{self.cx.pk}/').status_code, 404)

    def test_pas_d_oracle_d_existence_hors_ligne(self):
        c = cl(self.u['LIVREUR'])
        existant = c.get(f'{CL}{self.cx.pk}/')
        absent = c.get(f'{CL}{uuid.uuid4()}/')
        self.assertEqual((existant.status_code, existant.content), (absent.status_code, absent.content))
        for m in ('patch', 'delete', 'put'):
            a = getattr(c, m)(f'{CL}{self.cx.pk}/', {}, format='json')
            b = getattr(c, m)(f'{CL}{uuid.uuid4()}/', {}, format='json')
            self.assertEqual((a.status_code, a.content), (b.status_code, b.content), m)

    def test_filtres_node_et_recherche_hors_ligne(self):
        c = cl(self.u['LIVREUR'])
        for params in ({'node': self.k2.pk}, {'search': 'Tsimbalar'}, {'search': self.cx.code},
                       {'search': '0899911122'}, {'search': 'zorglub', 'ordering': 'last_name'},
                       {'search': 'Tsimbalar', 'is_active': 'true', 'category': 'NORMAL'}):
            r = c.get(CL, params)
            self.assertEqual(r.status_code, 200, params)
            self.assertNotIn('Tsimbalar', r.content.decode(), params)
            self.assertNotIn(str(self.cx.pk), r.content.decode(), params)

    def test_actions_liste_hors_ligne_ne_fuitent_pas(self):
        c = cl(self.u['LIVREUR'])
        Client.objects.filter(pk=self.cx.pk).update(category=Client.Category.RISK)
        for suffix in ('risk_alerts/', 'best_clients/', 'active_last_month/', 'bassins/?node=%d&month=10&year=2026' % self.k2.pk):
            r = c.get(f'{CL}{suffix}')
            self.assertNotIn(r.status_code, (500,), suffix)
            self.assertNotIn('Tsimbalar', r.content.decode(), suffix)
        Client.objects.filter(pk=self.cx.pk).update(category=Client.Category.NORMAL)

    def test_facturier_et_gerant_inchanges_hors_ligne(self):
        self.assertEqual(self.ids(self.u['FACTURIER']), {str(self.c1.pk), str(self.c2.pk), str(self.cx.pk)})
        self.assertEqual(self.ids(self.u['GERANT']), {str(self.c1.pk)})

    def test_creation_hors_ligne_ne_revele_pas_un_client_d_ailleurs(self):
        r = cl(self.u['LIVREUR']).post(CL, {'first_name': 'Zorglub', 'last_name': 'Tsimbalar', 'phone': '0899911122'},
                                       format='json')
        txt = r.content.decode()
        self.assertNotIn(self.cx.code, txt)
        self.assertNotIn('P2', txt)
        self.assertNotIn(str(self.cx.pk), txt)


# ---------------------------------------------------------------------------
# 3. Fuite : livreur hors ligne, balayage de toutes les routes GET
# ---------------------------------------------------------------------------
@override_settings(**LOCAL)
class FuiteHorsLigne(B8):
    def needles(self):
        return ['tsimbalar', 'zorglub', str(self.cx.pk), self.cx.code.lower(), '0899911122']

    def scan(self, user):
        c = cl(user)
        cands = [self.cx.pk, self.inv2.pk, self.cm2.pk, self.per2.pk, self.sc2.pk, self.k2.pk, 'P2']
        params = {'search': 'Tsimbalar', 'q': 'Tsimbalar', 'client': str(self.cx.pk), 'client_id': str(self.cx.pk),
                  'node': self.k2.pk, 'month': 10, 'year': 2026}
        hits, calls = [], 0
        for method, path in sorted(_enumerate()):
            if method != 'GET' or path.startswith('/api/sync/'):
                continue
            urls = set()
            if '{' in path:
                for cand in cands:
                    u = _concrete(path, [cand])
                    if u:
                        urls.add(u)
            else:
                urls.add(path)
            for url in sorted(urls):
                for p in (None, params):
                    calls += 1
                    r = c.get(url, p or {})
                    body = r.content.decode('utf-8', 'ignore').lower()
                    for n in self.needles():
                        if n in body:
                            hits.append((url, 'params' if p else 'sans', r.status_code, n))
                            break
        self.assertGreater(calls, 200)
        return hits

    def test_controle_positif_le_balayage_voit_la_fuite_du_facturier(self):
        hits = self.scan(self.u['FACTURIER'])
        self.assertTrue(any(h[0].startswith(CL) for h in hits), 'le balayage ne detecte rien meme pour le facturier')

    def test_livreur_hors_ligne_aucune_fuite_sur_les_routes_get(self):
        hits = self.scan(self.u['LIVREUR'])
        self.assertEqual(hits, [], 'FUITE livreur hors ligne : ' + '; '.join(map(str, hits)))

    def test_livreur_en_ligne_voit_comme_le_facturier(self):
        self.go_online()
        r = cl(self.u['LIVREUR']).get(CL, {'search': 'Tsimbalar'})
        self.assertIn('Tsimbalar', r.content.decode())


# ---------------------------------------------------------------------------
# 4. JWT du livreur
# ---------------------------------------------------------------------------
class JwtLivreur(B8):
    PW = 'Mdp-Qa-b8-12345'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for role in ('LIVREUR', 'FACTURIER'):
            u = cls.u[role]
            u.set_password(cls.PW)
            u.save()

    def login(self, role, pw=None):
        return APIClient().post('/api/core/auth/login/', {'username': self.u[role].username,
                                                          'password': pw or self.PW}, format='json')

    def test_memes_durees_que_le_facturier(self):
        from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
        spans = {}
        for role in ('LIVREUR', 'FACTURIER'):
            d = self.login(role).json()
            a, r = AccessToken(d['access']), RefreshToken(d['refresh'])
            spans[role] = (a['exp'] - a['iat'], r['exp'] - r['iat'])
        self.assertEqual(spans['LIVREUR'], spans['FACTURIER'])
        self.assertLessEqual(spans['LIVREUR'][0], 30 * 60)
        self.assertLessEqual(spans['LIVREUR'][1], 7 * 86400)

    def test_rotation_et_reutilisation_refusees(self):
        d = self.login('LIVREUR').json()
        c = APIClient()
        r1 = c.post('/api/core/auth/login/refresh/', {'refresh': d['refresh']}, format='json')
        self.assertEqual(r1.status_code, 200)
        r2 = c.post('/api/core/auth/login/refresh/', {'refresh': d['refresh']}, format='json')
        self.assertEqual(r2.status_code, 401)

    def test_refresh_apres_logout_refuse(self):
        d = self.login('LIVREUR').json()
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {d['access']}")
        self.assertEqual(c.post('/api/core/auth/logout/', {'refresh': d['refresh']}, format='json').status_code, 200)
        r = APIClient().post('/api/core/auth/login/refresh/', {'refresh': d['refresh']}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_jeton_expire_refuse(self):
        from rest_framework_simplejwt.tokens import AccessToken
        d = self.login('LIVREUR').json()
        tok = AccessToken(d['access'])
        tok.set_exp(from_time=tok.current_time, lifetime=-__import__('datetime').timedelta(seconds=5))
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
        self.assertEqual(c.get('/api/core/auth/me/').status_code, 401)

    def test_jeton_livreur_ne_donne_pas_de_role_superieur(self):
        d = self.login('LIVREUR').json()
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {d['access']}")
        me = c.get('/api/core/auth/me/').json()
        self.assertEqual(me['role'], 'LIVREUR')
        r = c.patch('/api/core/auth/me/', {'role': 'ADMIN', 'is_superuser': True, 'node': self.k2.pk}, format='json')
        self.u['LIVREUR'].refresh_from_db()
        self.assertEqual((self.u['LIVREUR'].role, self.u['LIVREUR'].is_superuser, self.u['LIVREUR'].node_id),
                         ('LIVREUR', False, self.k1.pk), r.content)

    def test_limitation_des_tentatives_de_login_livreur(self):
        codes = [self.login('LIVREUR', pw='faux-mdp').status_code for _ in range(8)]
        self.assertEqual(codes[0], 401)
        self.assertIn(429, codes)
        # un autre compte (meme IP) n'est pas bloque par le compte vise (BUG-087)
        self.assertEqual(self.login('FACTURIER').status_code, 200)
