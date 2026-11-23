"""Dev B (d15) : non-regression BUG-674/675/676/677 (remarque.md, demande 4). Donnees fictives."""
from datetime import date as ddate, timedelta
from decimal import Decimal as Dc

from core.models import ExpenseCategory
from core.testing import make_client
from production.models import BreadDisposal, ProductionSession
from production.tests.test_verif_a4_testeur_production import TBase, cl


def _rows(r):
    return r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data


class Bug674JournalSortiesParDate(TBase):
    def test_disposals_filtrables_par_date_de_fournee(self):
        today, yest = ddate.today(), ddate.today() - timedelta(days=1)
        for d, qty in ((today, 3), (yest, 5)):
            s = ProductionSession.objects.create(node=self.k1, date=d, team='A', flour_sacks_used=Dc('1'))
            BreadDisposal.objects.create(node=self.k1, session=s, bread_price=self.b3,
                                         disposal_type='UNSOLD', quantity=qty, unit_price_sold=300)
        r = cl(self.g1).get('/api/production/disposals/', {'date': str(yest)})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([x['quantity'] for x in _rows(r)], [5])
        r = cl(self.g1).get('/api/production/disposals/', {'date_from': str(yest), 'date_to': str(today)})
        self.assertEqual(len(_rows(r)), 2)
        self.assertEqual(cl(self.g1).get('/api/production/disposals/', {'date': '2026-13-45'}).status_code, 400)


class Bug675TransfertsDansCloture(TBase):
    def _total(self, user):
        r = cl(user).get('/api/production/daily-closure/', {'date': str(ddate.today())})
        self.assertEqual(r.status_code, 200, r.content)
        row = next(c for c in r.data['categories'] if c['bread_price'] == self.b3.pk)
        return Dc(row['facture_mvm_interne']['fc'])

    def test_emettrice_plus_receptrice_moins(self):
        avant_k1, avant_k2 = self._total(self.g1), self._total(self.g2)
        r = self.send([self.L(self.b3, 10)])
        self.assertEqual(r.status_code, 201, r.content)
        c = self.confirm(r.data['id'], [self.L(self.b3, 10, 'quantity_received')])
        self.assertEqual(c.status_code, 200, c.content)
        self.assertEqual(self._total(self.g1) - avant_k1, Dc('3000'))   # envoyes = vendus
        self.assertEqual(self._total(self.g2) - avant_k2, Dc('-3000'))  # recus retranches


class Bug676RepartitionZero(TBase):
    def test_repartition_pas_a_zero_quand_produit_vide(self):
        client = make_client(self.k1, credit_limit=Dc('900000'))
        r = cl(self.fac).post('/api/sales/invoices/', {
            'payment_type': 'CASH', 'payment_amount': '14000', 'client': str(client.pk),
            'lines': [{'bread_price': self.b3.pk, 'quantity': 30}, {'bread_price': self.b5.pk, 'quantity': 10}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        d = cl(self.fac).post(f"/api/sales/invoices/{r.data['id']}/deliver/")
        self.assertEqual(d.status_code, 200, d.content)
        rep = cl(self.g1).get('/api/production/daily-closure/', {'date': str(ddate.today())})
        self.assertEqual(rep.status_code, 200, rep.content)
        t = rep.data['totals']
        pcts = {x['bread_price']: Dc(x['pct']) for x in t['repartition_pct_par_quantite']}
        self.assertEqual((pcts[self.b3.pk], pcts[self.b5.pk]), (Dc('75.00'), Dc('25.00')))
        vals = {x['bread_price']: Dc(x['pct']) for x in t['repartition_pct_par_valeur']}
        self.assertEqual(vals[self.b3.pk], Dc('64.29'))  # 9000 / 14000
        self.assertNotEqual(t['repartition_base'], 'produit')


class Bug677CategoriesDepensesParPortee(TBase):
    def test_portee_direction_invisible_et_refusee_aux_boulangeries(self):
        d = ExpenseCategory.objects.create(code='DIRX', label='Direction seule', scope='DIRECTION')
        b = ExpenseCategory.objects.create(code='BAKX', label='Boulangerie seule', scope='BAKERY')
        ids = [x['id'] for x in _rows(cl(self.g1).get('/api/core/expense-categories/'))]
        self.assertIn(b.pk, ids)
        self.assertNotIn(d.pk, ids)
        ids = [x['id'] for x in _rows(cl(self.dir).get('/api/core/expense-categories/'))]
        self.assertIn(d.pk, ids)
        body = {'description': 'x', 'amount': '1000', 'date': str(ddate.today())}
        r = cl(self.g1).post('/api/treasury/expenses/', dict(body, category=d.pk), format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = cl(self.g1).post('/api/treasury/expenses/', dict(body, category=b.pk), format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def test_portee_modifiable_par_le_siege_seulement(self):
        c = ExpenseCategory.objects.create(code='SCP', label='Portee')
        self.assertEqual(c.scope, 'BOTH')
        url = f'/api/core/expense-categories/{c.pk}/'
        self.assertEqual(cl(self.g1).patch(url, {'scope': 'DIRECTION'}, format='json').status_code, 403)
        r = cl(self.dir).patch(url, {'scope': 'DIRECTION'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['scope'], 'DIRECTION')
