"""
Commissions - ronde b20 (testeur clients/commissions, 2026-11-23) : attaque de l'heuristique de BUG-1011
(boulangerie facturee sans ligne). Valeurs a la main : cotisation 1500, carte 700, dette 10 000.
Donnees FICTIVES.
"""
from decimal import Decimal as D

from commissions.models import ClientCommission, CommissionPeriod
from commissions.tests.test_commissions_v5 import COMM, Base5, api
from core.testing import make_client
from sales.models import Invoice


class Base7(Base5):
    def setUp(self):
        super().setUp()
        self.c = make_client(self.ns[2], current_debt=D('10000'))

    def rows(self):
        return list(ClientCommission.objects.filter(client=self.c))

    def total(self, f):
        return sum(getattr(r, f) for r in self.rows())

    def carrier(self, debt='10000.00'):
        return ClientCommission.objects.get(client=self.c, deduction_debt=D(debt))

    def zero(self, row):
        """Zero decide par la comptabilite : par PATCH (pose deduction_manual), BUG-1014."""
        r = api(self.comptable).patch(f'{COMM}{row.id}/', {'deduction_debt': '0', 'deduction_social': '0'}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))

    def delete(self, row):
        r = api(self.direction).delete(f'{COMM}{row.id}/')
        self.assertEqual(r.status_code, 204, getattr(r, 'data', None))

    def three(self):
        for n in self.ns:
            self.inv(n, self.c, 100)
        for n in self.ns:
            self.gen(n)


class Heuristique(Base7):
    def test_porteuse_supprimee_les_deux_autres_regenerees_reporte(self):
        self.three()
        node = self.carrier().period.node
        self.delete(self.carrier())
        for n in self.ns:
            if n != node:
                self.gen(n)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        self.assertEqual(self.total('deduction_social'), D('1500.00'))

    def test_deux_lignes_supprimees_dont_la_porteuse_une_seule_regeneree(self):
        self.three()
        carrier = self.carrier()
        other = [r for r in self.rows() if r.pk != carrier.pk][0]
        keep = [r for r in self.rows() if r.pk not in (carrier.pk, other.pk)][0]
        self.delete(carrier)
        self.delete(other)
        self.gen(keep.period.node)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        self.assertEqual(len(self.rows()), 1)

    def test_porteuse_supprimee_seule_la_plus_recente_regeneree(self):
        """Seule la plus ancienne ligne non payee reporte : si on ne regenere que la plus recente, la retenue
        n'est reportee nulle part."""
        self.three()
        self.delete(self.carrier())
        remaining = sorted(self.rows(), key=lambda r: (r.created_at, r.pk))
        self.gen(remaining[-1].period.node)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'), 'retenue perdue (BUG-1013)')

    def test_facture_de_la_porteuse_annulee_apres_suppression(self):
        """Cas realiste : la ligne est supprimee PARCE QUE la facture a ete annulee ; on regenere les autres."""
        self.three()
        node = self.carrier().period.node
        self.delete(self.carrier())
        Invoice.objects.filter(node=node, client=self.c).update(status='CANCELLED')
        for n in self.ns:
            if n != node:
                self.gen(n)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'), 'retenue perdue apres annulation')
        self.assertEqual(self.total('deduction_social'), D('1500.00'))

    def test_porteuse_payee_jamais_ecrasee_ni_doublee(self):
        self.three()
        c = self.carrier()
        r = api(self.direction).post(f'{COMM}{c.id}/mark_paid/', {}, format='json')
        self.assertIn(r.status_code, (200, 201))
        for _ in range(2):
            for n in self.ns:
                self.gen(n)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        c.refresh_from_db()
        self.assertEqual(c.deduction_debt, D('10000.00'))

    def test_double_regeneration_apres_report_ne_double_pas(self):
        self.three()
        self.delete(self.carrier())
        for _ in range(3):
            for n in self.ns:
                self.gen(n)
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        self.assertEqual(self.total('deduction_social'), D('1500.00'))
        self.assertEqual(sum(1 for r in self.rows() if r.deduction_debt != 0), 1)

    def test_ligne_a_zero_manuel_toutes_lignes_presentes_conservee(self):
        self.three()
        self.zero(self.carrier())
        for n in self.ns:
            self.gen(n)
        self.assertEqual(self.total('deduction_debt'), D('0.00'))

    def test_zero_manuel_puis_ligne_non_porteuse_supprimee_zero_conserve(self):
        """Compta : retenue mise a 0 a la main (dette reglee). Une autre ligne est supprimee puis regeneration :
        le zero manuel ne doit pas etre ecrase."""
        self.three()
        c = self.carrier()
        self.zero(c)
        victim = [r for r in self.rows() if r.pk != c.pk][0]
        self.delete(victim)
        for n in self.ns:
            self.gen(n)
        self.assertEqual(self.total('deduction_debt'), D('0.00'), 'zero manuel ecrase par le report')

    def test_zero_manuel_et_facture_livree_apres_generation_d_une_autre_boulangerie(self):
        """Y1 generee avant la livraison de la facture du client ; Y2 porteuse puis zero manuel ; regeneration de
        Y2 : le zero manuel doit rester."""
        n1, n2, _ = self.ns
        self.gen(n1)
        self.inv(n1, self.c, 100)
        self.inv(n2, self.c, 100)
        self.gen(n2)
        row = ClientCommission.objects.get(period__node=n2, client=self.c)
        self.assertEqual(row.deduction_debt, D('10000.00'))
        self.zero(row)
        self.gen(n2)
        row.refresh_from_db()
        self.assertEqual(row.deduction_debt, D('0.00'), 'zero manuel ecrase : Y1 facturee sans ligne')

    def test_premiere_generation_du_mois_porte_une_fois(self):
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        self.gen(self.ns[0])
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))
        self.assertEqual(self.total('deduction_social'), D('1500.00'))

    def test_bp_creditrice_reportee_negative(self):
        self.c.current_debt = D('-4000')
        self.c.save(update_fields=['current_debt'])
        self.three()
        self.delete(self.carrier('-4000.00'))
        for n in self.ns:
            self.gen(n)
        self.assertEqual(self.total('deduction_debt'), D('-4000.00'))

    def test_periode_close_ligne_non_supprimable_retenue_intacte(self):
        self.three()
        row = self.carrier()
        CommissionPeriod.objects.filter(pk=row.period_id).update(is_closed=True)
        r = api(self.direction).delete(f'{COMM}{row.id}/')
        self.assertIn(r.status_code, (400, 403, 409))
        self.assertEqual(self.total('deduction_debt'), D('10000.00'))

    def test_net_apres_report_decimal_exact(self):
        self.three()
        self.delete(self.carrier())
        for n in self.ns:
            self.gen(n)
        # CM 12 500 - (dette 10 000 + sociale 1 500 + carte 700) = 300 sur la ligne porteuse
        nets = sorted(r.net_payable for r in self.rows())
        for r in self.rows():
            self.assertIsInstance(r.net_payable, D)
        self.assertIn(D('300.00'), nets)
