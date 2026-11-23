"""
Commissions - ronde b21 (testeur clients/commissions, 2026-11-23). Verification independante de BUG-1013/1014
(retenue explicite, deduction_manual), BUG-1104 (carte une fois par client et par mois, card_applied) et attaque de
leurs interactions. Valeurs calculees a la main : 100 pains x 500 FC = 50 000 FC de commande, CM 25 % = 12 500 FC.
Cotisation 1 500 (Base5). Donnees FICTIVES. Code applicatif non modifie.
"""
from decimal import Decimal as D
from unittest import expectedFailure

from commissions.models import ClientCommission, CommissionPeriod
from commissions.tests.test_commissions_v5 import COMM, GEN, PERIODS, Base5, api
from core.testing import make_client
from sales.models import Invoice, InvoiceLine


class Base8(Base5):
    def setUp(self):
        super().setUp()
        for n, fee in zip(self.ns, ('1000', '800', '600')):
            n.card_fee_fc = D(fee)
            n.save(update_fields=['card_fee_fc'])
        self.c = make_client(self.ns[0], current_debt=D('0'))

    def rows(self, c=None):
        return list(ClientCommission.objects.filter(client=c or self.c).order_by('created_at', 'pk'))

    def total(self, f, c=None):
        return sum(getattr(r, f) for r in self.rows(c))

    def three(self, c=None):
        for n in self.ns:
            self.inv(n, c or self.c, 100)
        for n in self.ns:
            self.gen(n)

    def patch(self, row, body, expect=200):
        r = api(self.comptable).patch(f'{COMM}{row.id}/', body, format='json')
        self.assertEqual(r.status_code, expect, getattr(r, 'data', None))
        row.refresh_from_db()
        return r

    def carrier(self):
        (c,) = [r for r in self.rows() if r.card_applied]
        return c

    def inv_month(self, node, client, qty, month, day=10):
        i = Invoice.objects.create(node=node, client=client, payment_type='CREDIT', status='DELIVERED',
                                   payment_amount=D('0'), invoice_date=f'2026-{month:02d}-{day:02d}',
                                   node_origin=node.code)
        InvoiceLine.objects.create(invoice=i, bread_price=self.p500, quantity=qty)
        i.compute_order_total()
        i.save(update_fields=['order_total'])
        return i

    def gen_month(self, node, month):
        r = api(self.direction).post(GEN, {'node': node.pk, 'month': month, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))


class ValidationV6Inverse(Base8):
    """Valide le test v6 inverse : un zero pose par PATCH fige le mois ; un zero pose par ORM reste
    indiscernable d'une porteuse supprimee (limite documentee)."""

    def test_zero_par_patch_fige_le_mois_apres_suppression_et_regeneration(self):
        self.c.current_debt = D('10000')
        self.c.save()
        self.three()
        carrier = [r for r in self.rows() if r.deduction_debt != 0][0]
        self.patch(carrier, {'deduction_debt': '0', 'deduction_social': '0'})
        self.assertTrue(carrier.deduction_manual)
        other = [r for r in self.rows() if r.pk != carrier.pk][0]
        node = other.period.node
        other.delete()
        self.gen(node)
        self.assertEqual(self.total('deduction_debt'), D('0.00'))
        self.assertEqual(self.total('deduction_social'), D('0.00'))
        # la carte, elle, n'a pas ete touchee par le zero de la retenue : une seule, 1 000 FC (porteuse Y1)
        self.assertEqual(self.total('deduction_prints'), D('1000.00'))

    def test_la_decision_manuelle_ne_deborde_pas_sur_le_mois_suivant(self):
        self.c.current_debt = D('10000')
        self.c.save()
        self.inv_month(self.ns[0], self.c, 100, 2)
        self.gen_month(self.ns[0], 2)
        row = self.rows()[0]
        self.patch(row, {'deduction_debt': '0', 'deduction_social': '0'})
        self.inv_month(self.ns[0], self.c, 100, 3)
        self.gen_month(self.ns[0], 3)
        mars = ClientCommission.objects.get(client=self.c, period__month=3)
        self.assertEqual((mars.deduction_debt, mars.deduction_social), (D('10000.00'), D('1500.00')))
        self.assertEqual(mars.deduction_prints, D('1000.00'))  # une carte par MOIS
        self.assertTrue(mars.card_applied)
        self.assertFalse(mars.deduction_manual)

    def test_patch_sans_changement_reel_ou_sur_autre_champ_ne_pose_pas_le_drapeau(self):
        self.c.current_debt = D('4000')
        self.c.save()
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        row = self.rows()[0]
        self.patch(row, {'deduction_debt': '4000', 'deduction_social': '1500'})  # valeurs identiques
        self.assertFalse(row.deduction_manual)
        self.patch(row, {'deduction_other': '250'})
        self.assertFalse(row.deduction_manual)
        self.patch(row, {'deduction_prints': '1200'})
        self.assertFalse(row.deduction_manual)
        self.patch(row, {'deduction_social': '1000'})
        self.assertTrue(row.deduction_manual)

    def test_le_drapeau_ne_s_ecrit_ni_par_patch_ni_par_post(self):
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        row = self.rows()[0]
        self.patch(row, {'deduction_manual': True, 'card_applied': False})
        self.assertFalse(row.deduction_manual)
        self.assertTrue(row.card_applied)

    def test_put_modifiant_la_dette_pose_le_drapeau(self):
        self.c.current_debt = D('4000')
        self.c.save()
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        row = self.rows()[0]
        body = {'period': str(row.period_id), 'client': str(row.client_id), 'total_breads': row.total_breads,
                'order_value': str(row.order_value), 'commission_rate': str(row.commission_rate),
                'deduction_debt': '3000', 'deduction_social': '1500', 'deduction_prints': '1000',
                'deduction_other': '0'}
        r = api(self.comptable).put(f'{COMM}{row.id}/', body, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        row.refresh_from_db()
        self.assertTrue(row.deduction_manual)
        self.assertEqual(row.net_payable, D('12500.00') - D('3000') - D('1500') - D('1000'))


class CarteInteractions(Base8):
    def test_patch_de_la_dette_ne_fige_pas_la_carte_et_ne_la_deplace_pas(self):
        self.c.current_debt = D('10000')
        self.c.save()
        self.three()
        carrier = self.carrier()
        self.patch(carrier, {'deduction_debt': '4000'})
        self.assertTrue(carrier.deduction_manual)
        self.assertTrue(carrier.card_applied)
        for n in self.ns:
            self.gen(n)
        self.assertEqual(self.total('deduction_prints'), D('1000.00'))
        self.assertEqual(self.total('deduction_debt'), D('4000.00'))
        self.assertEqual(sum(1 for r in self.rows() if r.card_applied), 1)
        self.assertEqual(self.carrier().pk, carrier.pk)

    def test_carte_mise_a_zero_a_la_main_n_est_pas_reposee_ailleurs(self):
        self.three()
        carrier = self.carrier()
        self.patch(carrier, {'deduction_prints': '0'})  # la comptabilite renonce a la carte
        for n in self.ns:
            self.gen(n)
        self.assertEqual(self.total('deduction_prints'), D('0.00'))
        self.assertEqual(sum(1 for r in self.rows() if r.card_applied), 1)

    def test_imprimes_saisis_sur_la_porteuse_ecrasent_la_carte_limite_documentee(self):
        """deduction_prints = carte + imprimes : saisir 300 (imprimes) efface la carte de 1 000 (limite B-2)."""
        self.three()
        carrier = self.carrier()
        self.patch(carrier, {'deduction_prints': '300'})
        self.assertEqual(self.total('deduction_prints'), D('300.00'))
        self.assertEqual(self.carrier().deduction_prints, D('300.00'))

    def test_porteuse_payee_puis_nouvelle_ligne_ni_nouvelle_carte_ni_nouvelle_retenue(self):
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        carrier = self.carrier()
        r = api(self.direction).post(f'{COMM}{carrier.id}/mark_paid/', {}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        # nouvelle facture dans une autre boulangerie, regeneration
        self.inv(self.ns[1], self.c, 100)
        self.gen(self.ns[1])
        self.assertEqual(self.total('deduction_prints'), D('1000.00'))
        self.assertEqual(self.total('deduction_social'), D('1500.00'))
        nouvelle = [r for r in self.rows() if r.pk != carrier.pk][0]
        self.assertFalse(nouvelle.card_applied)
        self.assertEqual(nouvelle.net_payable, D('12500.00'))

    def test_porteuse_payee_avec_zero_puis_dette_apparue_la_nouvelle_ligne_la_reprend_sans_carte(self):
        """Premiere ligne payee sans dette ; la dette apparait avant la 2e boulangerie : elle est portee par
        la plus ancienne ligne NON payee (la nouvelle), une seule fois, et la carte n'est pas redoublee."""
        self.c.current_debt = D('0')
        self.c.save()
        # cotisation a zero : la ligne payee n'a aucune retenue de dette/cotisation
        self.ns[0].monthly_social_contribution = D('0')
        self.ns[0].save()
        self.c.cotisation_sociale = D('0')
        self.c.save()
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        carrier = self.carrier()
        api(self.direction).post(f'{COMM}{carrier.id}/mark_paid/', {}, format='json')
        type(self.c).objects.filter(pk=self.c.pk).update(current_debt=D('8000'), cotisation_sociale=D('1500'))
        self.inv(self.ns[1], self.c, 100)
        self.gen(self.ns[1])
        self.assertEqual(self.total('deduction_debt'), D('8000.00'))
        self.assertEqual(self.total('deduction_social'), D('1500.00'))
        self.assertEqual(self.total('deduction_prints'), D('1000.00'))
        self.assertEqual(sum(1 for r in self.rows() if r.deduction_debt != 0), 1)

    def test_carte_de_la_boulangerie_de_la_porteuse_trois_montants_differents(self):
        self.three()
        for ordre in ((2, 1, 0),):
            ClientCommission.objects.all().delete()
            CommissionPeriod.objects.all().delete()
            for i in ordre:
                self.gen(self.ns[i])
            self.assertEqual(self.total('deduction_prints'), D('600.00'))
        self.assertEqual(self.carrier().period.node, self.ns[2])

    def test_mois_suivant_une_nouvelle_carte(self):
        self.three()
        for n in self.ns:
            self.inv_month(n, self.c, 100, 3)
            self.gen_month(n, 3)
        fevrier = sum(r.deduction_prints for r in self.rows() if r.period.month == 2)
        mars = sum(r.deduction_prints for r in self.rows() if r.period.month == 3)
        self.assertEqual((fevrier, mars), (D('1000.00'), D('1000.00')))
        self.assertEqual(sum(1 for r in self.rows() if r.card_applied), 2)

    def test_porteuse_supprimee_la_carte_est_reportee_a_la_regeneration(self):
        self.three()
        carrier = self.carrier()
        node = carrier.period.node
        carrier.delete()
        self.assertEqual(self.total('deduction_prints'), D('0.00'))
        for n in self.ns:
            self.gen(n)
        self.assertEqual(sum(1 for r in self.rows() if r.card_applied), 1)
        self.assertEqual(self.total('deduction_prints') > 0, True)
        self.assertEqual(len(self.rows()), 3)
        self.assertIn(node.code, [r.period.node.code for r in self.rows()])

    def test_periode_close_de_la_porteuse_la_carte_n_est_pas_redoublee(self):
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        period = self.period(self.ns[0])
        r = api(self.direction).post(f'{PERIODS}{period.id}/close_period/', {}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.inv(self.ns[1], self.c, 100)
        self.gen(self.ns[1])
        self.assertEqual(self.total('deduction_prints'), D('1000.00'))
        self.assertEqual(self.total('deduction_social'), D('1500.00'))

    def test_deux_clients_deux_cartes_et_sommaire_vertical(self):
        c2 = make_client(self.ns[1], current_debt=D('0'))
        self.inv(self.ns[0], self.c, 100)
        self.inv(self.ns[1], self.c, 100)
        self.inv(self.ns[1], c2, 100)
        self.gen(self.ns[0])
        self.gen(self.ns[1])
        s = api(self.direction).get(COMM + 'summary/').data
        # c : Y1 porteuse (carte 1 000, cotisation 1 500) ; c2 : Y2 (carte 800, cotisation 1 500)
        self.assertEqual(D(s['total_carte']), D('1800.00'))
        self.assertEqual(D(s['total_cotisation']), D('3000.00'))
        self.assertEqual(D(s['total_cm']), D('37500.00'))
        self.assertEqual(D(s['total_net']), D('37500.00') - D('3000') - D('1800'))
        self.assertEqual(D(s['total_deductions']), D('4800.00'))


class NetNegatifEtListing(Base8):
    def test_net_negatif_non_payable_et_exact(self):
        self.c.current_debt = D('60000')
        self.c.save()
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        row = self.rows()[0]
        # 12 500 - (60 000 + 1 500 + 1 000) = -50 000
        self.assertEqual(row.net_payable, D('-50000.00'))
        r = api(self.direction).post(f'{COMM}{row.id}/mark_paid/', {}, format='json')
        self.assertEqual(r.status_code, 400)
        row.refresh_from_db()
        self.assertFalse(row.is_paid)

    def test_listing_de_paie_totaux_verticaux_trois_clients_et_carte_unique(self):
        c2 = make_client(self.ns[0], current_debt=D('2000'))
        c3 = make_client(self.ns[0], current_debt=D('0'))
        for c in (self.c, c2, c3):
            self.inv(self.ns[0], c, 100)
            self.inv(self.ns[1], c, 100)
        self.gen(self.ns[0])
        self.gen(self.ns[1])
        for node in self.ns[:2]:
            period = self.period(node)
            data = api(self.direction).get(COMM + 'payroll_listing/', {'period': str(period.id)}).data
            data = data['results'] if isinstance(data, dict) else data
            self.assertEqual(len(data), 3)
            s = api(self.direction).get(COMM + 'summary/', {'period': str(period.id)}).data
            for champ, cle in (('net_payable', 'total_net'), ('deduction_prints', 'total_carte'),
                               ('deduction_social', 'total_cotisation'), ('commission_gross', 'total_cm')):
                somme = sum(D(str(x[champ])) for x in data)
                self.assertEqual(somme, D(s[cle]), (node.code, champ))
        # Y1 (premier genere) porte les 3 cartes (1 000 chacune), Y2 aucune
        s1 = api(self.direction).get(COMM + 'summary/', {'period': str(self.period(self.ns[0]).id)}).data
        s2 = api(self.direction).get(COMM + 'summary/', {'period': str(self.period(self.ns[1]).id)}).data
        self.assertEqual((D(s1['total_carte']), D(s2['total_carte'])), (D('3000.00'), D('0.00')))
        self.assertEqual(D(s1['total_debt']) + D(s2['total_debt']), D('2000.00'))
        self.assertEqual(D(s1['total_net']) + D(s2['total_net']),
                         6 * D('12500') - D('2000') - 3 * D('1500') - D('3000'))

    @expectedFailure
    def test_card_applied_expose_en_lecture_seule_comme_annonce_par_le_rapport_b2(self):
        """BUG-1028 : le rapport B-2 annonce `card_applied` en lecture seule dans l'API ; absent du serializer."""
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        row = self.rows()[0]
        data = api(self.direction).get(f'{COMM}{row.id}/').data
        self.assertIn('card_applied', data)
        self.assertIs(data['card_applied'], True)


class CarteDependDeLOrdreDeGeneration(Base8):
    def test_carte_zero_de_la_premiere_boulangerie_generee_supprime_toute_carte_documente(self):
        """BUG-1029 (A CLARIFIER) : le montant de carte d'un client multi-boulangeries est celui de la
        PREMIERE boulangerie generee ; si cette boulangerie a card_fee_fc = 0, aucune carte n'est prelevee
        ce mois-la meme si les autres boulangeries (1 000 / 800) en font payer une. Comportement documente."""
        self.ns[0].card_fee_fc = D('0')
        self.ns[0].save()
        self.three()
        self.assertEqual(self.total('deduction_prints'), D('0.00'))
        self.assertEqual(sum(1 for r in self.rows() if r.card_applied), 1)
        # ordre inverse : la meme situation produit 600
        ClientCommission.objects.all().delete()
        CommissionPeriod.objects.all().delete()
        for i in (2, 1, 0):
            self.gen(self.ns[i])
        self.assertEqual(self.total('deduction_prints'), D('600.00'))
