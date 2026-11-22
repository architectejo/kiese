"""Clients - ronde v4 (testeur Clients/Commissions, 2026-11-22-b4).

Verification independante de BUG-747 (bornes de la remise annuelle et du total
a recevoir) et attaque des chemins de calcul voisins (refresh_indices,
auto_populate_lines, changement de tarif, distribution cloturee).
Donnees FICTIVES uniquement.
"""
from decimal import Decimal as D
from unittest import expectedFailure

from clients.models import SocialContribution, SocialDistributionLine
from clients.tests.test_clients_v2 import CONTRIB, DISTRIB, LINES, Base, api


class RemiseAnnuelleBornes(Base):
    def setUp(self):
        super().setUp()
        self.c1 = self.mk(self.k1, 'A', 'A')
        self.c2 = self.mk(self.k1, 'B', 'B')

    def distrib(self, tarif='700', year=2026):
        r = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': year, 'tarif': tarif}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def line(self, d, client=None, **kw):
        return api(self.g1).post(LINES, dict({'distribution': d, 'client': str((client or self.c1).id)}, **kw),
                                 format='json')

    def test_calcul_a_la_main_remise_et_total(self):
        d = self.distrib('700')
        r = self.line(d, indice=7, total_social='14000', merite='1500.50')
        self.assertEqual(r.status_code, 201, r.data)
        # remise = 7 x 700 = 4 900 ; total = 14 000 + 4 900 + 1 500,50
        self.assertEqual((r.data['remise'], r.data['total_payer']), ('4900.00', '20400.50'))

    def test_borne_somme_exacte_acceptee_et_refus_a_10_puissance_8(self):
        d = self.distrib('0')
        ok = self.line(d, total_social='99999999.99')
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertEqual(ok.data['total_payer'], '99999999.99')
        # 99 999 999,98 + 0,01 = 99 999 999,99 : accepte ; + 0,02 : refuse
        r1 = self.line(d, client=self.c2, total_social='99999999.98', merite='0.01')
        self.assertEqual(r1.status_code, 201, r1.data)
        self.assertEqual(r1.data['total_payer'], '99999999.99')
        c3 = self.mk(self.k1, 'C', 'C')
        r2 = self.line(d, client=c3, total_social='99999999.98', merite='0.02')
        self.assertEqual(r2.status_code, 400, r2.data)
        self.assertFalse(SocialDistributionLine.objects.filter(client=c3).exists())

    def test_remise_12_mois_tarif_maximal_exact(self):
        d = self.distrib('8333333.33')                    # 12 x 8 333 333,33 = 99 999 999,96
        r = self.line(d, indice=12)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['remise'], '99999999.96')
        r = self.line(d, client=self.c2, indice=12, merite='0.03')      # = 99 999 999,99
        self.assertEqual(r.status_code, 201, r.data)
        c3 = self.mk(self.k1, 'C', 'C')
        r = self.line(d, client=c3, indice=12, merite='0.04')           # = 100 000 000,00
        self.assertEqual(r.status_code, 400, r.data)

    def test_remise_seule_au_dessus_de_la_borne_400_en_francais(self):
        d = self.distrib('8333333.34')                    # 12 x = 100 000 000,08
        r = self.line(d, indice=12)
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(self.line(d, indice=11).status_code, 201)

    def test_patch_ligne_indice_et_merite_bornes(self):
        d = self.distrib('8333333.33')
        lid = self.line(d, indice=1).data['id']
        for body, code in (({'indice': 12}, 200), ({'merite': '0.03'}, 200), ({'merite': '0.04'}, 400),
                           ({'total_social': '0.01'}, 400)):
            with self.subTest(body=body):
                r = api(self.g1).patch(f'{LINES}{lid}/', body, format='json')
                self.assertEqual(r.status_code, code, (body, r.data))
        x = SocialDistributionLine.objects.get(pk=lid)
        self.assertEqual((x.indice, x.remise, x.total_payer), (12, D('99999999.96'), D('99999999.99')))

    def test_patch_tarif_refuse_si_une_ligne_deborderait_et_rien_n_est_modifie(self):
        d = self.distrib('700')
        lid = self.line(d, indice=12, total_social='1000').data['id']
        r = api(self.direction).patch(f'{DISTRIB}{d}/', {'tarif': '9000000'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        x = SocialDistributionLine.objects.get(pk=lid)
        self.assertEqual((x.remise, x.total_payer), (D('8400.00'), D('9400.00')))
        r = api(self.direction).patch(f'{DISTRIB}{d}/', {'tarif': '8333250'}, format='json')   # 99 999 000 + 1 000 = 10^8
        self.assertEqual(r.status_code, 400, r.data)
        r = api(self.direction).patch(f'{DISTRIB}{d}/', {'tarif': '8333249'}, format='json')   # 99 998 988 + 1 000
        self.assertEqual(r.status_code, 200, r.data)
        x.refresh_from_db()
        self.assertEqual((x.remise, x.total_payer), (D('99998988.00'), D('99999988.00')))

    def test_tarif_hors_colonne_400(self):
        for tarif in ('100000000', '1e9', 'NaN', 'Infinity', '-1', '99999999.999'):
            with self.subTest(tarif=tarif):
                r = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2030, 'tarif': tarif}, format='json')
                self.assertEqual(r.status_code, 400, (tarif, r.status_code))

    def test_refresh_indices_somme_de_cotisations_au_dessus_de_la_colonne(self):
        """Deux cotisations payees de 99 999 999,99 : total_social = 199 999 999,98 (hors colonne).
        L'action ne doit jamais renvoyer 500."""
        d = self.distrib('700')
        self.line(d)
        for m in (1, 2):
            SocialContribution.objects.create(client=self.c1, node=self.k1, month=m, year=2026,
                                              amount=D('99999999.99'), is_paid=True)
        r = api(self.g1).post(f'{DISTRIB}{d}/refresh_indices/', {}, format='json')
        self.assertLess(r.status_code, 500, r.status_code)

    def test_auto_populate_somme_de_cotisations_au_dessus_de_la_colonne(self):
        d = self.distrib('700')
        for m in (1, 2):
            SocialContribution.objects.create(client=self.c1, node=self.k1, month=m, year=2026,
                                              amount=D('99999999.99'), is_paid=True)
        r = api(self.g1).post(f'{DISTRIB}{d}/auto_populate_lines/', {}, format='json')
        self.assertLess(r.status_code, 500, r.status_code)

    def test_refresh_indices_calcul_a_la_main(self):
        d = self.distrib('700')
        lid = self.line(d, merite='300').data['id']
        for m in (1, 2, 3):
            SocialContribution.objects.create(client=self.c1, node=self.k1, month=m, year=2026,
                                              amount=D('2000'), is_paid=True)
        SocialContribution.objects.create(client=self.c1, node=self.k1, month=4, year=2026, amount=D('2000'))
        SocialContribution.objects.create(client=self.c1, node=self.k1, month=5, year=2025, amount=D('2000'), is_paid=True)
        r = api(self.g1).post(f'{DISTRIB}{d}/refresh_indices/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        x = SocialDistributionLine.objects.get(pk=lid)
        # indice 3 ; total social 6 000 ; remise 3 x 700 = 2 100 ; total = 6 000 + 2 100 + 300
        self.assertEqual((x.indice, x.total_social, x.remise, x.total_payer), (3, D('6000.00'), D('2100.00'), D('8400.00')))

    def test_distribution_cloturee_refuse_refresh_et_auto_populate(self):
        d = self.distrib('700')
        api(self.direction).patch(f'{DISTRIB}{d}/', {'is_closed': True}, format='json')
        for action in ('refresh_indices', 'auto_populate_lines'):
            r = api(self.g1).post(f'{DISTRIB}{d}/{action}/', {}, format='json')
            self.assertEqual(r.status_code, 400, (action, r.status_code))

    def test_ligne_d_une_distribution_cloturee_est_immuable(self):
        d = self.distrib('700')
        lid = self.line(d, indice=2, total_social='4000').data['id']
        api(self.direction).patch(f'{DISTRIB}{d}/', {'is_closed': True}, format='json')
        r = api(self.g1).patch(f'{LINES}{lid}/', {'merite': '5000'}, format='json')
        x = SocialDistributionLine.objects.get(pk=lid)
        self.assertEqual((r.status_code >= 400, x.merite), (True, D('0.00')), (r.status_code, x.merite))

    def test_gerant_k3_ne_peut_pas_lire_ni_modifier_la_ligne_de_k1(self):
        d = self.distrib('700')
        lid = self.line(d).data['id']
        self.assertEqual(api(self.g3).get(f'{LINES}{lid}/').status_code, 404)
        self.assertEqual(api(self.g3).patch(f'{LINES}{lid}/', {'merite': '1'}, format='json').status_code, 404)
        self.assertEqual(api(self.g3).delete(f'{LINES}{lid}/').status_code, 404)

    def test_facturier_et_livreur_refuses(self):
        d = self.distrib('700')
        for u in (self.f1, self.l1):
            self.assertEqual(self.line_as(u, d).status_code, 403)

    def line_as(self, user, d):
        return api(user).post(LINES, {'distribution': d, 'client': str(self.c1.id)}, format='json')

    def test_creation_et_suppression_de_ligne_refusees_sur_distribution_cloturee(self):
        d = self.distrib('700')
        lid = self.line(d, indice=2).data['id']
        api(self.direction).patch(f'{DISTRIB}{d}/', {'is_closed': True}, format='json')
        self.assertGreaterEqual(self.line(d, client=self.c2).status_code, 400)
        self.assertGreaterEqual(api(self.g1).delete(f'{LINES}{lid}/').status_code, 400)
        self.assertEqual(SocialDistributionLine.objects.filter(distribution_id=d).count(), 1)

    def test_corps_non_objet_sur_les_actions_clients(self):
        d = self.distrib('700')
        for url in (CONTRIB + 'bulk_create_month/', f'{DISTRIB}{d}/refresh_indices/', '/api/clients/clients/bulk_move/',
                    '/api/clients/clients/bulk_delete/'):
            for body in ([], [1], 'x', 5):
                with self.subTest(url=url, body=body):
                    r = api(self.direction).post(url, body, format='json')
                    self.assertLess(r.status_code, 500, (url, body, r.status_code))
