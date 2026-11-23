"""Commissions - ronde v3 (testeur Clients/Commissions, 2026-11-22-b3).

Verification independante de BUG-737, 744, 745 et attaque des correctifs :
ordre de generation, regeneration, client dans 3 boulangeries, paie deja payee,
suppression de la ligne qui retient, set_manuel (arrondi, negatifs, limites),
regressions CM/retenues/net. Valeurs calculees a la main. Donnees FICTIVES.
"""
import uuid
from decimal import Decimal as D
from unittest import expectedFailure

from commissions.models import ClientCommission, CommissionPeriod
from commissions.tests.test_commissions_v2 import (
    COMM, GEN, PERIODS, Base, api, rows,
)
from core.testing import make_bread_price, make_client, make_node, make_user


class Retenue737Tests(Base):
    def setUp(self):
        super().setUp()
        self.n5 = make_node(code='QA5', social=D('900'), card_fee=D('300'))
        # client de QA3 : BP 10 000, cotisation de QA3 = 1 500
        self.c = make_client(self.n3, current_debt=D('10000'))

    def total(self, field, client=None, month=2, year=2026):
        return sum(getattr(r, field) for r in ClientCommission.objects.filter(
            client=client or self.c, period__month=month, period__year=year))

    def test_trois_boulangeries_une_seule_retenue_dette_et_cotisation(self):
        for n in (self.n3, self.n1, self.n5):
            self.invoice(n, self.c, 100)       # 50 000 chacune
        for n in (self.n1, self.n5, self.n3):  # ordre : QA1 retient
            self.generate(n)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        self.assertEqual(self.total('deduction_social'), D('1500.00'))
        self.assertEqual(ClientCommission.objects.filter(client=self.c).count(), 3)
        first = ClientCommission.objects.get(client=self.c, period__node=self.n1)
        self.assertEqual((first.deduction_debt, first.deduction_social), (D('10000.00'), D('1500.00')))
        # BUG-1104 : la carte (QA1 = 1 000, boulangerie porteuse) n'est retenue qu'une fois
        self.assertEqual(first.deduction_prints, D('1000.00'))
        for n, card in ((self.n5, D('0.00')), (self.n3, D('0.00'))):
            r = ClientCommission.objects.get(client=self.c, period__node=n)
            self.assertEqual((r.deduction_debt, r.deduction_social, r.deduction_prints), (D('0.00'), D('0.00'), card))
            # CM = 50 000 x 0,25 = 12 500 ; net = 12 500 - carte
            self.assertEqual(r.net_payable, D('12500.00') - card)

    def test_l_ordre_de_generation_change_la_ligne_qui_retient_mais_pas_le_total(self):
        for n in (self.n3, self.n1):
            self.invoice(n, self.c, 100)
        self.generate(self.n3)
        self.generate(self.n1)
        r3 = ClientCommission.objects.get(client=self.c, period__node=self.n3)
        self.assertEqual(r3.deduction_debt, D('10000.00'))
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))

    def test_regeneration_ne_deplace_ni_ne_double_la_retenue(self):
        for n in (self.n3, self.n1):
            self.invoice(n, self.c, 100)
        self.generate(self.n1)
        self.generate(self.n3)
        for _ in range(3):
            self.generate(self.n1)
            self.generate(self.n3)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        self.assertEqual(self.total('deduction_social'), D('1500.00'))
        self.assertEqual(ClientCommission.objects.filter(client=self.c).count(), 2)

    def test_nouvelle_facture_apres_generation_met_a_jour_sans_toucher_aux_retenues(self):
        self.invoice(self.n3, self.c, 100)
        self.invoice(self.n1, self.c, 100)
        self.generate(self.n3)
        self.generate(self.n1)
        self.invoice(self.n1, self.c, 20, day=20)          # +10 000
        self.generate(self.n1)
        r1 = ClientCommission.objects.get(client=self.c, period__node=self.n1)
        self.assertEqual(r1.order_value, D('60000.00'))
        self.assertEqual(r1.commission_gross, D('15000.00'))
        self.assertEqual(r1.deduction_debt, D('0.00'))
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))

    def test_chaque_mois_retient_a_nouveau_la_bp_courante(self):
        self.invoice(self.n3, self.c, 100, month=2)
        self.invoice(self.n3, self.c, 100, month=3)
        self.invoice(self.n1, self.c, 100, month=3)
        self.generate(self.n3, month=2)
        self.generate(self.n3, month=3)
        self.generate(self.n1, month=3)
        self.assertEqual(self.total('deduction_social', month=2), D('1500.00'))
        self.assertEqual(self.total('deduction_social', month=3), D('1500.00'))
        self.assertEqual(self.total('deduction_debt', month=3), D('10000.00'))

    def test_meme_mois_annees_differentes_independants(self):
        self.invoice(self.n3, self.c, 100, year=2025)
        self.invoice(self.n1, self.c, 100, year=2026)
        self.generate(self.n3, year=2025)
        self.generate(self.n1, year=2026)
        self.assertEqual(self.total('deduction_debt', year=2025), D('10000.00'))
        self.assertEqual(self.total('deduction_debt', year=2026), D('10000.00'))

    def test_premiere_ligne_deja_payee_deuxieme_ligne_a_zero_et_payee_intacte(self):
        self.invoice(self.n3, self.c, 100)
        self.invoice(self.n1, self.c, 100)
        p3 = self.generate(self.n3)
        r3 = self.row(p3, self.c)
        self.assertEqual(api(self.direction).post(f'{COMM}{r3.id}/mark_paid/').status_code, 200)
        self.generate(self.n1)
        self.generate(self.n3)   # regeneration : la ligne payee est ignoree
        r3.refresh_from_db()
        self.assertTrue(r3.is_paid)
        self.assertEqual((r3.deduction_debt, r3.deduction_social), (D('10000.00'), D('1500.00')))
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))

    def test_periode_de_l_autre_boulangerie_cloturee_ne_bloque_pas_la_generation(self):
        self.invoice(self.n3, self.c, 100)
        self.invoice(self.n1, self.c, 100)
        p3 = self.generate(self.n3)
        self.assertEqual(api(self.direction).post(f'{PERIODS}{p3.id}/close_period/').status_code, 200)
        self.generate(self.n1)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))

    def test_clients_differents_ne_s_influencent_pas(self):
        c2 = make_client(self.n1, current_debt=D('2000'))
        self.invoice(self.n3, self.c, 100)
        self.invoice(self.n1, c2, 100)
        self.generate(self.n3)
        self.generate(self.n1)
        self.assertEqual(self.row(CommissionPeriod.objects.get(node=self.n1), c2).deduction_debt, D('2000.00'))

    def test_bp_creditrice_retenue_une_fois(self):
        c = make_client(self.n3, current_debt=D('-4000'))
        self.invoice(self.n3, c, 100)
        self.invoice(self.n1, c, 100)
        self.generate(self.n1)
        self.generate(self.n3)
        self.assertEqual(self.total('deduction_debt', client=c), D('-4000.00'))

    def test_suppression_de_la_ligne_qui_retient_puis_regeneration(self):
        """La ligne qui portait la BP est supprimee, puis la paie regeneree : la BP du client doit
        etre retenue quelque part (sinon elle disparait de toutes les paies du mois)."""
        self.invoice(self.n3, self.c, 100)
        self.invoice(self.n1, self.c, 100)
        self.generate(self.n3)
        self.generate(self.n1)
        r3 = ClientCommission.objects.get(client=self.c, period__node=self.n3)
        self.assertEqual(api(self.comptable).delete(f'{COMM}{r3.id}/').status_code, 204)
        self.generate(self.n3)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))

    def test_summary_totaux_verticaux_apres_double_facturation(self):
        self.invoice(self.n3, self.c, 100)
        self.invoice(self.n1, self.c, 100)
        p3 = self.generate(self.n3)
        self.generate(self.n1)
        r = api(self.comptable).get(f'{COMM}summary/', {'period': str(p3.id)})
        self.assertEqual(r.status_code, 200)
        # QA3 : CM 12 500, dette 10 000, cotisation 1 500, carte 700 -> net 300
        self.assertEqual((D(r.data['total_cm']), D(r.data['total_debt']), D(r.data['total_cotisation']), D(r.data['total_net'])),
                         (D('12500'), D('10000'), D('1500'), D('300')))


class SetManuelV3Tests(Base):
    def setUp(self):
        super().setUp()
        self.c = make_client(self.n1, current_debt=D('0'))
        self.invoice(self.n1, self.c, 100)
        self.r = self.row(self.generate(self.n1), self.c)   # CM 12 500 ; social 2 000 ; carte 1 000 ; net 9 500

    def set(self, value, **extra):
        return api(self.direction).patch(f'{COMM}{self.r.id}/set_manuel/',
                                         dict({'manuel_adjustment': value}, **extra), format='json')

    def test_net_initial(self):
        self.assertEqual(self.r.net_payable, D('9500.00'))

    def test_valeurs_valides_exactes(self):
        for value, expected in (('100', '100.00'), (100, '100.00'), ('0', '0.00'), ('-250.5', '-250.50'),
                                (' 12.34 ', '12.34'), ('1e2', '100.00'), ('999999999999.99', '999999999999.99'),
                                ('-999999999999.99', '-999999999999.99'), ('0.01', '0.01'), ('-0.01', '-0.01')):
            with self.subTest(value=value):
                r = self.set(value)
                self.assertEqual(r.status_code, 200, (value, r.data))
                self.assertEqual(r.data['net_payable'], expected)
                self.r.refresh_from_db()
                self.assertEqual(self.r.net_payable, D(expected))
                self.assertIsInstance(self.r.manuel_adjustment, D)

    def test_valeurs_refusees_sans_effet(self):
        for value in ('NaN', 'sNaN', 'Infinity', '-Infinity', 'inf', '1e12', '1000000000000', '-1000000000000',
                      '', 'abc', '1,5', '--1', [1], {'a': 1}, True, False, '0x10'):
            with self.subTest(value=value):
                r = self.set(value)
                if value == '':
                    # chaine vide : refus attendu (ne doit pas effacer ni empoisonner)
                    self.assertEqual(r.status_code, 400, r.status_code)
                else:
                    self.assertEqual(r.status_code, 400, (value, r.status_code))
                self.r.refresh_from_db()
                self.assertIsNone(self.r.manuel_adjustment)
                self.assertEqual(self.r.net_payable, D('9500.00'))

    def test_exposant_gigantesque_refuse_en_400(self):
        for value in ('1E999999999', '-1E999999999', '1E+99999999999'):
            with self.subTest(value=value):
                self.assertEqual(self.set(value).status_code, 400, value)

    def test_arrondi_millieme_documente(self):
        """Valeurs a 3 decimales : l'arrondi doit rester a +/- 0,01 de la valeur saisie et rester un Decimal."""
        for value, allowed in (('0.004', {'0.00'}), ('0.006', {'0.01'}), ('1.005', {'1.00', '1.01'}),
                               ('2.675', {'2.67', '2.68'}), ('-0.004', {'0.00', '-0.00'})):
            with self.subTest(value=value):
                r = self.set(value)
                self.assertEqual(r.status_code, 200)
                self.assertIn(r.data['net_payable'], allowed)

    def test_arrondi_demi_au_centime_observation(self):
        """0,005 -> 0,00 (arrondi bancaire ROUND_HALF_EVEN de quantize) : documente, pas de ticket."""
        self.assertEqual(self.set('0.005').data['net_payable'], '0.00')
        self.assertEqual(self.set('0.015').data['net_payable'], '0.02')

    def test_effacer_l_ajustement_restaure_le_calcul(self):
        self.set('123')
        r = self.set(None)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['net_payable'], '9500.00')
        self.r.refresh_from_db()
        self.assertIsNone(self.r.manuel_adjustment)
        self.assertEqual(self.r.manuel_notes, '')

    def test_notes_null_jamais_500(self):
        self.assertLess(self.set('10', manuel_notes=None).status_code, 500)

    def test_notes_types_exotiques_jamais_500(self):
        for notes in ('x' * 100000, '', 12, ['a'], {'a': 1}, 'é\u0000z', '\U0001F600'):
            with self.subTest(notes=repr(notes)[:15]):
                r = self.set('10', manuel_notes=notes)
                self.assertLess(r.status_code, 500, (repr(notes)[:15], r.status_code))

    def test_champ_absent_du_corps_efface_l_ajustement(self):
        """PATCH sans manuel_adjustment : ne doit pas silencieusement effacer un ajustement existant."""
        self.set('123')
        r = api(self.direction).patch(f'{COMM}{self.r.id}/set_manuel/', {'manuel_notes': 'note seule'}, format='json')
        self.r.refresh_from_db()
        self.assertEqual(self.r.manuel_adjustment, D('123.00'), (r.status_code, r.data))

    def test_commission_payee_ou_periode_cloturee_ou_non_direction(self):
        self.set('100')
        self.assertEqual(api(self.direction).post(f'{COMM}{self.r.id}/mark_paid/').status_code, 200)
        r = self.set('5')
        self.assertEqual(r.status_code, 400)
        self.r.refresh_from_db()
        self.assertEqual(self.r.manuel_adjustment, D('100.00'))
        for u in (self.comptable, self.g1, self.f1, self.l1):
            self.assertIn(api(u).patch(f'{COMM}{self.r.id}/set_manuel/', {'manuel_adjustment': '1'}, format='json').status_code,
                          (403, 404))

    def test_ajustement_negatif_ne_peut_pas_etre_paye(self):
        self.set('-50')
        r = api(self.direction).post(f'{COMM}{self.r.id}/mark_paid/')
        self.assertEqual(r.status_code, 400)
        self.r.refresh_from_db()
        self.assertFalse(self.r.is_paid)

    def test_deux_ajustements_successifs_le_dernier_gagne_pas_de_cumul(self):
        self.set('100')
        r = self.set('40')
        self.assertEqual(r.data['net_payable'], '40.00')


class RegressionFormulesV3(Base):
    def setUp(self):
        super().setUp()
        self.n0 = make_node(code='QA0', social=D('0'), card_fee=D('0'))
        self.p175 = make_bread_price('MOYEN', 'Pain 175 FC', 175)

    def test_cm_025_et_030_valeurs_non_rondes(self):
        a = make_client(self.n0, commission_rate=D('0.25'), current_debt=D('100.10'))
        b = make_client(self.n0, commission_rate=D('0.30'), current_debt=D('0'))
        self.invoice(self.n0, a, 7, price=self.p175)     # 1 225
        self.invoice(self.n0, b, 33, price=self.p175)    # 5 775
        p = self.generate(self.n0)
        ra, rb = self.row(p, a), self.row(p, b)
        self.assertEqual(ra.commission_gross, D('306.25'))       # 1 225 x 0,25
        self.assertEqual((ra.total_deductions, ra.net_payable), (D('100.10'), D('206.15')))
        self.assertEqual(rb.commission_gross, D('1732.50'))      # 5 775 x 0,30
        self.assertEqual(rb.net_payable, D('1732.50'))
        self.assertEqual(rb.annual_bonus, D('0.00'))

    def test_total_retenues_somme_des_quatre_postes(self):
        c = make_client(self.n0, current_debt=D('300'))
        self.invoice(self.n0, c, 100)   # 50 000 -> CM 12 500
        r = self.row(self.generate(self.n0), c)
        resp = api(self.comptable).patch(f'{COMM}{r.id}/', {'deduction_social': '250.25', 'deduction_prints': '49.75',
                                                            'deduction_other': '0.01'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        r.refresh_from_db()
        self.assertEqual(r.total_deductions, D('600.01'))        # 300 + 250,25 + 49,75 + 0,01
        self.assertEqual(r.net_payable, D('11899.99'))

    def test_net_negatif_reporte_sur_la_periode_suivante_meme_noeud(self):
        c = make_client(self.n0, current_debt=D('20000'))
        self.invoice(self.n0, c, 100, month=2)                    # CM 12 500 - BP 20 000 = -7 500
        r2 = self.row(self.generate(self.n0, month=2), c)
        self.assertEqual(r2.net_payable, D('-7500.00'))
        self.invoice(self.n0, c, 100, month=3)
        r3 = self.row(self.generate(self.n0, month=3), c)
        self.assertEqual(r3.carried_debt_in, D('7500.00'))

    def test_vente_solde_cash_et_epargne_sans_cm(self):
        c = make_client(self.n0)
        self.invoice(self.n0, c, 100, is_soldee=True)
        e = make_client(self.n0, current_debt=D('-30000'))
        self.invoice(self.n0, e, 0)
        self.generate(self.n0)
        self.assertFalse(ClientCommission.objects.filter(client__in=[c, e]).exists())

    def test_aucun_float_dans_l_api(self):
        c = make_client(self.n0, current_debt=D('10.10'))
        self.invoice(self.n0, c, 7, price=self.p175)
        self.generate(self.n0)
        for item in rows(api(self.comptable).get(COMM)):
            for k in ('commission_gross', 'net_payable', 'total_deductions', 'deduction_debt', 'order_value'):
                self.assertIsInstance(item[k], str, k)


class PayrollListingV3Tests(Base):
    def test_period_formats_et_inconnue(self):
        c = make_client(self.n1)
        self.invoice(self.n1, c, 10)
        p = self.generate(self.n1)
        for value in (str(p.id), p.id.hex, str(p.id).upper(), f'{{{p.id}}}', f'urn:uuid:{p.id}'):
            with self.subTest(value=value):
                r = api(self.comptable).get(f'{COMM}payroll_listing/', {'period': value})
                self.assertEqual(r.status_code, 200, (value, r.status_code))
                self.assertEqual(len(r.data), 1)
        r = api(self.comptable).get(f'{COMM}payroll_listing/', {'period': str(uuid.uuid4())})
        self.assertEqual((r.status_code, list(r.data)), (200, []))
        for bad in ('abc', '1', '%00', "' OR 1=1", 'x' * 500, '12345678-1234-1234-1234-12345678901g'):
            with self.subTest(bad=bad[:20]):
                self.assertEqual(api(self.comptable).get(f'{COMM}payroll_listing/', {'period': bad}).status_code, 400)

    def test_gerant_et_facturier_refuses(self):
        for u in (self.g1, self.f1, self.l1):
            self.assertEqual(api(u).get(f'{COMM}payroll_listing/', {'period': str(uuid.uuid4())}).status_code, 403)

    def test_filtre_period_de_la_liste_valeur_invalide(self):
        r = api(self.comptable).get(COMM, {'period': 'abc'})
        self.assertLess(r.status_code, 500)
