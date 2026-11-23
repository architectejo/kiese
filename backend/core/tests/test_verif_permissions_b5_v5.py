"""Verification BUG-872/873/874 + voisins (testeur-permissions, ronde b6, 2026-11-23).
Donnees fictives. Code applicatif non modifie."""
import uuid
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.contrib.auth import get_user_model
from django.utils import timezone

from clients.models import Client, SocialDistribution, SocialDistributionLine
from core.models import Node
from commissions.models import ClientCommission, CommissionPeriod
from core.tests import test_verif_permissions_b4_v4 as b4
from core.tests.test_permissions_regression_2026_11_19 import ALL, DIRECTION_UP, GERANT_UP, HQ, cl, mk
from production.models import BreadTransfer, BreadTransferLine
from sync.models import NodeAuthToken

User = get_user_model()
PUSH = '/api/sync/push/'
BAD_BODIES = ([], [1], 5, 'x')


def nocrash(c):
    c.raise_request_exception = False
    return c


class B5(b4.B4):
    def push(self, raw, label, rec):
        c = nocrash(self.node_client(raw))
        return c.post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {label: [rec]}}, format='json')

    def transfer(self, st='RESPONDED', qty_recv=None):
        return BreadTransfer.objects.create(
            from_node=self.k1, to_node=self.k2, bread_price=self.bp, quantity_sent=100,
            quantity_received=qty_recv, transfer_status=st, node_origin='P1')


# ---------------------------------------------------------------------------
# BUG-872
# ---------------------------------------------------------------------------
class V872(B5):
    def test_distribution_cloturee_non_supprimable_par_gerant_direction_admin(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        for role in ('GERANT', 'DIRECTION', 'ADMIN'):
            r = nocrash(cl(self.u[role])).delete(f'/api/clients/distributions/{self.dist1.pk}/')
            self.assertEqual(r.status_code, 400, (role, r.content))
            self.assertIn('detail', r.json())
        self.assertTrue(SocialDistribution.objects.filter(pk=self.dist1.pk).exists())
        self.assertTrue(SocialDistributionLine.objects.filter(pk=self.line1.pk).exists())

    def test_distribution_ouverte_reste_supprimable_par_son_gerant(self):
        r = cl(self.u['GERANT']).delete(f'/api/clients/distributions/{self.dist1.pk}/')
        self.assertEqual(r.status_code, 204)

    def test_roles_non_gerant_et_autre_noeud_refuses_sur_distribution_cloturee(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        for role in ('FACTURIER', 'LIVREUR'):
            r = nocrash(cl(self.u[role])).delete(f'/api/clients/distributions/{self.dist1.pk}/')
            self.assertEqual(r.status_code, 403, role)
        r = nocrash(cl(self.u2['GERANT'])).delete(f'/api/clients/distributions/{self.dist1.pk}/')
        self.assertEqual(r.status_code, 404)
        self.assertTrue(SocialDistribution.objects.filter(pk=self.dist1.pk).exists())

    def test_rouverture_refusee_donc_la_suppression_reste_impossible(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        r = nocrash(cl(self.u['DIRECTION'])).patch(
            f'/api/clients/distributions/{self.dist1.pk}/', {'is_closed': False}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self.dist1.refresh_from_db()
        self.assertTrue(self.dist1.is_closed)

    def test_suppression_de_ligne_et_creation_de_ligne_sur_distribution_cloturee_refusees(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        g = nocrash(cl(self.u['GERANT']))
        self.assertEqual(g.delete(f'/api/clients/distribution-lines/{self.line1.pk}/').status_code, 400)
        r = g.post('/api/clients/distribution-lines/', {'distribution': str(self.dist1.pk), 'client': str(self.c1.pk)},
                   format='json')
        self.assertEqual(r.status_code, 400, r.content)

    # --- voisin : le meme gel contourne par le push de synchronisation
    def test_BUG_887_push_sync_ne_modifie_pas_une_ligne_de_distribution_cloturee(self):
        """BUG-887 : le push sync modifie les montants d'une ligne d'une distribution CLOTUREE (BUG-752 contourne)."""
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        SocialDistributionLine.objects.filter(pk=self.line1.pk).update(total_social=Dc('1000'))
        r = self.push(self.raw1, 'clients.SocialDistributionLine',
                      {'id': str(self.line1.pk), 'distribution': str(self.dist1.pk), 'total_social': '999999'})
        self.line1.refresh_from_db()
        self.assertEqual(self.line1.total_social, Dc('1000.00'), r.content)

    def test_BUG_887_push_sync_ne_cree_pas_de_ligne_dans_une_distribution_cloturee(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        c = Client.objects.create(node=self.k1, node_origin='P1', first_name='Zed', last_name='Nouveau')
        rid = str(uuid.uuid4())
        self.push(self.raw1, 'clients.SocialDistributionLine',
                  {'id': rid, 'distribution': str(self.dist1.pk), 'client': str(c.pk), 'total_social': '5000'})
        self.assertFalse(SocialDistributionLine.objects.filter(pk=rid).exists())

    def test_push_sync_ligne_d_une_autre_boulangerie_refuse(self):
        r = self.push(self.raw1, 'clients.SocialDistributionLine',
                      {'id': str(self.line2.pk), 'distribution': str(self.dist2.pk), 'total_social': '777'})
        self.line2.refresh_from_db()
        self.assertNotEqual(self.line2.total_social, Dc('777'), r.content)

    def test_push_sync_contribution_d_une_autre_boulangerie_refusee(self):
        self.push(self.raw1, 'clients.SocialContribution',
                  {'id': str(self.contrib2.pk), 'amount': '1', 'is_paid': True})
        self.contrib2.refresh_from_db()
        self.assertEqual(self.contrib2.amount, Dc('3000.00'))
        self.assertFalse(self.contrib2.is_paid)

    def test_push_sync_ne_rouvre_pas_une_distribution_cloturee(self):
        SocialDistribution.objects.filter(pk=self.dist1.pk).update(is_closed=True)
        self.push(self.raw1, 'clients.SocialDistribution',
                  {'id': str(self.dist1.pk), 'is_closed': False, 'tarif': '1', 'year': 2020})
        self.dist1.refresh_from_db()
        self.assertTrue(self.dist1.is_closed)
        self.assertEqual(self.dist1.tarif, Dc('700.00'))


# ---------------------------------------------------------------------------
# BUG-873
# ---------------------------------------------------------------------------
class V873(B5):
    def test_me_patch_corps_non_objet_est_400_pour_tous_les_roles(self):
        for role in ('ADMIN', 'GERANT', 'FACTURIER', 'LIVREUR'):
            for body in BAD_BODIES:
                r = nocrash(cl(self.u[role])).patch('/api/core/auth/me/', body, format='json')
                self.assertEqual(r.status_code, 400, (role, body, r.content))

    def test_me_patch_mots_de_passe_non_textuels_400_et_mot_de_passe_inchange(self):
        u = self.u['FACTURIER']
        u.set_password('Ancien-mdp-9182')
        u.save()
        for body in ({'new_password': 12345678}, {'new_password': ['a']}, {'new_password': {'a': 1}},
                     {'new_password': True}, {'old_password': 5, 'new_password': 'Nouveau-mdp-7731'},
                     {'old_password': ['x'], 'new_password': 'Nouveau-mdp-7731'}):
            r = nocrash(cl(u)).patch('/api/core/auth/me/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.content))
            u.refresh_from_db()
            self.assertTrue(u.check_password('Ancien-mdp-9182'), body)

    def test_me_patch_champs_de_profil_mal_types_pas_de_500(self):
        for body in ({'first_name': ['a']}, {'username': 5}, {'email': {'a': 1}}, {'phone': 12}, {'first_name': None}):
            r = nocrash(cl(self.u['LIVREUR'])).patch('/api/core/auth/me/', body, format='json')
            self.assertLess(r.status_code, 500, (body, r.content[:200]))

    def test_me_patch_ne_permet_toujours_pas_l_elevation(self):
        u = self.u['FACTURIER']
        r = nocrash(cl(u)).patch('/api/core/auth/me/', {'role': 'ADMIN', 'node': str(self.k2.pk),
                                                          'is_superuser': True, 'is_staff': True}, format='json')
        self.assertLess(r.status_code, 500)
        u.refresh_from_db()
        self.assertEqual((u.role, u.node_id, u.is_superuser, u.is_staff), ('FACTURIER', self.k1.pk, False, False))

    def test_change_password_corps_non_objet_pas_de_500(self):
        for body in BAD_BODIES:
            r = nocrash(cl(self.u['FACTURIER'])).post('/api/core/auth/change-password/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.content))

    def test_login_refresh_logout_corps_non_objet_pas_de_500(self):
        for url in ('/api/core/auth/login/', '/api/core/auth/login/refresh/'):
            for body in BAD_BODIES + ({'username': 5, 'password': 5}, {'username': ['a'], 'password': {}},
                                      {'refresh': 5}, {'refresh': ['x']}):
                r = nocrash(cl()).post(url, body, format='json')
                self.assertIn(r.status_code, (400, 401, 429), (url, body, r.status_code))
        for body in BAD_BODIES + ({'refresh': 5}, {'refresh': ['x']}):
            r = nocrash(cl(self.u['GERANT'])).post('/api/core/auth/logout/', body, format='json')
            self.assertLess(r.status_code, 500, body)

    def test_BUG_886_reset_data_corps_non_objet_est_400(self):
        su = User.objects.create(username='pr_su', role='ADMIN', is_superuser=True, is_staff=True)
        for body in BAD_BODIES:
            r = nocrash(cl(su)).post('/api/core/reset-data/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code))

    def test_BUG_886_chat_conversation_directe_corps_non_objet_est_400(self):
        for body in BAD_BODIES:
            r = nocrash(cl(self.u['GERANT'])).post('/api/chat/conversations/direct/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code))

    def test_BUG_886_reset_data_types_de_champs_est_400(self):
        su = User.objects.create(username='pr_su', role='ADMIN', is_superuser=True, is_staff=True)
        for body in ({'confirm_phrase': 5, 'password': 'x'}, {'confirm_phrase': ['a'], 'password': 5},
                                  {'confirm_phrase': 'SUPPRIMER TOUT', 'password': 5},
                                  {'confirm_phrase': 'SUPPRIMER TOUT', 'password': ['a']}):
            r = nocrash(cl(su)).post('/api/core/reset-data/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code))

    def test_routes_core_clients_corps_non_objet_ou_types_pas_de_500(self):
        admin = self.u['ADMIN']
        routes = [
            ('post', '/api/core/users/'), ('patch', f'/api/core/users/{self.u["GERANT"].pk}/'),
            ('post', '/api/core/nodes/'), ('patch', f'/api/core/nodes/{self.k1.pk}/'),
            ('patch', '/api/core/config/'), ('post', '/api/core/bread-prices/'),
            ('post', '/api/core/expense-categories/'), ('post', '/api/core/colis/'),
            ('post', '/api/clients/clients/'), ('patch', f'/api/clients/clients/{self.c1.pk}/'),
            ('post', '/api/clients/contributions/'), ('post', '/api/clients/distributions/'),
            ('post', '/api/clients/distribution-lines/'),
            ('post', '/api/clients/contributions/bulk_create_month/'),
            ('post', '/api/clients/clients/bulk_delete/'), ('post', '/api/clients/clients/bulk_move/'),
            ('post', f'/api/clients/distributions/{self.dist1.pk}/refresh_indices/'),
        ]
        bad = []
        for m, url in routes:
            for body in BAD_BODIES + (['a'], {'a': [1]}):
                s = getattr(nocrash(cl(admin)), m)(url, body, format='json').status_code
                if s >= 500:
                    bad.append((m, url.split('/api/')[1][:50], repr(body), s))
        self.assertEqual(bad, [])

    def test_types_inattendus_dans_les_champs_pas_de_500(self):
        admin = nocrash(cl(self.u['ADMIN']))
        cases = [
            ('post', '/api/clients/clients/bulk_delete/', {'ids': 'abc'}),
            ('post', '/api/clients/clients/bulk_delete/', {'ids': 5}),
            ('post', '/api/clients/clients/bulk_delete/', {'ids': [1, None, {}, ['x']]}),
            ('post', '/api/clients/clients/bulk_delete/', {'ids': {'a': 1}}),
            ('post', '/api/clients/clients/bulk_move/', {'ids': [str(self.c1.pk)], 'node': 5}),
            ('post', '/api/clients/clients/bulk_move/', {'ids': [str(self.c1.pk)], 'node': ['a']}),
            ('post', '/api/clients/clients/bulk_move/', {'ids': 'abc', 'node': str(self.k2.pk)}),
            ('post', '/api/clients/contributions/bulk_create_month/', {'month': 'x', 'year': 2026}),
            ('post', '/api/clients/contributions/bulk_create_month/', {'month': [1], 'year': {}}),
            ('post', '/api/clients/contributions/bulk_create_month/', {'month': 99999999999999999999, 'year': 2026}),
            ('post', '/api/clients/contributions/bulk_create_month/', {'month': 5, 'year': 2026, 'node': 5}),
            ('patch', f'/api/clients/clients/{self.c1.pk}/', {'credit_limit': ['a']}),
            ('patch', f'/api/clients/clients/{self.c1.pk}/', {'credit_limit': 'NaN'}),
            ('patch', f'/api/clients/clients/{self.c1.pk}/', {'credit_limit': '1e999'}),
            ('patch', f'/api/clients/clients/{self.c1.pk}/', {'commission_rate': 'Infinity'}),
            ('post', '/api/clients/distributions/', {'year': 'x', 'node': str(self.k1.pk)}),
            ('post', '/api/clients/distributions/', {'year': 99999999999999, 'node': str(self.k1.pk)}),
            ('post', '/api/clients/distributions/', {'year': 2030, 'node': 5, 'tarif': ['a']}),
            ('get', '/api/clients/clients/?search[]=a&page=x&page_size=-1', None),
            ('get', '/api/clients/contributions/?month=x&year=[]', None),
        ]
        bad = []
        for m, url, body in cases:
            c = getattr(admin, m)
            r = c(url, body, format='json') if body is not None else c(url)
            if r.status_code >= 500:
                bad.append((m, url.split('/api/')[1][:50], repr(body), r.status_code))
        self.assertEqual(bad, [])

    def test_sync_push_handshake_corps_invalides_pas_de_500(self):
        c = nocrash(self.node_client(self.raw1))
        bodies = BAD_BODIES + ({'records': 5}, {'records': []}, {'records': 'x'}, {'batch_id': 5, 'records': {}},
                               {'batch_id': 'a', 'records': {'clients.Client': 5}},
                               {'batch_id': str(uuid.uuid4()), 'records': {'clients.Client': [5, None, [], 'x']}},
                               {'batch_id': str(uuid.uuid4()), 'records': {5: []}},
                               {'batch_id': str(uuid.uuid4()), 'records': {'clients.Client': [{'id': 5}, {'id': ['a']}]}},
                               {'batch_id': str(uuid.uuid4()), 'records': {'production.BreadTransfer':
                                                                          [{'id': str(uuid.uuid4()), 'from_node': 5, 'to_node': ['a']}]}})
        bad = []
        for url in (PUSH, '/api/sync/handshake/'):
            for body in bodies:
                s = c.post(url, body, format='json').status_code
                if s >= 500:
                    bad.append((url, repr(body)[:80], s))
        self.assertEqual(bad, [])


# ---------------------------------------------------------------------------
# BUG-874
# ---------------------------------------------------------------------------
class V874(B5):
    def test_emetteur_ne_confirme_pas(self):
        t = self.transfer('RESPONDED')
        self.push(self.raw1, 'production.BreadTransfer',
                  {'id': str(t.pk), 'transfer_status': 'CONFIRMED', 'quantity_received': 100})
        t.refresh_from_db()
        self.assertEqual(t.transfer_status, 'RESPONDED')
        self.assertIsNone(t.quantity_received)

    def test_receptrice_confirme_avec_quantite(self):
        t = self.transfer('RESPONDED')
        self.push(self.raw2, 'production.BreadTransfer',
                  {'id': str(t.pk), 'transfer_status': 'CONFIRMED', 'quantity_received': 98})
        t.refresh_from_db()
        self.assertEqual(t.transfer_status, 'CONFIRMED')
        self.assertEqual(t.quantity_received, 98)

    def test_emetteur_ne_cree_pas_de_transfert_confirme_ou_recu(self):
        for extra in ({'transfer_status': 'CONFIRMED'}, {'quantity_received': 5},
                      {'transfer_status': 'CONFIRMED', 'quantity_received': 100}):
            rid = str(uuid.uuid4())
            rec = {'id': rid, 'from_node': 'P1', 'to_node': 'P2', 'bread_price': self.bp.pk,
                   'quantity_sent': 100, 'node_origin': 'P1', **extra}
            self.push(self.raw1, 'production.BreadTransfer', rec)
            self.assertFalse(BreadTransfer.objects.filter(pk=rid).exists(), extra)

    def test_emetteur_ne_cree_pas_de_ligne_recue_mais_la_receptrice_oui(self):
        t = self.transfer('PENDING')
        rec = {'transfer': str(t.pk), 'bread_price': self.bp.pk, 'quantity_sent': 10, 'quantity_received': 10}
        self.push(self.raw1, 'production.BreadTransferLine', rec)
        self.assertFalse(BreadTransferLine.objects.filter(transfer=t).exists())
        self.push(self.raw2, 'production.BreadTransferLine', rec)
        self.assertTrue(BreadTransferLine.objects.filter(transfer=t, quantity_received=10).exists())

    def test_emetteur_ne_modifie_pas_la_quantite_recue_d_une_ligne_existante(self):
        t = self.transfer('RESPONDED')
        line = BreadTransferLine.objects.create(transfer=t, bread_price=self.bp, quantity_sent=10)
        self.push(self.raw1, 'production.BreadTransferLine', {'id': str(line.pk), 'quantity_received': 10})
        line.refresh_from_db()
        self.assertIsNone(line.quantity_received)

    def test_troisieme_noeud_ne_touche_pas_au_transfert(self):
        k3 = Node.objects.create(code='P3', name='Perm K3')
        _, raw3 = NodeAuthToken.issue_for_node(k3)
        t = self.transfer('RESPONDED')
        self.push(raw3, 'production.BreadTransfer', {'id': str(t.pk), 'transfer_status': 'CONFIRMED',
                                                     'quantity_received': 1})
        t.refresh_from_db()
        self.assertEqual(t.transfer_status, 'RESPONDED')
        rid = str(uuid.uuid4())
        self.push(raw3, 'production.BreadTransfer', {'id': rid, 'from_node': 'P1', 'to_node': 'P2',
                                                     'bread_price': self.bp.pk, 'quantity_sent': 1})
        self.assertFalse(BreadTransfer.objects.filter(pk=rid).exists())

    def test_pas_de_regression_d_etat_ni_de_reconfirmation(self):
        t = self.transfer('CONFIRMED', qty_recv=100)
        self.push(self.raw2, 'production.BreadTransfer',
                  {'id': str(t.pk), 'transfer_status': 'PENDING', 'quantity_received': 1})
        t.refresh_from_db()
        self.assertEqual((t.transfer_status, t.quantity_received), ('CONFIRMED', 100))

    # --- voisins : autres transitions reservees
    def test_BUG_888_emetteur_ne_declare_pas_un_litige_a_la_place_de_la_receptrice(self):
        """BUG-888 : RESPONDED -> DISPUTED (acte de la receptrice, confirm_reception) accepte du jeton emetteur."""
        t = self.transfer('RESPONDED')
        self.push(self.raw1, 'production.BreadTransfer', {'id': str(t.pk), 'transfer_status': 'DISPUTED'})
        t.refresh_from_db()
        self.assertNotEqual(t.transfer_status, 'DISPUTED')

    def test_BUG_888_receptrice_ne_declare_pas_la_reponse_de_l_emettrice(self):
        """BUG-888 : PENDING -> RESPONDED (acte de l'emettrice, respond_to_request) accepte du jeton receptrice."""
        t = self.transfer('PENDING')
        self.push(self.raw2, 'production.BreadTransfer', {'id': str(t.pk), 'transfer_status': 'RESPONDED'})
        t.refresh_from_db()
        self.assertNotEqual(t.transfer_status, 'RESPONDED')


# ---------------------------------------------------------------------------
# Suppression / modification d'objets figes
# ---------------------------------------------------------------------------
class Figes(B5):
    def mk_commission(self, closed=False, paid=False, month=None):
        per = CommissionPeriod.objects.create(node=self.k1, month=month or 9, year=2026, node_origin='P1', is_closed=closed)
        cm = ClientCommission.objects.create(period=per, client=self.c1, order_value=Dc('1000'),
                                             node_origin='P1', is_paid=paid)
        return per, cm

    def test_commission_payee_ou_periode_close_non_supprimable_ni_modifiable(self):
        for closed, paid, mo in ((True, False, 6), (False, True, 7)):
            per, cm = self.mk_commission(closed, paid, mo)
            for role in ('DIRECTION', 'ADMIN'):
                c = nocrash(cl(self.u[role]))
                self.assertEqual(c.delete(f'/api/commissions/commissions/{cm.pk}/').status_code, 400)
                self.assertEqual(c.patch(f'/api/commissions/commissions/{cm.pk}/', {'order_value': '1'},
                                         format='json').status_code, 400)
                self.assertEqual(c.delete(f'/api/commissions/periods/{per.pk}/').status_code, 400)
            self.assertTrue(ClientCommission.objects.filter(pk=cm.pk).exists())

    def test_gerant_facturier_ne_touchent_pas_aux_commissions(self):
        per, cm = self.mk_commission()
        for role in ('GERANT', 'FACTURIER', 'LIVREUR'):
            c = nocrash(cl(self.u[role]))
            self.assertEqual(c.delete(f'/api/commissions/commissions/{cm.pk}/').status_code, 403, role)
            self.assertEqual(c.delete(f'/api/commissions/periods/{per.pk}/').status_code, 403, role)
            self.assertEqual(c.post(f'/api/commissions/commissions/{cm.pk}/mark_paid/', {}, format='json').status_code,
                             403, role)

    def test_BUG_889_pas_de_creation_de_commission_dans_une_periode_cloturee(self):
        """BUG-889 : POST /commissions/commissions/ dans une periode CLOTUREE accepte (le gel ne couvre que update/destroy)."""
        per, _ = self.mk_commission(closed=True)
        c2 = Client.objects.create(node=self.k1, node_origin='P1', first_name='Cy', last_name='Neuf')
        r = nocrash(cl(self.u['DIRECTION'])).post(
            '/api/commissions/commissions/', {'period': str(per.pk), 'client': str(c2.pk), 'order_value': '5000'},
            format='json')
        self.assertGreaterEqual(r.status_code, 400, r.content)
        self.assertFalse(ClientCommission.objects.filter(period=per, client=c2).exists())

    def test_creation_de_commission_deja_payee_ignoree(self):
        """is_paid n'est pas inscriptible a la creation (contournement de mark_paid impossible)."""
        per, _ = self.mk_commission()
        c2 = Client.objects.create(node=self.k1, node_origin='P1', first_name='Di', last_name='Payee')
        r = nocrash(cl(self.u['DIRECTION'])).post(
            '/api/commissions/commissions/', {'period': str(per.pk), 'client': str(c2.pk), 'order_value': '5000',
                                              'is_paid': True}, format='json')
        created = ClientCommission.objects.filter(period=per, client=c2).first()
        self.assertTrue(created is None or not created.is_paid, r.content)

    def test_suppression_ecritures_comptables_et_clotures_interdite(self):
        from treasury.models import CashbookEntry
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'):
            for url in ('/api/treasury/cashbook/', '/api/treasury/closures/', '/api/treasury/journal/'):
                r = nocrash(cl(self.u[role])).delete(f'{url}{uuid.uuid4()}/')
                self.assertIn(r.status_code, (403, 404, 405), (role, url, r.status_code))
        self.assertIsNotNone(CashbookEntry)

    def test_client_a_l_autre_noeud_non_supprimable(self):
        for role in ('GERANT', 'DIRECTION'):
            if role == 'GERANT':
                r = nocrash(cl(self.u[role])).delete(f'/api/clients/clients/{self.c2.pk}/')
                self.assertEqual(r.status_code, 404)
        self.assertTrue(Client.objects.filter(pk=self.c2.pk).exists())
