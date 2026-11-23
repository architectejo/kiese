"""BUG-289 (cotisation par boulangerie), BUG-292 (REMISE 0,25 % de la commande),
BUG-293 (BP créditrice ajoutée au net). Valeurs calculées à la main."""
from decimal import Decimal as D

from django.test import TestCase

from clients.models import Client
from commissions.models import ClientCommission
from commissions.tests.test_vague2_db_commissions_2026_11_12 import Base as _Base, COMM, _api
from core.testing import make_client


class Base(_Base):
    def setUp(self):
        super().setUp()
        self.node.monthly_social_contribution = D('0')   # défaut réel de la boulangerie
        self.node.save()


class Bug289CotisationParBoulangerie(Base):
    def test_defaut_boulangerie_zero(self):
        self.assertEqual(self.node.monthly_social_contribution, D('0'))
        c = make_client(self.node)
        self.assertIsNone(c.cotisation_sociale)
        self.invoice(c, 10)                                   # 5000 -> CM 1250
        cc = self.row(self.generate(), c)
        self.assertEqual(cc.deduction_social, D('0'))
        self.assertEqual(cc.net_payable, D('1250'))

    def test_valeur_boulangerie_appliquee_aux_clients_sans_personnalisation(self):
        self.node.monthly_social_contribution = D('2000')
        self.node.save()
        c = make_client(self.node)
        self.invoice(c, 10)
        cc = self.row(self.generate(), c)
        self.assertEqual(cc.deduction_social, D('2000.00'))
        self.assertEqual(cc.net_payable, D('1250') - D('2000'))

    def test_personnalisation_client_prevaut(self):
        self.node.monthly_social_contribution = D('2000')
        self.node.save()
        c = make_client(self.node)
        Client.objects.filter(pk=c.pk).update(cotisation_sociale=D('500'))
        self.invoice(c, 10)
        self.assertEqual(self.row(self.generate(), c).deduction_social, D('500.00'))

    def test_commission_deja_creee_garde_son_montant_apres_changement_boulangerie(self):
        # BUG-1013/1014 (BUG-1022) : un zéro jamais décidé n'est pas figé (la retenue du mois est
        # reportée sur la plus ancienne ligne non payée). Une retenue DÉJÀ posée, elle, reste figée.
        self.node.monthly_social_contribution = D('1000')
        self.node.save()
        c = make_client(self.node)
        self.invoice(c, 10)
        cc = self.row(self.generate(), c)
        self.assertEqual(cc.deduction_social, D('1000'))
        self.node.monthly_social_contribution = D('2000')
        self.node.save()
        self.generate()                                       # régénération : retenue figée
        cc.refresh_from_db()
        self.assertEqual(cc.deduction_social, D('1000'))

    def test_champ_exposé_par_les_api_node_et_client(self):
        r = _api(self.direction).patch(f'/api/core/nodes/{self.node.pk}/',
                                       {'monthly_social_contribution': '2000'}, format='json')
        self.assertIn(r.status_code, (200,), getattr(r, 'data', None))
        self.node.refresh_from_db()
        self.assertEqual(self.node.monthly_social_contribution, D('2000.00'))
        c = make_client(self.node)
        r = _api(self.direction).get(f'/api/clients/clients/{c.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(D(r.data['effective_cotisation_sociale']), D('2000.00'))
        self.assertIsNone(r.data['cotisation_sociale'])


class Bug292Remise(Base):
    def test_remise_est_025_pct_de_la_commande_non_deduite(self):
        c = make_client(self.node)
        self.invoice(c, 100)                                  # 50 000 -> CM 12 500
        cc = self.row(self.generate(), c)
        self.assertEqual(cc.deduction_remise, D('125.00'))    # 50 000 x 0,25 %
        self.assertEqual(cc.net_payable, D('12500'))   # ni REMISE ni CARTE déduites


class Bug291SansCarte(Base):
    def test_net_egale_cm_plus_remise_incorporee_moins_retenues_sans_carte(self):
        c = make_client(self.node, current_debt=D('1000'))
        self.invoice(c, 100)                                  # 50 000 -> CM 12 500 ; 100 pains
        cc = self.row(self.generate(), c)
        self.assertEqual(cc.deduction_carte, D('0.00'))
        self.assertEqual(cc.net_carte, cc.net_ordi)
        _api(self.direction).patch(f'{COMM}{cc.pk}/', {'annual_bonus_incorporated': True,
                                                       'deduction_other': '200'}, format='json')
        cc.refresh_from_db()
        # net = CM + remise annuelle incorporée (100 x 0,025) - (dette 1000 + sociale 0 + imprimés + autre 200)
        expected = D('12500') + cc.annual_bonus - D('1000') - cc.deduction_social \
            - cc.deduction_prints - D('200')
        self.assertEqual(cc.net_payable, expected)
        self.assertEqual(cc.total_deductions, D('1000') + cc.deduction_social + cc.deduction_prints + D('200'))


class Bug293CreditBP(Base):
    def test_bp_creditrice_ajoutee_au_net(self):
        c = make_client(self.node, current_debt=D('-2000'))
        self.invoice(c, 100)                                  # CM 12 500
        cc = self.row(self.generate(), c)
        self.assertEqual(cc.deduction_debt, D('-2000'))
        self.assertEqual(cc.net_ordi, D('14500'))
        self.assertEqual(cc.net_payable, D('12500') + D('2000'))   # 14 500

    def test_bp_debitrice_inchangee_et_epargne_toujours_exclue(self):
        d = make_client(self.node, current_debt=D('1000'))
        ep = make_client(self.node, current_debt=D('-3000'))
        self.invoice(d, 100)
        self.invoice(ep, 0, pay=3000)
        p = self.generate()
        self.assertEqual(self.row(p, d).net_payable, D('12500') - D('1000'))
        self.assertFalse(ClientCommission.objects.filter(period=p, client=ep).exists())
