"""Regression des droits d'acces sur 528875c (testeur-permissions, 2026-11-19).

Matrice 6 roles + anonyme x routes ajoutees/modifiees depuis le 2026-11-15
(sales : paiements negatifs / motif / versement sans commande ; clients :
distributions refresh_indices, cotisation_sociale ; core : nodes
monthly_social_contribution ; production : sessions par sacs / PATCH,
daily-closure ; chat) + isolation inter-boulangeries des nouveaux champs
(objective_fc, progress_*, motif) + elevation par champs forges.
Rapport : docs/qa/rapports/testeur-permissions-2026-11-19-regression.md
Donnees fictives uniquement.
"""
import uuid
from decimal import Decimal as Dc

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import (Client, SocialContribution, SocialDistribution,
                            SocialDistributionLine)
from core.models import ActivityLog, BreadPrice, Node
from production.models import ProductionSession
from sales.models import Invoice

User = get_user_model()
ROLES = ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR']
HQ = {'ADMIN', 'DIRECTION', 'COMPTABLE'}
GERANT_UP = HQ | {'GERANT'}
FACT_UP = GERANT_UP | {'FACTURIER'}
ALL = set(ROLES)
DIRECTION_UP = {'ADMIN', 'DIRECTION'}
TODAY = '2026-11-19'


def mk(username, role, node=None, team='A'):
    # Pas de hachage de mot de passe (force_authenticate) : suite rapide.
    return User.objects.create(username=username, role=role, node=node, team=team,
                               first_name=username, last_name='Qa')


def cl(user=None):
    c = APIClient()
    if user is not None:
        c.force_authenticate(user)
    return c


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.k1 = Node.objects.create(code='P1', name='Perm K1', sac_value_fc=Dc('210000'), team_rotation_enabled=False)
        cls.k2 = Node.objects.create(code='P2', name='Perm K2', sac_value_fc=Dc('180000'), team_rotation_enabled=False)
        cls.u = {}
        for r in ROLES:
            cls.u[r] = mk(f'pr_{r.lower()}', r, None if r in HQ else cls.k1)
        cls.u2 = {r: mk(f'pr2_{r.lower()}', r, cls.k2) for r in ('GERANT', 'FACTURIER', 'LIVREUR')}
        cls.bp = BreadPrice.objects.get_or_create(
            category='MOYEN', defaults={'label': 'Pain 500', 'unit_price': 500})[0]
        cls.c1 = Client.objects.create(node=cls.k1, node_origin='P1', first_name='Ann', last_name='Un',
                                       credit_limit=Dc('50000'), commission_rate=Dc('0.25'))
        cls.c2 = Client.objects.create(node=cls.k2, node_origin='P2', first_name='Bob', last_name='Deux',
                                       credit_limit=Dc('50000'), commission_rate=Dc('0.25'))
        cls.dist1 = SocialDistribution.objects.create(node=cls.k1, year=2026, tarif=Dc('700'))
        cls.dist2 = SocialDistribution.objects.create(node=cls.k2, year=2026, tarif=Dc('900'))
        cls.line1 = SocialDistributionLine.objects.create(distribution=cls.dist1, client=cls.c1)
        cls.line2 = SocialDistributionLine.objects.create(distribution=cls.dist2, client=cls.c2)
        cls.contrib1 = SocialContribution.objects.create(client=cls.c1, node=cls.k1, month=1, year=2026,
                                                         amount=Dc('3000'))
        cls.contrib2 = SocialContribution.objects.create(client=cls.c2, node=cls.k2, month=1, year=2026,
                                                         amount=Dc('3000'))
        cls.s1 = ProductionSession.objects.create(node=cls.k1, team='A', date='2026-11-18',
                                                  flour_sacks_used=Dc('2'), declared_by=cls.u['GERANT'])
        cls.s2 = ProductionSession.objects.create(node=cls.k2, team='A', date='2026-11-18',
                                                  flour_sacks_used=Dc('3'), declared_by=cls.u2['GERANT'])
        # valeur du sac figee a la declaration (BUG-038) : fixtures cote modele
        ProductionSession.objects.filter(pk=cls.s1.pk).update(sac_value_fc_used=210000, theoretical_yield=420000)
        ProductionSession.objects.filter(pk=cls.s2.pk).update(sac_value_fc_used=180000, theoretical_yield=540000)

    def sess(self, node, sacks='4', date='2026-11-17', team='B'):
        return ProductionSession.objects.create(node=node, team=team, date=date,
                                                flour_sacks_used=Dc(sacks))


# --------------------------------------------------------------------------
# 1. Matrice anonyme + 6 roles : (methode, url, roles autorises)
# --------------------------------------------------------------------------
class Matrix(Base):
    def routes(self):
        return [
            # sales : creation = FACTURIER+ et LIVREUR (Q-027/BUG-1050 : memes droits que le
            # facturier) ; lecture = tout authentifie
            ('post', '/api/sales/invoices/', FACT_UP | {'LIVREUR'},
             {'client': str(self.c1.pk), 'payment_type': 'CASH', 'payment_amount': '-500',
              'motif': 'EMPRUNT_BOULANGER', 'is_debt_repayment': True, 'lines': []}),
            ('get', '/api/sales/invoices/', ALL, None),
            # clients : distributions (GERANT+)
            ('get', '/api/clients/distributions/', GERANT_UP, None),
            ('get', f'/api/clients/distributions/{self.dist1.pk}/', GERANT_UP, None),
            ('post', f'/api/clients/distributions/{self.dist1.pk}/refresh_indices/', GERANT_UP, {}),
            ('post', f'/api/clients/distributions/{self.dist1.pk}/auto_populate_lines/', GERANT_UP, {}),
            ('patch', f'/api/clients/distributions/{self.dist1.pk}/', GERANT_UP, {'tarif': '700'}),
            ('delete', f'/api/clients/distributions/{uuid.uuid4()}/', GERANT_UP, None),
            ('get', '/api/clients/distribution-lines/', GERANT_UP, None),
            ('patch', f'/api/clients/distribution-lines/{self.line1.pk}/', GERANT_UP, {'merite': '0'}),
            ('get', '/api/clients/contributions/', GERANT_UP, None),
            ('post', '/api/clients/contributions/bulk_create_month/', GERANT_UP,
             {'month': 5, 'year': 2026}),
            ('post', f'/api/clients/contributions/{self.contrib1.pk}/toggle_paid/', GERANT_UP, {}),
            ('patch', f'/api/clients/clients/{self.c1.pk}/', GERANT_UP, {'cotisation_sociale': '1000'}),
            # core : nodes (lecture tout authentifie ; ecriture DIRECTION+)
            ('get', '/api/core/nodes/', ALL, None),
            ('get', f'/api/core/nodes/{self.k1.pk}/', ALL, None),
            ('patch', f'/api/core/nodes/{self.k1.pk}/', DIRECTION_UP,
             {'monthly_social_contribution': '2000'}),
            ('post', '/api/core/nodes/', DIRECTION_UP, {'code': 'ZZ9', 'name': 'x'}),
            # production
            ('get', '/api/production/sessions/', ALL, None),
            ('post', '/api/production/sessions/', GERANT_UP,
             {'flour_sacks_used': '2', 'team': 'A', 'date': TODAY, 'node': self.k1.pk}),
            ('patch', f'/api/production/sessions/{self.s1.pk}/', GERANT_UP,
             {'flour_sacks_used': '3'}),
            ('delete', f'/api/production/sessions/{uuid.uuid4()}/', GERANT_UP, None),
            ('get', f'/api/production/daily-closure/?node={self.k1.pk}&date={TODAY}', GERANT_UP, None),
            ('post', f'/api/production/sessions/{self.s1.pk}/close/', GERANT_UP, {'lines': []}),
            ('get', f'/api/production/sessions/reconciliation/?node={self.k1.pk}&date={TODAY}',
             GERANT_UP, None),
            # chat : tout authentifie rattache a un role (annuaire, liste, non-lus)
            ('get', '/api/chat/conversations/', ALL, None),
            ('get', '/api/chat/unread-count/', ALL, None),
            ('get', '/api/chat/users/', ALL, None),
        ]

    def test_matrix(self):
        fails = []
        for method, url, allowed, body in self.routes():
            # anonyme -> 401
            r = getattr(cl(), method)(url, body, format='json') if body is not None \
                else getattr(cl(), method)(url)
            if r.status_code != 401:
                fails.append(('anon', method, url, r.status_code))
            for role in ROLES:
                # un objet detruit par un test precedent ne doit pas fausser : on
                # rejoue sur le meme jeu (TestCase = transaction annulee par test)
                u = self.u[role]
                c = cl(u)
                r = getattr(c, method)(url, body, format='json') if body is not None \
                    else getattr(c, method)(url)
                denied = r.status_code in (401, 403)
                if role in allowed and denied:
                    fails.append((role, method, url, 'attendu autorise', r.status_code))
                if role not in allowed and r.status_code != 403:
                    fails.append((role, method, url, 'attendu 403', r.status_code))
                if r.status_code >= 500:
                    fails.append((role, method, url, '5xx', r.status_code))
        self.assertEqual(fails, [])


# --------------------------------------------------------------------------
# 2. Isolation inter-boulangeries : sales (paiements negatifs, motif)
# --------------------------------------------------------------------------
class SalesIsolation(Base):
    def test_negative_payment_with_motif_on_foreign_node_forged(self):
        """Facturier K1 forge node=K2 : la facture est rattachee a K1 (ou refusee)."""
        r = cl(self.u['FACTURIER']).post('/api/sales/invoices/', {
            'node': self.k2.pk, 'client': str(self.c1.pk), 'payment_type': 'CASH',
            'payment_amount': '-500', 'motif': 'EMPRUNT_BOULANGER',
            'is_debt_repayment': True, 'lines': []}, format='json')
        if r.status_code == 201:
            self.assertEqual(Invoice.objects.get(pk=r.data['id']).node_id, self.k1.pk)
        else:
            self.assertIn(r.status_code, (400, 403))
        self.assertFalse(Invoice.objects.filter(node=self.k2).exists())

    def test_versement_sans_commande_n_altere_pas_client_autre_node_via_node_forge(self):
        """Facturier K1 + node=K1 : client de K2 facturable (regle 5.1), mais la facture
        reste sur le noeud du facturier et jamais sur K2."""
        r = cl(self.u['FACTURIER']).post('/api/sales/invoices/', {
            'node': self.k2.pk, 'client': str(self.c2.pk), 'payment_type': 'CASH',
            'payment_amount': '1000', 'is_debt_repayment': True, 'lines': []}, format='json')
        self.assertFalse(Invoice.objects.filter(node=self.k2).exists(), r.content)

    def test_livreur_cannot_create_negative_payment(self):
        """Q-027 / BUG-1050 : le livreur a les memes droits que le facturier, ni plus ni
        moins. Un paiement negatif au motif forge (inconnu) reste refuse pour le
        livreur comme pour le facturier ; les cas legitimes recoivent la meme reponse."""
        def post(role, body):
            return cl(self.u[role]).post('/api/sales/invoices/', {
                'client': str(self.c1.pk), 'payment_type': 'CASH', 'is_debt_repayment': True,
                'lines': [], **body}, format='json')
        forges = ({'payment_amount': '-500', 'motif': 'MOTIF_INVENTE'},)
        for body in forges:
            rf, rl = post('FACTURIER', body), post('LIVREUR', body)
            self.assertEqual(rf.status_code, 400, (body, rf.content))
            self.assertEqual(rl.status_code, rf.status_code, (body, rl.content))
        legit = ({'payment_amount': '-500', 'motif': 'MANQUANT_EQUIPE'}, {'payment_amount': '-500'},
                 {'payment_amount': '500'})
        for body in legit:
            self.assertEqual(post('LIVREUR', body).status_code,
                             post('FACTURIER', body).status_code, body)

    def test_motif_not_visible_across_nodes_and_not_patchable(self):
        inv = cl(self.u['FACTURIER']).post('/api/sales/invoices/', {
            'client': str(self.c1.pk), 'payment_type': 'CASH', 'payment_amount': '-500',
            'motif': 'EMPRUNT_BOULANGER', 'is_debt_repayment': True, 'lines': []}, format='json')
        self.assertEqual(inv.status_code, 201, inv.content)
        iid = inv.data['id']
        # Facturier/Livreur/Gerant K2 : liste vide et detail 404 (pas de fuite du motif)
        for u in (self.u2['FACTURIER'], self.u2['LIVREUR'], self.u2['GERANT']):
            c = cl(u)
            self.assertEqual(c.get(f'/api/sales/invoices/{iid}/').status_code, 404)
            ids = [i['id'] for i in c.get('/api/sales/invoices/').data.get('results', [])]
            self.assertNotIn(iid, ids)
            self.assertEqual(c.get(f'/api/sales/invoices/{iid}/receipt/').status_code, 404)
        # PATCH motif interdit meme au gerant du noeud (liste blanche commission_exempt)
        r = cl(self.u['GERANT']).patch(f'/api/sales/invoices/{iid}/', {'motif': ''}, format='json')
        self.assertEqual(r.status_code, 400)
        # PATCH/DELETE par gerant etranger : 404
        self.assertEqual(cl(self.u2['GERANT']).patch(
            f'/api/sales/invoices/{iid}/', {'commission_exempt': True}, format='json').status_code, 404)
        self.assertEqual(cl(self.u['GERANT']).delete(f'/api/sales/invoices/{iid}/').status_code, 405)
        # Facturier ne peut pas patcher
        self.assertEqual(cl(self.u['FACTURIER']).patch(
            f'/api/sales/invoices/{iid}/', {'commission_exempt': True}, format='json').status_code, 403)

    def test_deliver_cancel_adjust_foreign_invoice(self):
        inv = cl(self.u['FACTURIER']).post('/api/sales/invoices/', {
            'client': str(self.c1.pk), 'payment_type': 'CASH', 'payment_amount': '500',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(inv.status_code, 201, inv.content)
        iid = inv.data['id']
        for u in (self.u2['FACTURIER'], self.u2['LIVREUR'], self.u2['GERANT']):
            c = cl(u)
            self.assertEqual(c.post(f'/api/sales/invoices/{iid}/deliver/', {}, format='json').status_code,
                             404, u.role)
            self.assertEqual(c.post(f'/api/sales/invoices/{iid}/cancel/', {}, format='json').status_code,
                             404, u.role)  # BUG-1050 : le livreur annule comme le facturier
            self.assertEqual(c.post(f'/api/sales/invoices/{iid}/adjust/', {
                'adjustment_sign': 1, 'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]},
                format='json').status_code, 404 if u.role == 'GERANT' else 403, u.role)
        self.assertEqual(Invoice.objects.get(pk=iid).status, Invoice.Status.PENDING)


# --------------------------------------------------------------------------
# 3. Isolation clients (distributions, cotisations)
# --------------------------------------------------------------------------
class ClientsIsolation(Base):
    def test_gerant_k1_cannot_touch_distribution_k2(self):
        g = cl(self.u['GERANT'])
        d2 = f'/api/clients/distributions/{self.dist2.pk}/'
        self.assertEqual(g.get(d2).status_code, 404)
        self.assertEqual(g.patch(d2, {'tarif': '1'}, format='json').status_code, 404)
        self.assertEqual(g.delete(d2).status_code, 404)
        for act in ('refresh_indices', 'auto_populate_lines'):
            self.assertEqual(g.post(d2 + act + '/', {}, format='json').status_code, 404, act)
        ids = [d['id'] for d in g.get('/api/clients/distributions/').data.get('results', [])]
        self.assertEqual(ids, [str(self.dist1.pk)])
        self.dist2.refresh_from_db()
        self.assertEqual(self.dist2.tarif, Dc('900'))

    def test_distribution_create_forged_node_goes_to_own_node(self):
        r = cl(self.u['GERANT']).post('/api/clients/distributions/',
                                      {'node': self.k2.pk, 'year': 2027, 'tarif': '100'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(SocialDistribution.objects.get(pk=r.data['id']).node_id, self.k1.pk)

    def test_distribution_patch_node_cannot_move_to_other_node(self):
        """Un gerant K1 ne doit pas reaffecter sa distribution a K2 (champ node forge)."""
        r = cl(self.u['GERANT']).patch(f'/api/clients/distributions/{self.dist1.pk}/',
                                       {'node': self.k2.pk}, format='json')
        self.dist1.refresh_from_db()
        self.assertEqual(self.dist1.node_id, self.k1.pk, f'status={r.status_code}')

    def test_distribution_patch_node_with_free_year_cannot_move(self):
        """Variante sans collision unique_together (node, year) avec la distribution K2."""
        r = cl(self.u['GERANT']).patch(f'/api/clients/distributions/{self.dist1.pk}/',
                                       {'node': self.k2.pk, 'year': 2030}, format='json')
        self.dist1.refresh_from_db()
        self.assertEqual(self.dist1.node_id, self.k1.pk, f'status={r.status_code}')

    def test_distribution_patch_is_closed_forged_and_year(self):
        g = cl(self.u['GERANT'])
        r = g.patch(f'/api/clients/distributions/{self.dist1.pk}/', {'year': 2099}, format='json')
        self.assertIn(r.status_code, (200, 400))
        self.assertEqual(g.patch(f'/api/clients/distributions/{self.dist1.pk}/',
                                 {'tarif': '-1'}, format='json').status_code, 400)

    def test_distribution_lines_isolation(self):
        g = cl(self.u['GERANT'])
        l2 = f'/api/clients/distribution-lines/{self.line2.pk}/'
        self.assertEqual(g.get(l2).status_code, 404)
        self.assertEqual(g.patch(l2, {'merite': '999'}, format='json').status_code, 404)
        self.assertEqual(g.delete(l2).status_code, 404)
        # creation d'une ligne dans la distribution K2 / avec client K2
        r = g.post('/api/clients/distribution-lines/',
                   {'distribution': str(self.dist2.pk), 'client': str(self.c2.pk)}, format='json')
        self.assertEqual(r.status_code, 400)
        r = g.post('/api/clients/distribution-lines/',
                   {'distribution': str(self.dist1.pk), 'client': str(self.c2.pk)}, format='json')
        self.assertEqual(r.status_code, 400)
        # deplacer une ligne K1 vers distribution K2
        r = g.patch(f'/api/clients/distribution-lines/{self.line1.pk}/',
                    {'distribution': str(self.dist2.pk)}, format='json')
        self.assertEqual(r.status_code, 400)
        self.line1.refresh_from_db()
        self.assertEqual(self.line1.distribution_id, self.dist1.pk)

    def test_refresh_indices_closed_and_no_leak_in_payload(self):
        r = cl(self.u['GERANT']).post(f'/api/clients/distributions/{self.dist1.pk}/refresh_indices/',
                                      {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        txt = str(r.data)
        self.assertNotIn(str(self.c2.pk), txt)
        self.assertNotIn('Bob', txt)

    def test_contribution_isolation_and_forged_node(self):
        g = cl(self.u['GERANT'])
        c2 = f'/api/clients/contributions/{self.contrib2.pk}/'
        self.assertEqual(g.get(c2).status_code, 404)
        self.assertEqual(g.patch(c2, {'is_paid': True}, format='json').status_code, 404)
        self.assertEqual(g.post(c2 + 'toggle_paid/', {}, format='json').status_code, 404)
        self.assertEqual(g.delete(c2).status_code, 404)
        # bulk_create_month sur K2
        r = g.post('/api/clients/contributions/bulk_create_month/',
                   {'node': self.k2.pk, 'month': 6, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(SocialContribution.objects.filter(node=self.k2, month=6).exists())
        # creation avec node=K2 / client K2
        r = g.post('/api/clients/contributions/', {'client': str(self.c2.pk), 'node': self.k2.pk,
                   'month': 7, 'year': 2026, 'amount': '1'}, format='json')
        self.assertIn(r.status_code, (400, 403))
        self.assertFalse(SocialContribution.objects.filter(client=self.c2, month=7).exists())

    def test_contribution_patch_node_cannot_move_to_other_node(self):
        r = cl(self.u['GERANT']).patch(f'/api/clients/contributions/{self.contrib1.pk}/',
                                       {'node': self.k2.pk}, format='json')
        self.contrib1.refresh_from_db()
        self.assertEqual(self.contrib1.node_id, self.k1.pk, f'status={r.status_code}')

    def test_contribution_patch_client_to_foreign_client(self):
        r = cl(self.u['GERANT']).patch(f'/api/clients/contributions/{self.contrib1.pk}/',
                                       {'client': str(self.c2.pk)}, format='json')
        self.contrib1.refresh_from_db()
        self.assertEqual(self.contrib1.client_id, self.c1.pk, f'status={r.status_code}')

    def test_client_cotisation_sociale_forged(self):
        # facturier / livreur ne modifient pas la cotisation ; gerant K1 pas sur client K2
        url1 = f'/api/clients/clients/{self.c1.pk}/'
        for role in ('FACTURIER', 'LIVREUR'):
            r = cl(self.u[role]).patch(url1, {'cotisation_sociale': '0'}, format='json')
            self.assertEqual(r.status_code, 403, role)
        r = cl(self.u['GERANT']).patch(f'/api/clients/clients/{self.c2.pk}/',
                                       {'cotisation_sociale': '0'}, format='json')
        self.assertIn(r.status_code, (403, 404))
        self.c2.refresh_from_db()
        self.assertIsNone(self.c2.cotisation_sociale)
        # gerant ne peut pas deplacer son client sur K2
        r = cl(self.u['GERANT']).patch(url1, {'node': self.k2.pk}, format='json')
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.node_id, self.k1.pk, f'status={r.status_code}')
        # credit_limit par facturier
        self.assertEqual(cl(self.u['FACTURIER']).patch(
            url1, {'credit_limit': '9999999'}, format='json').status_code, 403)


# --------------------------------------------------------------------------
# 4. Core : nodes monthly_social_contribution
# --------------------------------------------------------------------------
class NodesSocial(Base):
    def test_only_direction_writes_monthly_social_contribution(self):
        url = f'/api/core/nodes/{self.k1.pk}/'
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            r = cl(self.u[role]).patch(url, {'monthly_social_contribution': '1'}, format='json')
            self.assertEqual(r.status_code, 403, role)
            r = cl(self.u[role]).put(url, {'code': 'P1', 'name': 'x'}, format='json')
            self.assertEqual(r.status_code, 403, role)
        self.k1.refresh_from_db()
        self.assertNotEqual(self.k1.monthly_social_contribution, Dc('1'))
        for role in DIRECTION_UP:
            r = cl(self.u[role]).patch(url, {'monthly_social_contribution': '2500'}, format='json')
            self.assertEqual(r.status_code, 200, role)
        self.k1.refresh_from_db()
        self.assertEqual(self.k1.monthly_social_contribution, Dc('2500'))

    def test_negative_or_garbage_contribution_rejected(self):
        for v in ('-1', 'abc', '1e99', 'NaN'):
            r = cl(self.u['DIRECTION']).patch(f'/api/core/nodes/{self.k1.pk}/',
                                              {'monthly_social_contribution': v}, format='json')
            self.assertIn(r.status_code, (400,), v)

    def test_node_delete_forbidden_to_non_direction(self):
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).delete(f'/api/core/nodes/{self.k2.pk}/').status_code, 403)

    def test_node_list_exposes_no_secret_field(self):
        """sac_value_fc et monthly_social_contribution sont visibles de tout authentifie
        (necessaire a l'UI) : on verifie qu'aucun champ sensible n'est present."""
        r = cl(self.u['LIVREUR']).get('/api/core/nodes/')
        self.assertEqual(r.status_code, 200)
        rows = r.data.get('results', r.data)
        for row in rows:
            for k in row:
                self.assertNotIn(k, ('password', 'secret', 'token', 'iban'))


# --------------------------------------------------------------------------
# 5. Production : sessions par sacs, objective_fc / progress, daily-closure
# --------------------------------------------------------------------------
class ProductionIsolation(Base):
    def test_gerant_k1_cannot_read_or_write_session_k2(self):
        g = cl(self.u['GERANT'])
        d2 = f'/api/production/sessions/{self.s2.pk}/'
        self.assertEqual(g.get(d2).status_code, 404)
        self.assertEqual(g.patch(d2, {'flour_sacks_used': '9'}, format='json').status_code, 404)
        self.assertEqual(g.delete(d2).status_code, 404)
        self.assertEqual(g.post(d2 + 'close/', {'lines': []}, format='json').status_code, 404)
        self.s2.refresh_from_db()
        self.assertEqual(self.s2.flour_sacks_used, Dc('3'))

    def test_objective_and_progress_not_leaked_across_nodes(self):
        """objective_fc / progress_* ne sortent jamais de la boulangerie (liste,
        filtre ?node=, ordering, search, detail) pour facturier, livreur, gerant."""
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            for q in ('', f'?node={self.k2.pk}', f'?node={self.k2.pk}&date=2026-11-18',
                      '?date_from=2000-01-01&date_to=2100-01-01', '?ordering=-date'):
                r = c.get('/api/production/sessions/' + q)
                self.assertEqual(r.status_code, 200, (role, q))
                rows = r.data.get('results', r.data)
                for row in rows:
                    self.assertEqual(row['node'], self.k1.pk, (role, q))
                    self.assertNotEqual(row['id'], str(self.s2.pk))
            self.assertEqual(c.get(f'/api/production/sessions/{self.s2.pk}/').status_code, 404)

    def test_hq_sees_both_with_objective(self):
        r = cl(self.u['COMPTABLE']).get('/api/production/sessions/')
        rows = r.data.get('results', r.data)
        by = {x['id']: x for x in rows}
        self.assertEqual(by[str(self.s1.pk)]['objective_fc'], 2 * 210000)
        self.assertEqual(by[str(self.s2.pk)]['objective_fc'], 3 * 180000)

    def test_forged_objective_progress_fields_ignored(self):
        g = cl(self.u['GERANT'])
        r = g.patch(f'/api/production/sessions/{self.s1.pk}/', {
            'objective_fc': 1, 'progress_value_fc': 999999, 'progress_pct': '100.00',
            'is_in_progress': False, 'auto_track': False, 'is_closed': True,
            'sac_value_fc_used': '1', 'theoretical_yield': '1', 'total_fc_produced': '999999',
            'closed_at': '2020-01-01T00:00:00Z', 'node_origin': 'P2', 'is_synced': True,
        }, format='json')
        self.assertIn(r.status_code, (200, 400), r.content)
        self.s1.refresh_from_db()
        self.assertFalse(self.s1.is_closed)
        self.assertEqual(self.s1.sac_value_fc_used, 210000)
        self.assertEqual(self.s1.theoretical_yield, 2 * 210000)
        self.assertNotEqual(self.s1.total_fc_produced, 999999)

    def test_create_by_sacks_forged_node_stays_on_own_node(self):
        r = cl(self.u['GERANT']).post('/api/production/sessions/', {
            'flour_sacks_used': '2', 'team': 'B', 'date': TODAY, 'node': self.k2.pk,
            'node_origin': 'P2', 'declared_by': self.u2['GERANT'].pk}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        s = ProductionSession.objects.get(pk=r.data['id'])
        self.assertEqual(s.node_id, self.k1.pk)
        self.assertNotEqual(s.declared_by_id, self.u2['GERANT'].pk)

    def test_patch_node_forged_by_gerant_ignored(self):
        r = cl(self.u['GERANT']).patch(f'/api/production/sessions/{self.s1.pk}/',
                                       {'node': self.k2.pk}, format='json')
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.node_id, self.k1.pk, f'status={r.status_code}')

    def test_facturier_livreur_cannot_declare_or_patch_by_sacks(self):
        for role in ('FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            self.assertEqual(c.post('/api/production/sessions/', {
                'flour_sacks_used': '2', 'team': 'B', 'date': TODAY}, format='json').status_code, 403)
            self.assertEqual(c.patch(f'/api/production/sessions/{self.s1.pk}/',
                                     {'flour_sacks_used': '9'}, format='json').status_code, 403)

    def test_extreme_sacks_values_no_500(self):
        g = cl(self.u['GERANT'])
        for v in ('-1', 'abc', '1e9', 'NaN', 'Infinity', None, True, '1.234'):
            r = g.patch(f'/api/production/sessions/{self.s1.pk}/', {'flour_sacks_used': v}, format='json')
            self.assertLess(r.status_code, 500, v)

    def test_daily_closure_node_scoping(self):
        g = cl(self.u['GERANT'])
        r = g.get(f'/api/production/daily-closure/?node={self.k2.pk}&date=2026-11-18')
        self.assertEqual(r.status_code, 200)
        txt = str(r.data)
        # le rapport retourne K1 (noeud du gerant), jamais K2
        self.assertIn('P1', txt)
        self.assertNotIn('P2', txt)
        r = g.get(f'/api/production/daily-closure/?node=P2&date=2026-11-18')
        self.assertNotIn('Perm K2', str(r.data))
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).get(
                f'/api/production/daily-closure/?node={self.k1.pk}&date=2026-11-18').status_code, 403)

    def test_daily_closure_exposes_no_other_node_session_value(self):
        """Le rapport K1 n'inclut pas l'objectif ni les sacs de K2 (3 sacs x 180000)."""
        r = cl(self.u['GERANT']).get(f'/api/production/daily-closure/?node={self.k2.pk}&date=2026-11-18')
        self.assertNotIn('540000', str(r.data))

    def test_shift_end_status_foreign_node(self):
        r = cl(self.u['FACTURIER']).get(
            f'/api/production/sessions/shift-end-status/?node={self.k2.pk}')
        if r.status_code == 200:
            self.assertNotIn('P2', str(r.data))
        else:
            self.assertIn(r.status_code, (400, 403, 404))

    def test_close_foreign_session_by_forged_lines_no_effect(self):
        s = self.sess(self.k1)
        r = cl(self.u2['GERANT']).post(f'/api/production/sessions/{s.pk}/close/',
                                       {'lines': []}, format='json')
        self.assertEqual(r.status_code, 404)
        s.refresh_from_db()
        self.assertFalse(s.is_closed)


# --------------------------------------------------------------------------
# 6. Elevation par champs forges
# --------------------------------------------------------------------------
class Escalation(Base):
    def _assert_unchanged(self, user, **orig):
        user.refresh_from_db()
        for k, v in orig.items():
            self.assertEqual(getattr(user, k), v, k)

    def test_self_patch_forged_privilege_fields(self):
        forged = [
            {'role': 'ADMIN'}, {'node': self.k2.pk}, {'is_superuser': True}, {'is_staff': True},
            {'is_active': True, 'role': 'DIRECTION'}, {'can_access_all_nodes': True},
            {'is_headquarters': True}, {'groups': [1]}, {'user_permissions': [1]},
        ]
        for role in ROLES:
            u = self.u[role]
            orig = dict(role=u.role, node_id=u.node_id, is_superuser=False, is_staff=False)
            for body in forged:
                r = cl(u).patch(f'/api/core/users/{u.pk}/', body, format='json')
                self.assertIn(r.status_code, (200, 400, 403, 404), (role, body, r.status_code))
                if role not in DIRECTION_UP:
                    self.assertEqual(r.status_code, 403, (role, body))
                self._assert_unchanged(u, **orig)

    def test_non_admin_cannot_create_privileged_user(self):
        for role in ('COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'):
            for body in ({'role': 'ADMIN'}, {'is_superuser': True}, {'is_staff': True}):
                r = cl(self.u[role]).post('/api/core/users/', {
                    'username': f'evil_{role}_{len(body)}', 'password': 'Xx-pass-123456', 'role': 'ADMIN',
                    'first_name': 'a', 'last_name': 'b', **body}, format='json')
                self.assertEqual(r.status_code, 403, (role, body))
        self.assertFalse(User.objects.filter(username__startswith='evil_').exists())

    def test_direction_cannot_forge_superuser_or_staff_on_creation(self):
        r = cl(self.u['DIRECTION']).post('/api/core/users/', {
            'username': 'evil_dir', 'password': 'Xx-pass-123456', 'role': 'FACTURIER',
            'node': self.k1.pk, 'first_name': 'a', 'last_name': 'b',
            'is_superuser': True, 'is_staff': True}, format='json')
        if r.status_code == 201:
            n = User.objects.get(username='evil_dir')
            self.assertFalse(n.is_superuser)
            self.assertFalse(n.is_staff)

    def test_direction_cannot_create_admin(self):
        r = cl(self.u['DIRECTION']).post('/api/core/users/', {
            'username': 'evil_adm', 'password': 'Xx-pass-123456', 'role': 'ADMIN',
            'first_name': 'a', 'last_name': 'b'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_direction_cannot_patch_admin(self):
        for body in ({'role': 'FACTURIER'}, {'is_active': False}, {'first_name': 'x'}):
            r = cl(self.u['DIRECTION']).patch(f'/api/core/users/{self.u["ADMIN"].pk}/', body, format='json')
            self.assertEqual(r.status_code, 403, body)

    def test_gerant_cannot_forge_invoice_fields(self):
        """Champs forges sur facture : facturier, status, node, livreur, motif invalide."""
        inv = cl(self.u['FACTURIER']).post('/api/sales/invoices/', {
            'client': str(self.c1.pk), 'payment_type': 'CASH', 'payment_amount': '0',
            'lines': [{'bread_price': self.bp.pk, 'quantity': 1}],
            'facturier': self.u['ADMIN'].pk, 'status': 'DELIVERED', 'node': self.k2.pk,
            'is_staff': True, 'role': 'ADMIN', 'debt_after': '-999'}, format='json')
        self.assertEqual(inv.status_code, 201, inv.content)
        i = Invoice.objects.get(pk=inv.data['id'])
        self.assertEqual(i.facturier_id, self.u['FACTURIER'].pk)
        self.assertEqual(i.status, Invoice.Status.PENDING)
        self.assertEqual(i.node_id, self.k1.pk)
        r = cl(self.u['FACTURIER']).post('/api/sales/invoices/', {
            'client': str(self.c1.pk), 'payment_type': 'CASH', 'payment_amount': '-5',
            'motif': '<script>', 'is_debt_repayment': True, 'lines': []}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_activity_logs_and_config_closed_to_low_roles(self):
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = cl(self.u[role])
            self.assertEqual(c.get('/api/core/activities/').status_code, 403, role)
            self.assertEqual(c.patch('/api/core/config/', {'best_client_threshold': 1}, format='json').status_code,
                             403, role)
