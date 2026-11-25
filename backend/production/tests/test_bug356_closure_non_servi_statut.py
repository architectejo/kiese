"""
BUG-356 (remarque.md « Non Servi » non comptabilisé dans la Clôture Journalière) :
les factures au statut NOT_SERVED (BUG-318) du jour de travail (`not_served_at`)
alimentent `categories[].non_servi_jour` et `totals.non_servi_*`, sans entrer
dans les ventes / le produit / le facturé. Données fictives.
"""
from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice

URL = '/api/production/daily-closure/'
URL_CLIENTS = '/api/production/daily-closure/clients/'


def _aware(d, hour=10, minute=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, hour, minute), timezone.get_current_timezone())


class Base(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.other = make_node()
        self.bp300 = make_bread_price('B350_300', 'Pain 300 FC', 300)
        self.bp500 = make_bread_price('B350_500', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node)
        self.fact_a = make_user('FACTURIER', node=self.node, team='A')
        self.fact_b = make_user('FACTURIER', node=self.node, team='B')
        self.client1 = make_client(self.node, credit_limit=Decimal('900000.00'))
        self.today = timezone.localdate()
        self.g = APIClient(); self.g.force_authenticate(self.gerant)

    def _api(self, user):
        c = APIClient(); c.force_authenticate(user)
        return c

    def create(self, lines=((300, 10),), payment='0.00', code='', user=None, node_user=None):
        api = self._api(user or self.fact_a)
        bps = {300: self.bp300, 500: self.bp500}
        r = api.post('/api/sales/invoices/', {
            'payment_type': 'CREDIT', 'payment_amount': payment, 'special_code': code,
            'client': str(self.client1.pk),
            'lines': [{'bread_price': bps[p].pk, 'quantity': q} for p, q in lines],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def non_servi(self, inv_id, user=None):
        r = self._api(user or self.fact_a).post(f'/api/sales/invoices/{inv_id}/mark-not-served/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def deliver(self, inv_id, user=None):
        r = self._api(user or self.fact_a).post(f'/api/sales/invoices/{inv_id}/deliver/')
        self.assertEqual(r.status_code, 200, r.data)

    def report(self, day=None, api=None):
        r = (api or self.g).get(URL, {'date': str(day or self.today)})
        self.assertEqual(r.status_code, 200, r.data)
        rows = {x['bread_price']: x for x in r.data['categories']}
        return r.data, rows[self.bp300.pk], rows[self.bp500.pk]


class NonServiStatutTests(Base):
    def test_total_une_categorie_et_plusieurs_categories(self):
        self.non_servi(self.create(((300, 10), (500, 4))))
        self.non_servi(self.create(((300, 2),)))
        data, r300, r500 = self.report()
        self.assertEqual(r300['non_servi_jour'], {'quantity': 12, 'fc': '3600.00'})
        self.assertEqual(r500['non_servi_jour'], {'quantity': 4, 'fc': '2000.00'})
        t = data['totals']
        self.assertEqual((t['non_servi_fc'], t['non_servi_quantity'], t['non_servi_total_fc']), ('5600.00', 16, '5600.00'))

    def test_valeur_au_prix_fige_meme_si_le_catalogue_change(self):
        inv = self.create(((300, 10),))
        self.non_servi(inv)
        self.bp300.unit_price = 999
        self.bp300.save()
        _d, r300, _r = self.report()
        self.assertEqual(r300['non_servi_jour'], {'quantity': 10, 'fc': '3000.00'})

    def test_non_servi_partiel_une_ligne_deja_reduite_compte_le_commande_initial(self):
        inv = self.create(((300, 10), (500, 4)))
        self.non_servi(inv)
        Invoice.objects.get(pk=inv)  # existe, statut NOT_SERVED
        line = Invoice.objects.get(pk=inv).lines.get(bread_price=self.bp500)
        self.assertEqual((line.quantity, line.ordered_quantity), (0, 4))
        # ordered_quantity absent (anciennes données) : repli sur la quantité
        type(line).objects.filter(pk=line.pk).update(ordered_quantity=None, quantity=3)
        _d, r300, r500 = self.report()
        self.assertEqual(r300['non_servi_jour']['quantity'], 10)
        self.assertEqual(r500['non_servi_jour'], {'quantity': 3, 'fc': '1500.00'})

    def test_exclu_des_ventes_produit_et_facture_et_total_du_jour_inchange(self):
        d_ok = self.create(((300, 5),))
        self.deliver(d_ok)
        avant, a300, _ = self.report()
        self.non_servi(self.create(((300, 10), (500, 4))))
        apres, p300, p500 = self.report()
        self.assertEqual(p300['facture_jr'], a300['facture_jr'])
        self.assertEqual(p300['produit'], a300['produit'])
        self.assertEqual(p300['vente_cash_soldee']['quantity'], 0)
        self.assertEqual(p500['facture_jr'], {'quantity': 0, 'fc': '0.00'})
        self.assertEqual(p300['non_servi'], a300['non_servi'])  # NS code spécial inchangé
        self.assertEqual(p300['facture_mvm_interne'], a300['facture_mvm_interne'])
        for k in ('total_du_jour_fc', 'total_breads_billed', 'ecart_facture_fc', 'net_produit_fc'):
            self.assertEqual(apres['totals'][k], avant['totals'][k], k)

    def test_code_special_ns_inchange_et_non_double_compte(self):
        self.create(((300, 10),), code='NS')  # PENDING, code spécial
        self.non_servi(self.create(((300, 4),)))
        data, r300, _ = self.report()
        self.assertEqual(r300['non_servi'], {'quantity': 10, 'fc': '3000.00', 'fc_signe': '-3000.00'})
        self.assertEqual(r300['non_servi_jour'], {'quantity': 4, 'fc': '1200.00'})
        self.assertEqual(r300['facture_mvm_interne'], {'fc': '-3000.00'})  # seul le code NS retranche
        self.assertEqual(data['totals']['non_servi_fc'], '1200.00')
        self.assertEqual(data['totals']['non_servi_total_fc'], '4200.00')

    def test_jour_de_travail_et_minuit(self):
        # Q-018 (2026-11-24) : la journee va de midi a midi (et non plus de minuit a minuit).
        # 11:59 le 15 -> journee du 14 ; 12:00 le 15 -> journee du 15 ; minuit n'est plus une frontiere.
        inv = self.create(((300, 10),))
        self.non_servi(inv)
        day = date(2026, 10, 14)
        Invoice.objects.filter(pk=inv).update(not_served_at=_aware(date(2026, 10, 15), 11, 59))
        self.assertEqual(self.report(day)[1]['non_servi_jour']['quantity'], 10)
        self.assertEqual(self.report(date(2026, 10, 15))[1]['non_servi_jour']['quantity'], 0)
        Invoice.objects.filter(pk=inv).update(not_served_at=_aware(date(2026, 10, 15), 12, 0))
        self.assertEqual(self.report(day)[1]['non_servi_jour']['quantity'], 0)
        self.assertEqual(self.report(date(2026, 10, 15))[1]['non_servi_jour']['quantity'], 10)

    def test_date_de_creation_ne_compte_pas_seule_not_served_at_fait_foi(self):
        inv = self.create(((300, 10),))
        self.non_servi(inv)
        Invoice.objects.filter(pk=inv).update(invoice_date=date(2026, 1, 1))
        self.assertEqual(self.report()[1]['non_servi_jour']['quantity'], 10)

    def test_pending_annule_et_livre_ne_comptent_pas(self):
        self.create(((300, 10),))  # PENDING
        self.deliver(self.create(((300, 3),)))
        c = self.create(((300, 2),))
        Invoice.objects.filter(pk=c).update(status=Invoice.Status.CANCELLED)
        self.assertEqual(self.report()[0]['totals']['non_servi_quantity'], 0)

    def test_equipes_a_et_b_cumulees_et_filtre_equipe_cote_clients(self):
        self.non_servi(self.create(((300, 5),), user=self.fact_a), user=self.fact_a)
        self.non_servi(self.create(((300, 7),), user=self.fact_b), user=self.fact_b)
        self.assertEqual(self.report()[1]['non_servi_jour']['quantity'], 12)
        for team, n in (('A', 1), ('B', 1)):
            r = self.g.get(URL_CLIENTS, {'date': str(self.today), 'team': team})
            self.assertEqual(r.data['non_servis']['count'], n)

    def test_isolation_noeud(self):
        other_fact = make_user('FACTURIER', node=self.other, team='A')
        other_client = make_client(self.other, credit_limit=Decimal('900000.00'))
        r = self._api(other_fact).post('/api/sales/invoices/', {
            'payment_type': 'CREDIT', 'payment_amount': '0.00', 'client': str(other_client.pk),
            'lines': [{'bread_price': self.bp300.pk, 'quantity': 20}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.non_servi(r.data['id'], user=other_fact)
        self.non_servi(self.create(((300, 1),)))
        data, r300, _ = self.report()
        self.assertEqual(r300['non_servi_jour']['quantity'], 1)
        self.assertEqual(data['totals']['non_servi_quantity'], 1)
        # un gérant d'une autre boulangerie ne voit pas ce nœud
        g2 = self._api(make_user('GERANT', node=self.other))
        _d, o300, _ = self.report(api=g2)
        self.assertEqual(o300['non_servi_jour']['quantity'], 20)

    def test_coherence_avec_daily_closure_clients(self):
        self.non_servi(self.create(((300, 5),)))
        self.non_servi(self.create(((500, 2),)))
        self.create(((300, 9),), code='NS')
        data, _a, _b = self.report()
        c = self.g.get(URL_CLIENTS, {'date': str(self.today)})
        self.assertEqual(c.status_code, 200, c.data)
        self.assertEqual(c.data['non_servis']['count'], 3)  # 2 statut + 1 code NS
        self.assertEqual(data['totals']['non_servi_total_fc'], str(Decimal('1500') + Decimal('1000') + Decimal('2700')) + '.00')
        self.assertEqual(c.data['totals']['order_value'], Decimal('0.00'))

    def test_versement_conserve_ne_change_pas_le_non_servi(self):
        self.non_servi(self.create(((300, 10),), payment='1000.00'))
        _d, r300, _ = self.report()
        self.assertEqual(r300['non_servi_jour'], {'quantity': 10, 'fc': '3000.00'})
