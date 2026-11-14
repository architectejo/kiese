"""
Vague 4 (testeur-ventes, 2026-11-12) : decision client « Rapport Journalier =
JOUR CALENDAIRE » (BUG-271/272) vue des Ventes et de la Tresorerie, bout en
bout par l'API (facturation -> livraison -> rapport facturier -> cloture de
caisse -> rapport journalier consolide), avec horloge simulee. Donnees
fictives uniquement (base de test).
"""
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import get_config, make_bread_price, make_client, make_node, make_user
from production.models import DailyTeamAssignment
from production.views import _build_daily_closure_report
from sales.models import Invoice
from treasury.models import CashClosure, FacturierReport

D = date(2026, 11, 12)
PREV = date(2026, 11, 11)
OLDER = date(2026, 11, 10)
INV = '/api/sales/invoices/'
TA = '/api/production/team-assignment/'


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


class Base(TestCase):
    rotation = True

    def setUp(self):
        self.node = make_node(code='K1')
        self.node.team_rotation_enabled = self.rotation
        self.node.handover_time = time(12, 0)
        self.node.save()
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='v4_fa')
        self.fa2 = make_user('FACTURIER', node=self.node, team='A', username='v4_fa2')
        self.fb = make_user('FACTURIER', node=self.node, team='B', username='v4_fb')
        self.lv = make_user('LIVREUR', node=self.node, team='A', username='v4_lv')
        self.gerant = make_user('GERANT', node=self.node, team='', username='v4_g')
        self.cl = make_client(self.node)

    def assign(self, d, team):
        return DailyTeamAssignment.objects.create(node=self.node, work_date=d, team=team)

    def sale(self, user=None, qty=2, pay=0, client='default', **extra):
        cl = self.cl if client == 'default' else client
        p = {'payment_type': 'CASH' if pay else 'CREDIT', 'payment_amount': pay,
             'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}
        if cl is not None:
            p['client'] = str(cl.pk)
        p.update(extra)
        return _api(user or self.fa).post(INV, p, format='json')

    def refund(self, amount=300):
        return _api(self.fa).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': amount,
                                        'is_debt_repayment': True, 'lines': []}, format='json')

    def deliver(self, iid, user=None):
        return _api(user or self.lv).post(f'{INV}{iid}/deliver/')


class DatesEtRecusCalendairesTests(Base):
    def test_vente_03h00_jour_calendaire_et_numeros_uniques_par_date(self):
        self.assign(PREV, 'B')
        with _now(23, 50, PREV):
            r0 = self.sale()
        with _now(3, 0):
            r1 = self.sale()
            r2 = self.sale(pay=500)
        self.assertEqual([r0.status_code, r1.status_code, r2.status_code], [201, 201, 201])
        self.assertEqual(r0.data['receipt_number'], 'K1-20261111-0001')
        self.assertEqual(r1.data['receipt_number'], 'K1-20261112-0001')
        self.assertEqual(r2.data['receipt_number'], 'K1-20261112-0002')
        for r, d in ((r0, PREV), (r1, D), (r2, D)):
            self.assertEqual(Invoice.objects.get(pk=r.data['id']).invoice_date, d)
        # equipe de service a 03:00 = periode du 11/11 (releve de 12:00 pas encore passee)
        self.assertEqual(r1.data['team'], 'B')

    def test_releve_12h00_change_equipe_pas_date_ni_serie_de_numeros(self):
        self.assign(PREV, 'B')
        self.assign(D, 'A')
        with _now(11, 59):
            r1 = self.sale()
        with _now(12, 0):
            r2 = self.sale()
        self.assertEqual((r1.data['team'], r2.data['team']), ('B', 'A'))
        self.assertEqual(r1.data['receipt_number'], 'K1-20261112-0001')
        self.assertEqual(r2.data['receipt_number'], 'K1-20261112-0002')

    def test_numeros_uniques_apres_suppression_d_une_facture_expiree(self):
        self.assign(D, 'A')
        with _now(13, 0):
            ids = [self.sale().data['id'] for _ in range(3)]
        Invoice.objects.filter(pk=ids[0]).update(created_at=_at(D, 0, 1))
        with _now(13, 30):
            _api(self.gerant).post(INV + 'cleanup_expired/')  # BUG-284 : reserve GERANT+
            n = self.sale().data['receipt_number']
        nums = list(Invoice.objects.values_list('receipt_number', flat=True))
        self.assertEqual(len(nums), len(set(nums)))
        self.assertIn(n, nums)

    def test_equipe_vente_retroactive_est_celle_de_service_a_l_heure_de_la_vente(self):
        get_config_obj = get_config()
        get_config_obj.allow_backdated_sales = True
        get_config_obj.save()
        self.assign(OLDER, 'A')
        self.assign(PREV, 'B')
        self.assign(D, 'A')
        # maintenant 15:00 le 12/11 : vente datee du 11/11 -> 11/11 15:00 -> periode 11/11 = B
        with _now(15, 0):
            r = self.sale(invoice_date=str(PREV))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['team'], 'B')
        self.assertEqual(r.data['receipt_number'], 'K1-20261111-0001')
        # maintenant 03:00 : vente datee du 11/11 -> 11/11 03:00 -> periode du 10/11 = A
        with _now(3, 0):
            r = self.sale(invoice_date=str(PREV))
        self.assertEqual(r.data['team'], 'A')
        self.assertEqual(r.data['receipt_number'], 'K1-20261111-0002')

    def test_vente_retroactive_sans_designation_ne_bloque_pas_et_prend_l_equipe_du_facturier(self):
        cfg = get_config()
        cfg.allow_backdated_sales = True
        cfg.save()
        self.assign(D, 'A')
        with _now(15, 0):
            r = self.sale(user=self.fb, invoice_date=str(OLDER))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['team'], 'B')


class BlocageEquipeTests(Base):
    def test_facturation_bloquee_tant_que_equipe_non_designee_puis_debloquee(self):
        with _now(15, 0):
            for r in (self.sale(), self.sale(client=None, pay=1000), self.refund(),
                      self.sale(invoice_date=str(D))):
                self.assertEqual(r.status_code, 403, r.data)
                self.assertEqual(r.data['code'], 'TEAM_NOT_ASSIGNED')
            self.assertEqual(Invoice.objects.count(), 0)
            # un livreur ne designe pas l'equipe
            self.assertEqual(_api(self.lv).post(TA, {'team': 'A'}, format='json').status_code, 403)
            r = _api(self.fa).post(TA, {'team': 'B'}, format='json')
            self.assertIn(r.status_code, (200, 201), r.data)
            r = self.sale(user=self.fa)
            self.assertEqual(r.status_code, 201, r.data)
            self.assertEqual(r.data['team'], 'B')          # equipe designee, pas celle du compte (A)
            self.assertEqual(self.refund().status_code, 201)

    def test_a_03h00_la_designation_du_jour_calendaire_ne_vaut_que_pour_la_periode_du_matin(self):
        # periode en cours a 03:00 = celle ouverte le 11/11 a 12:00 ; la designation
        # du 12/11 (releve 12:00) n'est pas encore valable.
        self.assign(D, 'A')
        with _now(3, 0):
            r = self.sale()
            self.assertEqual(r.status_code, 403, r.data)
            self.assertEqual(r.data['code'], 'TEAM_NOT_ASSIGNED')
            ta = _api(self.fa).post(TA, {'team': 'B'}, format='json')
            self.assertIn(ta.status_code, (200, 201), ta.data)
            self.assertEqual(ta.data['work_date'], str(D))      # date calendaire
            self.assertEqual(ta.data['shift_date'], str(PREV))  # periode de service
            r = self.sale()
            self.assertEqual(r.status_code, 201, r.data)
            self.assertEqual(r.data['team'], 'B')
            self.assertEqual(Invoice.objects.get(pk=r.data['id']).invoice_date, D)

    def test_sans_rotation_aucun_blocage_et_equipe_du_compte(self):
        node = make_node(code='K9')
        fx = make_user('FACTURIER', node=node, team='B', username='v4_fx')
        cl = make_client(node)
        with _now(3, 0):
            r = _api(fx).post(INV, {'client': str(cl.pk), 'payment_type': 'CASH', 'payment_amount': 500,
                                    'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['team'], 'B')
        self.assertEqual(r.data['receipt_number'], 'K9-20261112-0001')


class RapportFacturierEtClotureTests(Base):
    def _journee(self):
        """A de 03:00 a 11:59 (periode du 11/11), B apres 12:00 ; 2 ventes chacune, livrees."""
        self.assign(PREV, 'A')
        self.assign(D, 'B')
        ids = {'A': [], 'B': []}
        with _now(3, 0):
            ids['A'].append(self.sale(pay=500).data['id'])
            ids['A'].append(self.sale(qty=4).data['id'])
            for i in ids['A']:
                self.assertEqual(self.deliver(i).status_code, 200)
        with _now(13, 0):
            ids['B'].append(self.sale(user=self.fb, pay=1000).data['id'])
            ids['B'].append(self.sale(user=self.fb, qty=3).data['id'])
            for i in ids['B']:
                self.assertEqual(self.deliver(i).status_code, 200)
        return ids

    def test_un_rapport_facturier_par_equipe_et_date_idempotent_et_cloture_unique(self):
        self._journee()
        g = _api(self.gerant)
        with _now(20, 0):
            r = g.post('/api/treasury/reports/generate/', {}, format='json')
            self.assertEqual(r.status_code, 200, r.content)
            self.assertEqual(sorted((x['team'], x['date']) for x in r.data), [('A', str(D)), ('B', str(D))])
            r = g.post('/api/treasury/reports/generate/', {}, format='json')   # regeneration
            self.assertEqual(FacturierReport.objects.filter(node=self.node, date=D).count(), 2)
            cash = {x['team']: Decimal(x['total_cash_sales']) for x in r.data}
            credit = {x['team']: Decimal(x['total_credit_sales']) for x in r.data}
            self.assertEqual(cash, {'A': Decimal('500'), 'B': Decimal('1000')})
            self.assertEqual(credit, {'A': Decimal('2500'), 'B': Decimal('1500')})
            c = g.post('/api/treasury/closures/', {'date': str(D), 'bills_1000': 1, 'bills_500': 1}, format='json')
            self.assertEqual(c.status_code, 201, c.content)
            self.assertEqual(c.data['date'], str(D))
            self.assertEqual(Decimal(c.data['total_entries']), Decimal('1500'))   # A + B, un seul jour
            self.assertEqual(Decimal(c.data['cash_gap']), Decimal('0'))
            self.assertEqual(g.post('/api/treasury/closures/', {'date': str(D), 'bills_500': 1}, format='json').status_code, 400)
            self.assertEqual(CashClosure.objects.filter(node=self.node).count(), 1)
        with _now(1, 0, D + timedelta(days=1)):
            c2 = g.post('/api/treasury/closures/', {'date': str(D + timedelta(days=1)), 'bills_500': 1}, format='json')
            self.assertEqual(c2.status_code, 201, c2.content)
            self.assertEqual(c2.data['date'], str(D + timedelta(days=1)))   # une cloture par (noeud, date)

    def test_deux_facturiers_meme_equipe_meme_date_un_rapport_par_facturier(self):
        # BUG-273 (decision client) : un rapport par (facturier, equipe, date) ; la
        # cloture de caisse reste unique par (noeud, date) et additionne tout.
        self.assign(D, 'A')
        with _now(13, 0):
            for u in (self.fa, self.fa2):
                i = self.sale(user=u, pay=500).data['id']
                self.assertEqual(self.deliver(i).status_code, 200)
        with _now(20, 0):
            r = _api(self.gerant).post('/api/treasury/reports/generate/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        rows = [x for x in r.data if x['team'] == 'A']
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({x['facturier'] for x in rows}), 2)
        self.assertEqual(sum(Decimal(x['total_cash_sales']) for x in rows), Decimal('1000'))
        with _now(20, 5):
            c = _api(self.gerant).post('/api/treasury/closures/', {'date': str(D), 'bills_500': 2}, format='json')
        self.assertEqual(c.status_code, 201, c.content)
        self.assertEqual(Decimal(c.data['total_entries']), Decimal('1000'))   # somme des deux rapports

    def test_rapport_journalier_consolide_ns_rg_facture_jr_cm(self):
        self.assign(PREV, 'A')
        self.assign(D, 'B')
        other = make_client(self.node)
        with _now(3, 0):
            n1 = self.sale(qty=2, pay=1000).data['id']                       # A : 1000 normal, CM 25 %
            self.deliver(n1)
            ns = self.sale(special_code='NS', qty=3, client=other)
            self.assertEqual(ns.status_code, 201, ns.data)
        with _now(13, 0):
            n2 = self.sale(user=self.fb, qty=4, pay=2000).data['id']          # B : 2000 normal
            self.deliver(n2)
            rg = self.sale(user=self.fb, special_code='RG', qty=1, client=other)
            self.assertEqual(rg.status_code, 201, rg.data)
            self.deliver(rg.data['id'])
            sol = self.sale(user=self.fb, qty=2, is_soldee=True, pay=750)
            self.assertEqual(sol.status_code, 201, sol.data)
            self.deliver(sol.data['id'])
        report = _build_daily_closure_report(self.node, D)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(row['facture_jr'], {'quantity': 6, 'fc': '3000.00'})       # A + B ensemble
        self.assertEqual(Decimal(row['commission_jr']['fc']), Decimal('750.00'))    # 25 % de 3000
        self.assertEqual(row['non_servi']['quantity'], 3)
        self.assertEqual(Decimal(row['non_servi']['fc']), Decimal('1500'))
        self.assertEqual(row['regularisation']['quantity'], 1)
        self.assertEqual(Decimal(row['regularisation']['fc']), Decimal('500'))
        self.assertEqual(row['vente_cash_soldee']['quantity'], 2)
        self.assertEqual(Decimal(row['vente_cash_soldee']['fc']), Decimal('750'))
        # la veille ne contient rien de ce jour
        prev = _build_daily_closure_report(self.node, PREV)
        prow = next(c for c in prev['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(prow['facture_jr']['quantity'], 0)
        # via l'API (gerant) : meme chiffres, une seule fois
        with _now(21, 0):
            r = _api(self.gerant).get('/api/production/daily-closure/', {'date': str(D)})
        self.assertEqual(r.status_code, 200)
        api_row = next(c for c in r.data['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(api_row['facture_jr'], row['facture_jr'])


class FrontiereDeMinuitTests(Base):
    """Facture creee juste avant minuit, livree juste apres."""

    def setUp(self):
        super().setUp()
        self.assign(PREV, 'A')
        self.assign(D, 'B')

    # BUG-274 corrigé
    def test_facture_en_attente_a_23h55_reste_listee_pour_le_livreur_apres_minuit(self):
        with _now(23, 55, PREV):
            iid = self.sale(pay=500).data['id']
        with _now(0, 5):
            r = _api(self.lv).get(INV + 'pending_deliveries/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(iid, [x['id'] for x in r.data])

    def test_livraison_apres_minuit_possible_et_tracee_au_jour_de_la_livraison(self):
        with _now(23, 55, PREV):
            iid = self.sale(pay=500).data['id']
        with _now(0, 5):
            self.assertEqual(self.deliver(iid).status_code, 200)
            r = _api(self.gerant).post('/api/treasury/reports/generate/', {}, format='json')
        inv = Invoice.objects.get(pk=iid)
        self.assertEqual(inv.invoice_date, PREV)
        self.assertEqual(timezone.localtime(inv.delivered_at).date(), D)
        # chiffres releves (pas de regle claire sur le jour de rattachement du cash) :
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([(x['date'], x['total_cash_sales']) for x in r.data], [(str(D), '500.00')])

    def test_vente_solde_exclue_du_credit_de_daily_summary(self):
        # BUG-275 (complément) : la décote d'une VENTE SOLDE n'est jamais une créance.
        with _now(10, 0):
            iid = self.sale(qty=2, pay=500, is_soldee=True).data['id']   # 2 x 75 % du prix, paiement partiel
            self.assertEqual(self.deliver(iid).status_code, 200)
            rows = _api(self.gerant).get(INV + 'daily_summary/', {'date': str(D)}).data
        credit = [r for r in rows if r['payment_type'] == 'CREDIT']
        self.assertTrue(all(Decimal(str(r['total'])) == 0 for r in credit), rows)

    def test_recaps_ventes_et_rapports_s_accordent_sur_le_jour_d_une_facture_livree_apres_minuit(self):
        with _now(23, 55, PREV):
            iid = self.sale(pay=500).data['id']
        with _now(0, 5):
            self.assertEqual(self.deliver(iid).status_code, 200)
            g = _api(self.gerant)
            ds = {d: g.get(INV + 'daily_summary/', {'date': str(d)}).data for d in (PREV, D)}
            bs = {d: g.get(INV + 'bread_summary/', {'date': str(d)}).data['grand_total_qty'] for d in (PREV, D)}
        # `daily_summary` range la facture au 11/11 (invoice_date), `bread_summary`
        # (et le rapport facturier / la cloture) au 12/11 (delivered_at).
        jour_daily = [d for d in (PREV, D) if any(r['count'] for r in ds[d])]
        jour_pains = [d for d in (PREV, D) if bs[d]]
        self.assertEqual(jour_daily, jour_pains)
        self.assertEqual(jour_daily, [D])   # BUG-275 : jour de LIVRAISON
