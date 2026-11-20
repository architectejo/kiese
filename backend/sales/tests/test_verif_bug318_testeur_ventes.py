"""
Vérification indépendante de BUG-318 (testeur-ventes) : Non servi, livraison
partielle, expiration 12 h. Données fictives uniquement.
"""
import threading
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import BreadStock
from sales.models import Invoice, InvoiceLine
from sales.services import expire_pending_invoices

INV = '/api/sales/invoices/'


class V(TestCase):
    def setUp(self):
        self.node = make_node(code='VA')
        self.other = make_node(code='VB')
        self.bpa = make_bread_price('V318A', 'Pain 500', 500)
        self.bpb = make_bread_price('V318B', 'Pain 300', 300)
        self.fact = make_user('FACTURIER', node=self.node)
        self.liv = make_user('LIVREUR', node=self.node)
        self.ger = make_user('GERANT', node=self.node)
        self.fact_o = make_user('FACTURIER', node=self.other)
        self.dir = make_user('DIRECTION', node=None)
        self.cl = make_client(self.node, credit_limit=Decimal('50000.00'))

    def api(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c

    def mk(self, pay='0.00', ptype='CREDIT', client=True, qa=4, qb=2, user=None, **extra):
        lines = [{'bread_price': b.pk, 'quantity': q}
                 for b, q in ((self.bpa, qa), (self.bpb, qb)) if q > 0]
        p = {'payment_type': ptype, 'payment_amount': pay, 'lines': lines}
        if client:
            p['client'] = str(self.cl.pk)
        p.update(extra)
        r = self.api(user or self.fact).post(INV, p, format='json')
        return r

    def inv(self, *a, **k):
        r = self.mk(*a, **k)
        self.assertEqual(r.status_code, 201, r.data)
        return Invoice.objects.get(pk=r.data['id'])

    def bp(self):
        self.cl.refresh_from_db()
        return self.cl.current_debt

    def sent(self, b=None):
        return sum(BreadStock.objects.filter(node=self.node, bread_price=b or self.bpa)
                   .values_list('qty_sent', flat=True))

    def age(self, i, h):
        Invoice.objects.filter(pk=i.pk).update(created_at=timezone.now() - timedelta(hours=h))

    def ns(self, i, user=None, **b):
        return self.api(user or self.fact).post(f'{INV}{i.pk}/mark-not-served/', b, format='json')

    def dl(self, i, lines=None, user=None):
        b = {} if lines is None else {'lines': lines}
        return self.api(user or self.fact).post(f'{INV}{i.pk}/deliver/', b, format='json')

    def L(self, i, b):
        return i.lines.get(bread_price=b)


class NonServiManuel(V):
    def test_bp_stock_versement_lignes_terminal(self):
        self.cl.current_debt = Decimal('10000'); self.cl.save()
        i = self.inv(pay='1000.00')
        self.assertEqual(self.bp(), Decimal('11600'))
        r = self.ns(i, reason='  absent ')
        self.assertEqual(r.status_code, 200, r.data)
        i.refresh_from_db()
        self.assertEqual(i.status, 'NOT_SERVED')
        self.assertEqual(i.not_served_reason, 'absent')
        self.assertEqual(i.order_total, 0)
        self.assertEqual(i.initial_order_total, Decimal('2600'))
        self.assertEqual(i.payment_amount, Decimal('1000'))
        # BP avant 10000, commande 0, versement 1000 conserve -> 9000
        self.assertEqual(self.bp(), Decimal('9000'))
        self.assertEqual(i.debt_after, Decimal('9000'))
        self.assertEqual(self.sent(), 0)
        self.assertEqual(self.sent(self.bpb), 0)
        self.assertEqual(i.lines.count(), 2)
        for l in i.lines.all():
            self.assertEqual(l.quantity, 0)
            self.assertEqual(l.line_total, 0)
        self.assertEqual(l.ordered_quantity in (4, 2), True)
        self.assertEqual(r.data['status'], 'NOT_SERVED')
        self.assertIn('not_served_at', r.data)

    def test_motif_vide_ou_absent_ok_et_invalide_refuse(self):
        a = self.inv(); self.assertEqual(self.ns(a).status_code, 200)
        b = self.inv(); self.assertEqual(self.ns(b, reason=None).status_code, 200)
        c = self.inv()
        for bad in ('x' * 201, 123, ['a'], {'a': 1}, True):
            r = self.ns(c, reason=bad)
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(Invoice.objects.get(pk=c.pk).status, 'PENDING')
        self.assertEqual(self.ns(c, reason='x' * 200).status_code, 200)

    def test_409_statuts_non_pending(self):
        d = self.inv(); self.dl(d)
        self.assertEqual(self.ns(d).status_code, 409)
        c = self.inv(); self.api(self.fact).post(f'{INV}{c.pk}/cancel/')
        self.assertEqual(self.ns(c).status_code, 409)
        n = self.inv(); self.ns(n)
        r = self.ns(n)
        self.assertEqual(r.status_code, 409); self.assertIn('detail', r.data)
        # la BP n'a bougé qu'une fois : d livree = 2600
        self.assertEqual(self.bp(), Decimal('2600'))

    def test_acces_et_roles(self):
        i = self.inv()
        self.assertEqual(APIClient().post(f'{INV}{i.pk}/mark-not-served/', {}, format='json').status_code, 401)
        self.assertEqual(self.ns(i, user=self.fact_o).status_code, 404)
        self.assertEqual(Invoice.objects.get(pk=i.pk).status, 'PENDING')
        for u in (self.liv, self.ger, self.fact):
            j = self.inv()
            self.assertEqual(self.ns(j, user=u).status_code, 200, u.role)
        self.assertEqual(self.bp(), Decimal('2600'))  # i seule reste

    def test_ns_code_special_et_ajustement_refuses(self):
        n = self.inv(special_code='NS')
        self.assertEqual(self.ns(n).status_code, 400)

    def test_cash_integral_donne_credit_et_soldee_bp_inchangee(self):
        i = self.inv(pay='2600.00', ptype='CASH')
        self.assertEqual(self.bp(), 0)
        self.ns(i)
        self.assertEqual(self.bp(), Decimal('-2600'))
        s = self.inv(pay='1000.00', ptype='CASH', is_soldee=True)
        b = self.bp()
        self.ns(s)
        self.assertEqual(self.bp(), b)
        self.assertEqual(self.sent(), 0)

    def test_client_divers(self):
        i = self.inv(pay='2600.00', ptype='CASH', client=False)
        self.assertEqual(self.sent(), 4)
        self.assertEqual(self.ns(i).status_code, 200)
        i.refresh_from_db()
        self.assertEqual(i.payment_amount, 0)
        self.assertEqual(self.sent(), 0)

    def test_debloque_un_client_au_plafond(self):
        a = self.inv(pay='0.00', qa=100, qb=0)  # 50000 -> BP = plafond
        self.assertEqual(self.bp(), Decimal('50000'))
        self.assertEqual(self.mk().status_code, 403)
        self.ns(a)
        self.assertEqual(self.bp(), 0)
        self.assertEqual(self.mk().status_code, 201)

    def test_non_servi_exclu_deficit_du_mois(self):
        for _ in range(3):
            self.ns(self.inv(qa=60, qb=0))  # 30000 x3, BP revient a 0
        self.assertEqual(self.bp(), 0)
        self.assertEqual(self.mk().status_code, 201)


class LivraisonPartielle(V):
    def test_valeur_bp_stock_cm_recu_prix_fige(self):
        i = self.inv(pay='1000.00')  # 2600
        self.bpa.unit_price = 900; self.bpa.save()  # le catalogue change apres
        la = self.L(i, self.bpa)
        r = self.dl(i, [{'id': la.pk, 'quantity': 1}])
        self.assertEqual(r.status_code, 200, r.data)
        i.refresh_from_db()
        # servi 1x500 + 2x300 = 1100 (prix fige 500, pas 900)
        self.assertEqual(i.order_total, Decimal('1100'))
        self.assertEqual(i.initial_order_total, Decimal('2600'))
        self.assertEqual(i.debt_after, Decimal('100'))
        self.assertEqual(self.bp(), Decimal('100'))
        self.assertEqual((self.sent(), self.sent(self.bpb)), (1, 2))
        self.assertEqual(i.commission_rate, Decimal('0.25'))
        la.refresh_from_db()
        self.assertEqual((la.unit_price, la.quantity, la.ordered_quantity, la.line_total), (500, 1, 4, 500))
        d = r.data
        self.assertEqual(d['order_total'], '1100.00')
        self.assertEqual(d['status'], 'DELIVERED')
        ql = {x['id']: x for x in d['lines']}
        self.assertEqual(ql[la.pk]['quantity'], 1)
        self.assertEqual(ql[la.pk]['ordered_quantity'], 4)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 3)

    def test_soldee_partielle_prix_75_fige(self):
        i = self.inv(pay='0.00', ptype='CASH', is_soldee=True, qa=4, qb=0)
        la = self.L(i, self.bpa)
        self.assertEqual(la.unit_price, 375)
        self.dl(i, [{'id': la.pk, 'quantity': 2}])
        i.refresh_from_db(); la.refresh_from_db()
        self.assertEqual(la.line_total, Decimal('750'))
        self.assertEqual(i.order_total, Decimal('750'))
        self.assertEqual(i.commission_rate, 0)
        self.assertEqual(self.bp(), 0)
        self.assertEqual(self.sent(), 2)

    def test_cm_base_sur_servi(self):
        i = self.inv(pay='0.00')
        self.dl(i, [{'id': self.L(i, self.bpa).pk, 'quantity': 0}])  # servi 600
        now = timezone.now()
        r = self.api(self.dir).post('/api/commissions/periods/generate/',
                                    {'node': str(self.node.pk), 'month': now.month, 'year': now.year}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        from commissions.models import ClientCommission
        cc = ClientCommission.objects.get(client=self.cl)
        self.assertEqual(cc.order_value, Decimal('600'))
        self.assertEqual(cc.commission_gross, Decimal('150'))

    def test_rejets_valeurs_invalides(self):
        i = self.inv()
        la = self.L(i, self.bpa)
        o = self.inv(qa=1, qb=0); fo = o.lines.first()
        bad = [[{'id': la.pk, 'quantity': -1}], [{'id': la.pk, 'quantity': 1.5}],
               [{'id': la.pk, 'quantity': True}], [{'id': la.pk, 'quantity': 5}],
               [{'id': la.pk, 'quantity': 'x'}], [{'id': la.pk, 'quantity': None}],
               [{'id': fo.pk, 'quantity': 0}], [{'id': 99999999, 'quantity': 0}],
               [{'id': la.pk, 'quantity': 1}, {'id': la.pk, 'quantity': 2}],
               [{'id': True, 'quantity': 1}], [{'quantity': 1}], [1], 'x', {'id': la.pk}]
        for b in bad:
            r = self.dl(i, b)
            self.assertEqual(r.status_code, 400, (b, r.data))
        i.refresh_from_db()
        self.assertEqual(i.status, 'PENDING')
        self.assertEqual(self.bp(), Decimal('2600') + Decimal('500'))
        self.assertEqual(self.sent(), 5)
        self.assertEqual(self.L(i, self.bpa).quantity, 4)

    def test_tout_a_zero_refuse(self):
        i = self.inv()
        r = self.dl(i, [{'id': l.pk, 'quantity': 0} for l in i.lines.all()])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Invoice.objects.get(pk=i.pk).status, 'PENDING')

    def test_lignes_omises_servies_en_totalite_et_total_sans_changement(self):
        i = self.inv()
        r = self.dl(i, [{'id': self.L(i, self.bpa).pk, 'quantity': 4}])
        self.assertEqual(r.status_code, 200)
        i.refresh_from_db()
        self.assertIsNone(i.initial_order_total)
        self.assertEqual(self.bp(), Decimal('2600'))
        j = self.inv()
        self.assertEqual(self.dl(j, []).status_code, 200)

    def test_livreur_et_double_livraison_et_autre_noeud(self):
        i = self.inv()
        la = self.L(i, self.bpa)
        self.assertEqual(self.dl(i, [], user=self.fact_o).status_code, 404)
        self.assertEqual(self.dl(i, [{'id': la.pk, 'quantity': 1}], user=self.liv).status_code, 200)
        b = self.bp()
        self.assertEqual(self.dl(i, [{'id': la.pk, 'quantity': 0}]).status_code, 400)
        self.assertEqual(self.bp(), b)
        self.assertEqual(self.sent(), 1)

    def test_versement_superieur_au_servi_cree_credit(self):
        i = self.inv(pay='2600.00', ptype='CASH')
        self.dl(i, [{'id': self.L(i, self.bpa).pk, 'quantity': 0}])  # servi 600
        self.assertEqual(self.bp(), Decimal('-2000'))

    def test_client_divers_paiement_ramene(self):
        i = self.inv(pay='2600.00', ptype='CASH', client=False)
        self.dl(i, [{'id': self.L(i, self.bpa).pk, 'quantity': 0}])
        i.refresh_from_db()
        self.assertEqual((i.order_total, i.payment_amount), (Decimal('600'), Decimal('600')))

    def test_partielle_deficit_mois_sur_servi(self):
        i = self.inv(qa=100, qb=0)  # 50000 -> BP au plafond
        self.dl(i, [{'id': self.L(i, self.bpa).pk, 'quantity': 10}])
        self.assertEqual(self.bp(), Decimal('5000'))
        self.assertEqual(self.mk().status_code, 201)


class Expiration(V):
    def test_lecture_liste_et_pending_deliveries(self):
        a = self.inv(pay='500.00'); self.age(a, 13)
        self.assertEqual(self.api(self.fact).get(INV).status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, 'NOT_SERVED')
        self.assertEqual(a.not_served_reason, 'Expirée automatiquement')
        self.assertEqual(self.bp(), Decimal('-500'))
        self.assertEqual(self.sent(), 0)
        b = self.inv(); self.age(b, 13)
        r = self.api(self.liv).get(INV + 'pending_deliveries/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 0)
        self.assertEqual(Invoice.objects.get(pk=b.pk).status, 'NOT_SERVED')

    def test_limite_12h(self):
        a = self.inv(); self.age(a, 11.9)
        b = self.inv(); self.age(b, 12.1)
        self.assertEqual(expire_pending_invoices(), 1)
        self.assertEqual(Invoice.objects.get(pk=a.pk).status, 'PENDING')
        self.assertEqual(Invoice.objects.get(pk=b.pk).status, 'NOT_SERVED')

    def test_cleanup_ne_supprime_plus_et_idempotent(self):
        a = self.inv(); self.age(a, 13)
        n0 = Invoice.objects.count()
        r = self.api(self.ger).post(INV + 'cleanup_expired/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['expired'], r.data['deleted']), (1, 0))
        self.assertEqual(Invoice.objects.count(), n0)
        self.assertEqual(self.api(self.ger).post(INV + 'cleanup_expired/').data['expired'], 0)
        self.assertEqual(self.bp(), 0)
        self.assertEqual(self.api(self.fact).post(INV + 'cleanup_expired/').status_code, 403)
        self.assertEqual(self.api(self.liv).post(INV + 'cleanup_expired/').status_code, 403)

    def test_commande_de_gestion(self):
        a = self.inv(); self.age(a, 13)
        out = StringIO()
        call_command('expire_pending_invoices', stdout=out)
        call_command('expire_pending_invoices', stdout=out)
        self.assertEqual(Invoice.objects.get(pk=a.pk).status, 'NOT_SERVED')
        self.assertEqual(self.bp(), 0)
        self.assertEqual(self.sent(), 0)
        self.assertTrue(Invoice.objects.filter(pk=a.pk).exists())

    def test_jamais_pour_livree_annulee_ns_remboursement_ajustement(self):
        d = self.inv(); self.dl(d)
        c = self.inv(); self.api(self.fact).post(f'{INV}{c.pk}/cancel/')
        n = self.inv(special_code='NS')
        rb = self.api(self.fact).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH',
                                            'payment_amount': '100.00', 'lines': [],
                                            'is_debt_repayment': True}, format='json')
        self.assertEqual(rb.status_code, 201, rb.data)
        adj = Invoice.objects.filter(pk=d.pk)
        ids = [d.pk, c.pk, n.pk, rb.data['id']]
        Invoice.objects.filter(pk__in=ids).update(created_at=timezone.now() - timedelta(hours=40))
        b = self.bp()
        self.assertEqual(expire_pending_invoices(), 0)
        self.assertEqual(Invoice.objects.get(pk=d.pk).status, 'DELIVERED')
        self.assertEqual(Invoice.objects.get(pk=c.pk).status, 'CANCELLED')
        self.assertEqual(Invoice.objects.get(pk=n.pk).status, 'PENDING')
        self.assertEqual(Invoice.objects.get(pk=rb.data['id']).status, 'DELIVERED')
        self.assertEqual(self.bp(), b)

    def test_perimetre_noeud_et_direction(self):
        a = self.inv(); self.age(a, 13)
        self.api(self.fact_o).get(INV)
        self.assertEqual(Invoice.objects.get(pk=a.pk).status, 'PENDING')
        self.api(self.dir).get(INV)
        self.assertEqual(Invoice.objects.get(pk=a.pk).status, 'NOT_SERVED')

    def test_livraison_expiree_409_puis_stable(self):
        a = self.inv(); self.age(a, 13)
        self.assertEqual(self.dl(a).status_code, 409)
        self.assertEqual(Invoice.objects.get(pk=a.pk).status, 'NOT_SERVED')
        self.assertEqual(self.dl(a).status_code, 409)
        self.assertEqual(self.bp(), 0)
        self.assertEqual(self.sent(), 0)

    def test_soldee_expiree_bp_inchangee(self):
        a = self.inv(pay='0.00', ptype='CASH', is_soldee=True); self.age(a, 13)
        expire_pending_invoices()
        self.assertEqual(self.bp(), 0)
        self.assertEqual(self.sent(), 0)

    def test_ordre_livraison_puis_expiration_et_inverse(self):
        a = self.inv(); self.dl(a); self.age(a, 20)
        self.assertEqual(expire_pending_invoices(), 0)
        self.assertEqual(self.bp(), Decimal('2600'))
        b = self.inv(); self.age(b, 20); expire_pending_invoices()
        self.assertEqual(self.bp(), Decimal('2600'))
        self.assertEqual(self.dl(b).status_code, 409)
        self.assertEqual(self.bp(), Decimal('2600'))


class RegressionsFacturation(V):
    def test_bp_cumulative_et_blocage(self):
        self.inv(pay='1000.00')            # +1600
        self.inv(pay='0.00', qa=2, qb=0)   # +1000
        self.assertEqual(self.bp(), Decimal('2600'))
        self.cl.current_debt = Decimal('49999.00'); self.cl.save()
        self.assertEqual(self.mk(pay='0.00').status_code, 201)  # juste sous le plafond
        self.cl.current_debt = Decimal('50000.00'); self.cl.save()
        r = self.mk(pay='0.00')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.mk(pay='2600.00', ptype='CASH').status_code, 201)

    def test_remboursement_et_codes(self):
        self.inv()
        b = self.bp()
        r = self.api(self.fact).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH',
                                           'payment_amount': '1000.00', 'lines': [],
                                           'is_debt_repayment': True}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.bp(), b - 1000)
        self.assertEqual(self.sent(), 4)  # pas de stock touche
        rg = self.inv(special_code='RG', pay='0.00')
        self.assertEqual(rg.commission_rate, 0)
        ns = self.inv(special_code='NS', pay='0.00')
        self.assertEqual(self.dl(ns).status_code, 400)
        self.assertEqual(self.dl(rg).status_code, 200)


class ConcurrenceDeliverExpire(TransactionTestCase):
    def test_deliver_vs_expire_un_seul_effet(self):
        Config.get_instance()
        node = make_node(code='VC')
        bp = make_bread_price('V318C', 'Pain C', 500)
        fact = make_user('FACTURIER', node=node)
        cl = make_client(node, credit_limit=Decimal('50000'))
        c = APIClient(); c.force_authenticate(fact)
        r = c.post(INV, {'client': str(cl.pk), 'payment_type': 'CREDIT', 'payment_amount': '0.00',
                         'lines': [{'bread_price': bp.pk, 'quantity': 4}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        pk = r.data['id']
        Invoice.objects.filter(pk=pk).update(created_at=timezone.now() - timedelta(hours=13))
        res = []

        def deliver():
            try:
                cc = APIClient(); cc.force_authenticate(fact)
                res.append(cc.post(f'{INV}{pk}/deliver/', {}, format='json').status_code)
            except Exception as e:  # verrou SQLite
                res.append(repr(e))
            finally:
                connections.close_all()

        def expire():
            try:
                expire_pending_invoices()
            except Exception as e:
                res.append(repr(e))
            finally:
                connections.close_all()
        ts = [threading.Thread(target=deliver), threading.Thread(target=expire),
              threading.Thread(target=deliver)]
        [t.start() for t in ts]; [t.join() for t in ts]
        i = Invoice.objects.get(pk=pk)
        cl.refresh_from_db()
        stock = sum(BreadStock.objects.filter(node=node, bread_price=bp).values_list('qty_sent', flat=True))
        # facture expiree : jamais livree, effets appliques une seule fois
        self.assertEqual(i.status, 'NOT_SERVED', res)
        self.assertEqual(cl.current_debt, 0, res)
        self.assertEqual(stock, 0, res)


class RegressionsAnomalies(V):
    def test_bug320_versement_non_servi_dans_le_cash_theorique(self):
        """BUG-320 : le versement conserve d'une facture NOT_SERVED n'entre pas dans le rapport facturier."""
        from treasury.models import FacturierReport
        from treasury.services import regenerate_facturier_reports
        i = self.inv(pay='1000.00')
        self.ns(i)
        regenerate_facturier_reports(self.node, timezone.localdate())
        total = sum(r.total_cash_sales for r in FacturierReport.objects.filter(node=self.node))
        self.assertEqual(total, Decimal('1000'))

    def test_bug321_sync_propage_non_servi(self):
        """BUG-321 : _push_invoice ignore la transition PENDING -> NOT_SERVED."""
        from sync.services import _push_invoice
        i = self.inv()
        _push_invoice(self.node, {'id': str(i.pk), 'status': 'NOT_SERVED'})
        i.refresh_from_db()
        self.assertEqual(i.status, 'NOT_SERVED')

    def test_bug320_non_servi_pas_une_vente_et_cloture_coherente(self):
        """BUG-320 : le versement entre dans le cash, jamais en vente/credit ; la cloture le reprend."""
        from treasury.models import FacturierReport
        from treasury.services import regenerate_facturier_reports
        d = self.inv(pay='2600.00', ptype='CASH')
        self.dl(d)
        i = self.inv(pay='1000.00')
        self.ns(i)
        z = self.inv(pay='0.00')
        self.ns(z)  # sans versement : aucun effet
        regenerate_facturier_reports(self.node, timezone.localdate())
        reps = FacturierReport.objects.filter(node=self.node)
        self.assertEqual(sum(r.total_cash_sales for r in reps), Decimal('3600'))
        self.assertEqual(sum(r.theoretical_cash for r in reps), Decimal('3600'))
        self.assertEqual(sum(r.total_credit_sales for r in reps), 0)
        sold = {}
        for r in reps:
            for k, v in r.breads_sold_by_category.items():
                sold[k] = sold.get(k, 0) + v
        self.assertEqual(sold.get('Pain 500'), 4)  # seule la facture livree

    def test_bug320_non_servi_seul_genere_un_rapport_et_pas_de_double_compte(self):
        from treasury.models import FacturierReport
        from treasury.services import regenerate_facturier_reports
        self.ns(self.inv(pay='700.00'))
        regenerate_facturier_reports(self.node, timezone.localdate())
        regenerate_facturier_reports(self.node, timezone.localdate())  # idempotent
        reps = FacturierReport.objects.filter(node=self.node)
        self.assertEqual(sum(r.total_cash_sales for r in reps), Decimal('700'))

    def test_bug320_commissions_ignorent_la_valeur_non_servie(self):
        self.ns(self.inv(pay='1000.00'))
        now = timezone.now()
        self.api(self.dir).post('/api/commissions/periods/generate/',
                                {'node': str(self.node.pk), 'month': now.month, 'year': now.year}, format='json')
        from commissions.models import ClientCommission
        self.assertFalse(ClientCommission.objects.filter(client=self.cl, order_value__gt=0).exists())

    def test_bug321_sync_propage_quantites_reduites_et_champs(self):
        from sync.services import _push_invoice, _push_invoice_line
        i = self.inv(pay='1000.00')
        la = self.L(i, self.bpa)
        _push_invoice(self.node, {
            'id': str(i.pk), 'status': 'NOT_SERVED', 'order_total': '0.00',
            'initial_order_total': '2600.00', 'payment_amount': '1000.00',
            'not_served_reason': 'absent', 'not_served_at': timezone.now().isoformat(),
        })
        _push_invoice_line(self.node, {'id': la.pk, 'invoice': str(i.pk),
                                       'bread_price': self.bpa.pk, 'quantity': 0, 'ordered_quantity': 4})
        i.refresh_from_db(); la.refresh_from_db()
        self.assertEqual(i.status, 'NOT_SERVED')
        self.assertEqual(i.order_total, 0)
        self.assertEqual(i.initial_order_total, Decimal('2600'))
        self.assertEqual(i.not_served_reason, 'absent')
        self.assertEqual((la.quantity, la.ordered_quantity, la.line_total, la.unit_price), (0, 4, 0, 500))
        # jamais de regression depuis un statut terminal
        _push_invoice(self.node, {'id': str(i.pk), 'status': 'DELIVERED'})
        i.refresh_from_db()
        self.assertEqual(i.status, 'NOT_SERVED')
