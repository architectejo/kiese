"""Clients / Commissions / Sync / Permissions - ronde b5 (testeur Clients/Commissions, 2026-11-23).

Verification independante de BUG-751/752/753/761/762/785-789 et recherche de
nouveaux defauts. Donnees FICTIVES. Code applicatif non modifie.
"""
import uuid
from decimal import Decimal as D
from unittest import expectedFailure

from clients.models import Client, SocialContribution, SocialDistribution, SocialDistributionLine
from clients.tests.test_clients_v2 import CL, CONTRIB, DISTRIB, LINES, Base, api
from commissions.models import ClientCommission, CommissionPeriod
from core.models import Node
from core.testing import make_bread_price, make_client, make_node, make_user


# ------------------------------------------------------------------ 751/752/753/762 (verifs)
class Verif751_752_753(Base):
    def setUp(self):
        super().setUp()
        self.c1 = self.mk(self.k1, 'A', 'A')

    def _distrib(self, tarif='700'):
        r = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2026, 'tarif': tarif}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def test_751_762_corps_non_objet_400_sur_toutes_les_actions_clients(self):
        for url in (CL + 'bulk_delete/', CL + 'bulk_move/', CONTRIB + 'bulk_create_month/'):
            for body in ([], [1], 5, '"x"'):
                r = api(self.direction).post(url, body, format='json')
                self.assertEqual(r.status_code, 400, (url, body, r.status_code))
                self.assertIn('detail', r.data)

    def test_752_ligne_d_une_distribution_close_immuable_creation_modif_suppression(self):
        d = self._distrib()
        r = api(self.g1).post(LINES, {'distribution': d, 'client': str(self.c1.id), 'merite': '10'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        lid = r.data['id']
        api(self.direction).patch(f'{DISTRIB}{d}/', {'is_closed': True}, format='json')
        c2 = self.mk(self.k1, 'B', 'B')
        self.assertEqual(api(self.g1).post(LINES, {'distribution': d, 'client': str(c2.id)}, format='json').status_code, 400)
        self.assertEqual(api(self.g1).patch(f'{LINES}{lid}/', {'merite': '999'}, format='json').status_code, 400)
        self.assertEqual(api(self.direction).patch(f'{LINES}{lid}/', {'merite': '999'}, format='json').status_code, 400)
        self.assertEqual(api(self.g1).delete(f'{LINES}{lid}/').status_code, 400)
        self.assertEqual(SocialDistributionLine.objects.get(pk=lid).merite, D('10.00'))

    def test_752_deplacer_une_ligne_ouverte_vers_une_distribution_close_refuse(self):
        d1 = self._distrib()
        d2 = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2025, 'tarif': '100'}, format='json').data['id']
        lid = api(self.g1).post(LINES, {'distribution': d1, 'client': str(self.c1.id)}, format='json').data['id']
        api(self.direction).patch(f'{DISTRIB}{d2}/', {'is_closed': True}, format='json')
        r = api(self.g1).patch(f'{LINES}{lid}/', {'distribution': d2}, format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def _deux_cotisations(self):
        for m in (1, 2):
            SocialContribution.objects.create(client=self.c1, node=self.k1, month=m, year=2026,
                                              amount=D('99999999.99'), is_paid=True)

    def test_753_refresh_indices_hors_colonne_400_sans_ecriture(self):
        d = self._distrib()
        lid = api(self.g1).post(LINES, {'distribution': d, 'client': str(self.c1.id), 'merite': '5'}, format='json').data['id']
        self._deux_cotisations()
        r = api(self.direction).post(f'{DISTRIB}{d}/refresh_indices/', format='json')
        self.assertEqual(r.status_code, 400, r.status_code)
        self.assertTrue(r.data['detail'])
        line = SocialDistributionLine.objects.get(pk=lid)
        self.assertEqual((line.indice, line.total_social), (0, D('0.00')))

    def test_753_auto_populate_hors_colonne_400_sans_ecriture(self):
        d = self._distrib()
        Client.objects.filter(pk=self.c1.pk).update(cotisation_sociale=D('2000'))
        self._deux_cotisations()
        r = api(self.direction).post(f'{DISTRIB}{d}/auto_populate_lines/', format='json')
        self.assertEqual(r.status_code, 400, r.status_code)
        self.assertEqual(SocialDistributionLine.objects.filter(distribution=d).count(), 0)


# ------------------------------------------------------------------ nouveaux defauts caisse sociale
class CaisseSocialeV5(Base):
    def setUp(self):
        super().setUp()
        self.c1 = self.mk(self.k1, 'A', 'A')
        self.c3 = self.mk(self.k3, 'Z', 'Z')

    def _distrib(self, node, year=2026):
        r = api(self.direction).post(DISTRIB, {'node': node.pk, 'year': year, 'tarif': '700'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    # (BUG-87x corrigé)
    def test_distribution_close_non_supprimable_par_un_gerant(self):
        """Une distribution close est figee (BUG-295/313/752) : sa suppression efface les montants distribues."""
        d = self._distrib(self.k1)
        api(self.g1).post(LINES, {'distribution': d, 'client': str(self.c1.id), 'merite': '10'}, format='json')
        api(self.direction).patch(f'{DISTRIB}{d}/', {'is_closed': True}, format='json')
        r = api(self.g1).delete(f'{DISTRIB}{d}/')
        self.assertEqual(r.status_code, 400, r.status_code)
        self.assertTrue(SocialDistribution.objects.filter(pk=d).exists())
        self.assertEqual(SocialDistributionLine.objects.filter(distribution=d).count(), 1)

    def test_gerant_k1_ne_deplace_pas_une_ligne_vers_la_distribution_de_k3(self):
        d1, d3 = self._distrib(self.k1), self._distrib(self.k3)
        lid = api(self.g1).post(LINES, {'distribution': d1, 'client': str(self.c1.id)}, format='json').data['id']
        r = api(self.g1).patch(f'{LINES}{lid}/', {'distribution': d3}, format='json')
        self.assertIn(r.status_code, (400, 403, 404), r.status_code)
        self.assertEqual(str(SocialDistributionLine.objects.get(pk=lid).distribution_id), d1)

    def test_gerant_k1_ne_cree_pas_de_ligne_dans_la_distribution_de_k3(self):
        d3 = self._distrib(self.k3)
        r = api(self.g1).post(LINES, {'distribution': d3, 'client': str(self.c3.id)}, format='json')
        self.assertIn(r.status_code, (400, 403, 404), r.status_code)
        self.assertEqual(SocialDistributionLine.objects.filter(distribution=d3).count(), 0)


# ------------------------------------------------------------------ commissions : champs libres
from commissions.tests.test_commissions_v2 import COMM, Base as CBase  # noqa: E402
from commissions.tests.test_commissions_v2 import api as capi  # noqa: E402


class CommissionChampsLibres(CBase):
    def setUp(self):
        super().setUp()
        c = make_client(self.n1)
        self.invoice(self.n1, c, 100)
        self.row_ = self.row(self.generate(self.n1), c)

    def test_mark_paid_paid_by_non_texte_ou_trop_long_n_est_pas_un_500(self):
        for value in ([1], {'a': 1}, 'x' * 500):
            ClientCommission.objects.filter(pk=self.row_.pk).update(is_paid=False)
            r = capi(self.direction).post(f'{COMM}{self.row_.id}/mark_paid/', {'paid_by': value}, format='json')
            self.assertLess(r.status_code, 500, (repr(value)[:20], r.status_code))

    def test_set_manuel_notes_non_texte_n_est_pas_un_500(self):
        for value in ([1], {'a': 1}):
            r = capi(self.direction).patch(f'{COMM}{self.row_.id}/set_manuel/',
                                           {'manuel_adjustment': '100', 'manuel_notes': value}, format='json')
            self.assertLess(r.status_code, 500, (repr(value), r.status_code))

    def test_set_manuel_refuse_apres_paiement_et_net_inchange(self):
        r = capi(self.direction).post(f'{COMM}{self.row_.id}/mark_paid/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        net = ClientCommission.objects.get(pk=self.row_.pk).net_payable
        r = capi(self.direction).patch(f'{COMM}{self.row_.id}/set_manuel/', {'manuel_adjustment': '1'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ClientCommission.objects.get(pk=self.row_.pk).net_payable, net)


# ------------------------------------------------------------------ permissions / core : corps non objet
from rest_framework.test import APIClient  # noqa: E402


class CorpsNonObjetCore(Base):
    ME = '/api/core/auth/me/'

    # (BUG-87x corrigé)
    def test_profil_patch_corps_non_objet_est_400(self):
        for body in ([], [1], 5):
            r = api(self.f1).patch(self.ME, body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code))

    # (BUG-87x corrigé)
    def test_profil_patch_new_password_non_texte_est_400(self):
        r = api(self.f1).patch(self.ME, {'new_password': 12345678, 'old_password': 'x'}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)

    def test_profil_patch_champs_texte_non_scalaires_est_400(self):
        r = api(self.f1).patch(self.ME, {'first_name': ['a']}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)
