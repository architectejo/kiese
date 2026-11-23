"""
Commissions - ronde b19 (testeur clients/commissions, 2026-11-23). Verification independante de BUG-1009 et
balayage suppression / regeneration / paiement multi-boulangeries. Valeurs calculees a la main (cotisation 1500,
carte 700, dette 10 000, 100 pains x 500 FC x 0,25 = 12 500 de CM par boulangerie). Donnees FICTIVES.
"""
from decimal import Decimal as D

from commissions.models import ClientCommission
from commissions.tests.test_commissions_v5 import COMM, Base5, api
from core.testing import make_client


class Multi(Base5):
    def setUp(self):
        super().setUp()
        self.c = make_client(self.ns[2], current_debt=D('10000'))
        for n in self.ns:
            self.inv(n, self.c, 100)
        for n in self.ns:
            self.gen(n)

    def rows(self):
        return list(ClientCommission.objects.filter(client=self.c))

    def total(self, field):
        return sum(getattr(r, field) for r in self.rows())

    def carrier(self):
        return ClientCommission.objects.get(client=self.c, deduction_debt=D('10000.00'))

    def delete(self, row):
        r = api(self.direction).delete(f'{COMM}{row.id}/')
        self.assertEqual(r.status_code, 204, getattr(r, 'data', None))

    def test_regeneration_complete_apres_suppression_reporte_une_seule_fois(self):
        self.delete(self.carrier())
        for n in self.ns:
            self.gen(n)
        self.assertEqual(len(self.rows()), 3)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        self.assertEqual(self.total('deduction_social'), D('1500.00'))

    def test_regeneration_de_la_seule_boulangerie_supprimee_reprend_la_retenue(self):
        c = self.carrier()
        node = c.period.node
        self.delete(c)
        self.gen(node)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        self.assertEqual(self.total('deduction_social'), D('1500.00'))

    def test_suppression_d_une_ligne_non_porteuse_ne_change_rien(self):
        non = ClientCommission.objects.filter(client=self.c, deduction_debt=0).first()
        node = non.period.node
        self.delete(non)
        self.gen(node)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        self.assertEqual(sum(1 for r in self.rows() if r.deduction_debt != 0), 1)

    def test_ligne_porteuse_payee_compte_comme_deja_retenu(self):
        c = self.carrier()
        r = api(self.direction).post(f'{COMM}{c.id}/mark_paid/', {}, format='json')
        self.assertIn(r.status_code, (200, 201), getattr(r, 'data', None))
        c.refresh_from_db()
        self.assertTrue(c.is_paid)
        for n in self.ns:
            self.gen(n)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        self.assertEqual(sum(1 for r in self.rows() if r.deduction_debt != 0), 1)

    def test_porteuse_payee_puis_supprimee_les_autres_regenerees_ne_portent_pas(self):
        """Une ligne payee ne se supprime pas ? Sinon la retenue est reportee sur la regeneration."""
        c = self.carrier()
        api(self.direction).post(f'{COMM}{c.id}/mark_paid/', {}, format='json')
        r = api(self.direction).delete(f'{COMM}{c.id}/')
        if r.status_code == 204:
            for n in self.ns:
                self.gen(n)
            self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        else:
            self.assertIn(r.status_code, (400, 403, 409))
            self.assertTrue(ClientCommission.objects.filter(pk=c.pk).exists())

    def test_regeneration_seules_lignes_restantes_sans_recreer_la_supprimee(self):
        """Limite annoncee BUG-1009 : la ligne supprimee n'est pas regeneree, les autres restent a 0.
        La dette BP est alors retenue nulle part et l'API ne le signale pas (aucune alerte, 201)."""
        c = self.carrier()
        gone = c.period.node
        self.delete(c)
        for n in self.ns:
            if n != gone:
                r = self.gen(n)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'),
                         'retenue perdue : aucune ligne ne la porte et aucune alerte')

    def test_manuel_zero_sur_la_porteuse_puis_generation_d_une_nouvelle_ligne_ne_double_pas(self):
        """Comptable met la retenue de la porteuse a 0 a la main (PATCH -> deduction_manual), puis supprime une
        autre ligne et la regenere. BUG-1014 (d54) : la decision manuelle fige le mois, la nouvelle ligne ne
        reprend PAS la retenue (avant d54 elle la reprenait) ; dans tous les cas, jamais de doublon."""
        c = self.carrier()
        api(self.comptable).patch(f'{COMM}{c.id}/', {'deduction_debt': '0', 'deduction_social': '0'}, format='json')
        other = ClientCommission.objects.filter(client=self.c).exclude(pk=c.pk).first()
        node = other.period.node
        self.delete(other)
        self.gen(node)
        self.assertEqual(self.total('deduction_debt'), D('0.00'))
        self.assertEqual(self.total('deduction_social'), D('0.00'))

    def test_net_a_payer_exact_de_chaque_ligne(self):
        for r in self.rows():
            carry = r.deduction_debt != 0
            retenues = D('700') + (D('11500') if carry else D('0'))  # carte + dette 10 000 + sociale 1 500
            self.assertEqual(r.commission_gross, D('12500.00'))
            self.assertEqual(r.net_payable, D('12500.00') - retenues)

    def test_client_sans_dette_ni_cotisation_aucune_porteuse_pas_de_report_fantome(self):
        from clients.models import Client
        from core.models import Node
        n = Node.objects.get(code='Y1')
        n.social_contribution_fc = D('0')
        n.save()
        c2 = make_client(self.ns[0], current_debt=D('0'))
        Client.objects.filter(pk=c2.pk).update(cotisation_sociale=D('0'))
        self.inv(self.ns[0], c2, 10)
        self.inv(self.ns[1], c2, 10)
        self.gen(self.ns[0])
        self.gen(self.ns[1])
        rows = list(ClientCommission.objects.filter(client=c2))
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(r.deduction_debt for r in rows), D('0'))

    def test_bp_creditrice_negative_est_porteuse(self):
        c2 = make_client(self.ns[0], current_debt=D('-3000'))
        for n in self.ns[:2]:
            self.inv(n, c2, 10)
        for n in self.ns[:2]:
            self.gen(n)
        rows = list(ClientCommission.objects.filter(client=c2))
        self.assertEqual(sum(r.deduction_debt for r in rows), D('-3000.00'))
        self.assertEqual(sum(1 for r in rows if r.deduction_debt != 0), 1)
        for n in self.ns[:2]:  # regeneration : toujours une seule porteuse
            self.gen(n)
        rows = list(ClientCommission.objects.filter(client=c2))
        self.assertEqual(sum(1 for r in rows if r.deduction_debt != 0), 1)
