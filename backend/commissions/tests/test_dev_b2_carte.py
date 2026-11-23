"""
BUG-1104 (B-2, reponse client Q2) : la carte est un montant FIXE par client et par mois (defaut 1 000 FC,
Node.card_fee_fc, a confirmer avec le client). Une seule retenue, portee par la ligne porteuse
(la plus ancienne non payee), au montant de la boulangerie porteuse. Valeurs calculees a la main :
100 pains x 500 FC = 50 000 FC de commande, CM = 12 500 FC. Donnees FICTIVES.
"""
from decimal import Decimal as D

from commissions.models import ClientCommission
from commissions.tests.test_commissions_v5 import COMM, Base5, api
from core.testing import make_client, make_node


class CarteUneFoisParMois(Base5):
    def setUp(self):
        super().setUp()
        # montants propres : Y1 = 700 (Base5), Y2 = 700, Y3 = 700 -> on les differencie
        for n, fee in zip(self.ns, ('1000', '800', '600')):
            n.card_fee_fc = D(fee)
            n.save(update_fields=['card_fee_fc'])
        self.c = make_client(self.ns[0], current_debt=D('0'))

    def rows(self, c=None):
        return list(ClientCommission.objects.filter(client=c or self.c).order_by('created_at', 'pk'))

    def total_carte(self, c=None):
        return sum(r.deduction_prints for r in self.rows(c))

    def test_une_boulangerie_une_carte_et_net_exact(self):
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        (r,) = self.rows()
        self.assertEqual(r.deduction_prints, D('1000.00'))
        self.assertTrue(r.card_applied)
        # 12 500 - (dette 0 + cotisation 1 500 + carte 1 000) = 10 000
        self.assertEqual((r.commission_gross, r.net_payable), (D('12500.00'), D('10000.00')))

    def test_plusieurs_factures_dans_le_mois_une_seule_carte(self):
        for _ in range(3):
            self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        self.gen(self.ns[0])
        (r,) = self.rows()
        self.assertEqual(r.order_value, D('150000.00'))
        self.assertEqual(r.deduction_prints, D('1000.00'))

    def test_trois_boulangeries_une_seule_carte_celle_de_la_porteuse(self):
        for n in self.ns:
            self.inv(n, self.c, 100)
        for n in self.ns:
            self.gen(n)
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(self.total_carte(), D('1000.00'))  # Y1 (porteuse), pas 1000+800+600
        porteuse = [r for r in rows if r.card_applied]
        self.assertEqual(len(porteuse), 1)
        self.assertEqual(porteuse[0].period.node, self.ns[0])
        self.assertEqual(porteuse[0].deduction_prints, D('1000.00'))
        # net = CM - retenues ; somme des nets = 3 x 12 500 - (cotisation 1 500 + carte 1 000)
        self.assertEqual(sum(r.net_payable for r in rows), D('37500.00') - D('1500.00') - D('1000.00'))
        # les colonnes de la situation correspondent
        lignes = api(self.direction).get(COMM, {'client': self.c.pk}).data
        lignes = lignes['results'] if isinstance(lignes, dict) else lignes
        self.assertEqual(sum(D(x['carte_fc']) for x in lignes), D('1000.00'))

    def test_ordre_de_generation_inverse_porteuse_est_la_premiere_generee(self):
        for n in self.ns:
            self.inv(n, self.c, 100)
        for n in (self.ns[2], self.ns[1], self.ns[0]):
            self.gen(n)
        self.assertEqual(self.total_carte(), D('600.00'))  # Y3 genere en premier : sa carte (600)
        self.assertEqual([r.period.node.code for r in self.rows() if r.card_applied], ['Y3'])

    def test_regeneration_n_ajoute_pas_de_carte(self):
        for n in self.ns:
            self.inv(n, self.c, 100)
        for _ in range(2):
            for n in self.ns:
                self.gen(n)
        self.assertEqual(self.total_carte(), D('1000.00'))
        self.assertEqual(sum(1 for r in self.rows() if r.card_applied), 1)

    def test_porteuse_payee_la_carte_reste_et_les_autres_restent_a_zero(self):
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        ClientCommission.objects.filter(client=self.c).update(is_paid=True)
        self.inv(self.ns[1], self.c, 100)
        self.gen(self.ns[1])
        self.gen(self.ns[0])  # regeneration : la ligne payee n'est pas touchee
        rows = self.rows()
        self.assertEqual(self.total_carte(), D('1000.00'))
        self.assertEqual(rows[0].deduction_prints, D('1000.00'))
        self.assertEqual(rows[1].deduction_prints, D('0.00'))

    def test_porteuse_supprimee_la_carte_est_reportee_sur_la_suivante(self):
        for n in self.ns[:2]:
            self.inv(n, self.c, 100)
            self.gen(n)
        r = api(self.direction).delete(f"{COMM}{self.rows()[0].id}/")
        self.assertEqual(r.status_code, 204)
        self.gen(self.ns[1])
        (reste,) = self.rows()
        self.assertEqual(reste.deduction_prints, D('800.00'))  # carte de la nouvelle porteuse (Y2)

    def test_card_fee_zero_aucune_retenue(self):
        for n in self.ns:
            n.card_fee_fc = D('0')
            n.save(update_fields=['card_fee_fc'])
        for n in self.ns[:2]:
            self.inv(n, self.c, 100)
            self.gen(n)
        self.assertEqual(self.total_carte(), D('0.00'))
        self.assertEqual(sum(1 for r in self.rows() if r.card_applied), 1)
        self.assertEqual(sum(r.net_payable for r in self.rows()), D('25000.00') - D('1500.00'))

    def test_changer_card_fee_ne_modifie_pas_les_commissions_generees(self):
        self.inv(self.ns[0], self.c, 100)
        self.gen(self.ns[0])
        self.ns[0].card_fee_fc = D('5000')
        self.ns[0].save(update_fields=['card_fee_fc'])
        self.gen(self.ns[0])  # regeneration du meme mois
        (r,) = self.rows()
        self.assertEqual(r.deduction_prints, D('1000.00'))
        self.assertEqual(r.net_payable, D('10000.00'))
        # un nouveau mois utilise le nouveau montant
        r2 = api(self.direction).post('/api/commissions/periods/generate/',
                                      {'node': self.ns[0].pk, 'month': 3, 'year': 2026}, format='json')
        self.assertEqual(r2.status_code, 201)

    def test_deux_clients_deux_cartes_chacun_la_sienne(self):
        c2 = make_client(self.ns[1], current_debt=D('0'))
        self.inv(self.ns[0], self.c, 100)
        self.inv(self.ns[1], c2, 100)
        self.gen(self.ns[0])
        self.gen(self.ns[1])
        self.assertEqual(self.total_carte(self.c), D('1000.00'))
        self.assertEqual(self.total_carte(c2), D('800.00'))
        self.assertEqual(D(api(self.direction).get(COMM + 'summary/').data['total_carte']), D('1800.00'))

    def test_net_formule_avec_dette_cotisation_carte_trois_boulangeries(self):
        self.c.current_debt = D('4000')
        self.c.save(update_fields=['current_debt'])
        for n in self.ns:
            self.inv(n, self.c, 100)
            self.gen(n)
        # 37 500 - (dette 4 000 + cotisation 1 500 + carte 1 000) = 31 000
        self.assertEqual(sum(r.net_payable for r in self.rows()), D('31000.00'))
        self.assertEqual(sum(r.total_deductions for r in self.rows()), D('6500.00'))
