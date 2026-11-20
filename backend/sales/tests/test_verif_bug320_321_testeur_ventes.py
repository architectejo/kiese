"""Vérification indépendante BUG-320 (cash théorique d'un « Non servi » avec versement)
et BUG-321 (sync : PENDING -> NOT_SERVED, quantités réduites). testeur-ventes, 2026-11-20."""
from datetime import timedelta
from unittest import expectedFailure
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import BreadStock
from sales.models import Invoice, InvoiceLine
from treasury.models import CashClosure, FacturierReport
from treasury.services import regenerate_facturier_reports

INV = '/api/sales/invoices/'
D = Decimal


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='WA')
        self.bpa = make_bread_price('W320A', 'Pain 500', 500)
        self.bpb = make_bread_price('W320B', 'Pain 300', 300)
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='w_fa')
        self.fb = make_user('FACTURIER', node=self.node, team='B', username='w_fb')
        self.ger = make_user('GERANT', node=self.node, username='w_ger')
        self.dir = make_user('DIRECTION', node=None, username='w_dir')
        self.cl = make_client(self.node, credit_limit=D('50000.00'))
        self.today = timezone.localdate()

    def api(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c

    def mk(self, user=None, pay='0.00', ptype='CREDIT', client=True, qa=4, qb=2, **extra):
        lines = [{'bread_price': b.pk, 'quantity': q} for b, q in ((self.bpa, qa), (self.bpb, qb)) if q > 0]
        p = {'payment_type': ptype, 'payment_amount': pay, 'lines': lines}
        if client:
            p['client'] = str(self.cl.pk)
        p.update(extra)
        r = self.api(user or self.fa).post(INV, p, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return Invoice.objects.get(pk=r.data['id'])

    def ns(self, i, user=None):
        r = self.api(user or self.fa).post(f'{INV}{i.pk}/mark-not-served/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        return r

    def dl(self, i, user=None):
        r = self.api(user or self.fa).post(f'{INV}{i.pk}/deliver/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def regen(self, d=None):
        regenerate_facturier_reports(self.node, d or self.today)
        return {(r.facturier_id, r.team): r for r in FacturierReport.objects.filter(node=self.node, date=d or self.today)}

    def bp(self):
        self.cl.refresh_from_db()
        return self.cl.current_debt


class Bug320Cash(Base):
    def test_livree_plus_non_servi_par_facturier_et_equipe(self):
        d = self.mk(self.fa, pay='2600.00', ptype='CASH')  # 4*500+2*300 = 2600
        self.dl(d)
        n = self.mk(self.fa, pay='1000.00')
        self.ns(n)
        nb = self.mk(self.fb, pay='400.00')
        self.ns(nb)
        reps = self.regen()
        ra, rb = reps[(self.fa.pk, 'A')], reps[(self.fb.pk, 'B')]
        self.assertEqual(ra.total_cash_sales, D('3600'))
        self.assertEqual(ra.theoretical_cash, D('3600'))
        self.assertEqual(ra.total_credit_sales, 0)
        self.assertEqual(rb.total_cash_sales, D('400'))
        self.assertEqual(rb.theoretical_cash, D('400'))
        self.assertEqual(rb.total_credit_sales, 0)
        self.assertEqual(rb.breads_sold_by_category, {})
        self.assertEqual(ra.breads_sold_by_category, {'Pain 500': 4, 'Pain 300': 2})
        self.assertEqual(ra.sacks_value_gap, D('2600'))  # valeur realisee = livree seule

    def test_non_servi_seul_cree_un_rapport(self):
        self.ns(self.mk(pay='700.00'))
        reps = self.regen()
        self.assertEqual(len(reps), 1)
        r = list(reps.values())[0]
        self.assertEqual((r.total_cash_sales, r.theoretical_cash, r.total_credit_sales), (D('700'), D('700'), 0))
        self.assertEqual(r.sacks_value_gap, 0)

    def test_non_servi_sans_versement_ne_cree_rien(self):
        self.ns(self.mk(pay='0.00'))
        self.assertEqual(self.regen(), {})

    def test_client_divers_non_servi_aucun_cash(self):
        """Client divers : le versement est ramene a la valeur servie (0) -> aucun cash."""
        i = self.mk(client=False, pay='2600.00', ptype='CASH')
        self.ns(i)
        i.refresh_from_db()
        self.assertEqual(i.payment_amount, 0)
        self.assertEqual(self.regen(), {})

    def test_rg_et_ns_exclus(self):
        # RG : regularisation (paiement d'une dette) ; NS code special : jamais livrable
        self.cl.current_debt = D('5000'); self.cl.save()
        ns_code = self.api(self.fa).post(INV, {
            'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': '0.00',
            'special_code': 'NS', 'lines': [{'bread_price': self.bpa.pk, 'quantity': 2}]}, format='json')
        self.assertEqual(ns_code.status_code, 201, ns_code.data)
        self.assertEqual(self.regen(), {})
        # Un RG force en NOT_SERVED par la base ne doit pas entrer non plus dans le cash.
        inv = Invoice.objects.get(pk=ns_code.data['id'])
        Invoice.objects.filter(pk=inv.pk).update(
            status='NOT_SERVED', payment_amount=D('900'), not_served_at=timezone.now())
        self.assertEqual(self.regen(), {})
        Invoice.objects.filter(pk=inv.pk).update(special_code='RG')
        self.assertEqual(self.regen(), {})

    def test_regeneration_idempotente(self):
        self.ns(self.mk(pay='700.00'))
        d = self.mk(pay='2600.00', ptype='CASH')
        self.dl(d)
        for _ in range(3):
            self.regen()
        reps = FacturierReport.objects.filter(node=self.node, date=self.today)
        self.assertEqual(reps.count(), 1)
        self.assertEqual(reps[0].total_cash_sales, D('3300'))
        self.assertEqual(reps[0].theoretical_cash, D('3300'))

    def test_date_est_not_served_at(self):
        i = self.mk(pay='700.00')
        self.ns(i)
        yday = self.today - timedelta(days=1)
        Invoice.objects.filter(pk=i.pk).update(not_served_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self.regen(self.today), {})
        reps = self.regen(yday)
        self.assertEqual(list(reps.values())[0].total_cash_sales, D('700'))

    def test_sans_effet_sur_credit_pains_valeur_cm_finance(self):
        i = self.mk(pay='1000.00')
        self.assertEqual(self.bp(), D('1600'))  # 2600 - 1000
        self.ns(i)
        bp_ns = self.bp()
        self.assertEqual(bp_ns, D('-1000'))  # versement conserve, rien commande
        sent = sum(BreadStock.objects.filter(node=self.node).values_list('qty_sent', flat=True))
        self.regen()
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, bp_ns)
        self.assertEqual(sum(BreadStock.objects.filter(node=self.node).values_list('qty_sent', flat=True)), sent)
        self.assertEqual(sent, 0)
        i.refresh_from_db()
        self.assertEqual(i.order_total, 0)
        self.assertEqual(sum(l.line_total for l in i.lines.all()), 0)
        # CM
        from commissions.models import ClientCommission
        now = timezone.now()
        r = self.api(self.dir).post('/api/commissions/periods/generate/',
                                    {'node': str(self.node.pk), 'month': now.month, 'year': now.year}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        self.assertFalse(ClientCommission.objects.filter(client=self.cl, order_value__gt=0).exists())
        self.assertFalse(ClientCommission.objects.filter(client=self.cl, commission_gross__gt=0).exists())
        # total_payments du recapitulatif de periode
        h = self.api(self.dir).get('/api/commissions/periods/history/', {'node': str(self.node.pk)})
        self.assertEqual(h.status_code, 200)
        row = [x for x in h.data if x['month'] == now.month and x['year'] == now.year][0]
        self.assertEqual(D(row['total_payments']), D('1000'))
        self.assertEqual(D(row['total_orders']), 0)
        self.assertEqual(D(row['total_cm']), 0)
        # finance : aucun produit pour une facture non servie
        from sales.models import InvoiceLine as IL
        self.assertEqual(
            sum(l.line_total for l in IL.objects.filter(invoice__node=self.node, invoice__status='DELIVERED')), 0)

    def test_commissions_total_payments_livree_plus_non_servi(self):
        d = self.mk(pay='2600.00', ptype='CASH')
        self.dl(d)
        self.ns(self.mk(pay='1000.00'))
        now = timezone.now()
        self.api(self.dir).post('/api/commissions/periods/generate/',
                                {'node': str(self.node.pk), 'month': now.month, 'year': now.year}, format='json')
        h = self.api(self.dir).get('/api/commissions/periods/history/', {'node': str(self.node.pk)})
        row = [x for x in h.data if x['month'] == now.month][0]
        self.assertEqual(D(row['total_payments']), D('3600'))
        self.assertEqual(D(row['total_orders']), D('2600'))

    def test_pending_et_annulee_ne_comptent_pas(self):
        self.mk(pay='500.00')  # PENDING
        c = self.mk(pay='800.00')
        r = self.api(self.fa).post(f'{INV}{c.pk}/cancel/', {}, format='json')
        self.assertIn(r.status_code, (200, 204, 400, 403), r.data)
        reps = self.regen()
        for rep in reps.values():
            self.assertEqual(rep.total_cash_sales, 0)

    def test_cloture_et_livre_de_caisse(self):
        from treasury.models import CashbookEntry
        d = self.mk(pay='2600.00', ptype='CASH')
        self.dl(d)
        self.ns(self.mk(pay='1000.00'))
        gen = self.api(self.ger).post('/api/treasury/reports/generate/', {'date': self.today.isoformat()}, format='json')
        self.assertEqual(gen.status_code, 200, gen.content)
        r = self.api(self.ger).post('/api/treasury/closures/', {
            'date': self.today.isoformat(), 'bills_1000': 3, 'bills_500': 1, 'bills_100': 1}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        cl = CashClosure.objects.get(pk=r.json()['id'])
        self.assertEqual(cl.total_entries, D('3600'))
        self.assertEqual(cl.net_cash, D('3600'))
        self.assertEqual(cl.physical_cash_total, D('3600'))
        self.assertEqual(cl.cash_gap, 0)
        comptable = make_user('COMPTABLE', node=None, username='w_cpt')
        v = self.api(comptable).post(f'/api/treasury/closures/{cl.pk}/validate/', {}, format='json')
        self.assertEqual(v.status_code, 200, v.content)
        p = self.api(comptable).post(f'/api/treasury/closures/{cl.pk}/push_to_cashbook/', {}, format='json')
        self.assertEqual(p.status_code, 201, p.content)
        e = CashbookEntry.objects.get(source_closure=cl)
        self.assertEqual(e.running_balance, D('3600'))
        chk = self.api(comptable).get('/api/treasury/cashbook/integrity_check/')
        self.assertTrue(chk.json()['chain_valid'])


class Bug321Sync(Base):
    def push_inv(self, rec):
        from sync.services import _push_invoice
        return _push_invoice(self.node, rec)

    def push_line(self, rec):
        from sync.services import _push_invoice_line
        return _push_invoice_line(self.node, rec)

    def test_pending_vers_non_servi_et_champs(self):
        i = self.mk(pay='1000.00')
        la = i.lines.get(bread_price=self.bpa)
        nsat = timezone.now()
        rec = {'id': str(i.pk), 'status': 'NOT_SERVED', 'order_total': '0.00', 'initial_order_total': '2600.00',
               'payment_amount': '1000.00', 'debt_after': '-1000.00', 'not_served_reason': 'absent',
               'not_served_at': nsat.isoformat()}
        self.push_inv(rec)
        self.push_line({'id': la.pk, 'invoice': str(i.pk), 'bread_price': self.bpa.pk,
                        'quantity': 0, 'ordered_quantity': 4})
        i.refresh_from_db(); la.refresh_from_db()
        self.assertEqual(i.status, 'NOT_SERVED')
        self.assertEqual((i.order_total, i.initial_order_total, i.payment_amount), (0, D('2600'), D('1000')))
        self.assertEqual(i.not_served_reason, 'absent')
        self.assertIsNotNone(i.not_served_at)
        self.assertEqual((la.quantity, la.ordered_quantity, la.line_total, la.unit_price), (0, 4, 0, 500))

    def test_prix_fige_malgre_prix_dans_le_payload_et_catalogue_modifie(self):
        i = self.mk(pay='0.00')
        la = i.lines.get(bread_price=self.bpa)
        self.bpa.unit_price = D('900'); self.bpa.save()
        self.push_line({'id': la.pk, 'invoice': str(i.pk), 'bread_price': self.bpa.pk,
                        'quantity': 3, 'ordered_quantity': 4, 'unit_price': '1', 'line_total': '3'})
        la.refresh_from_db()
        self.assertEqual((la.quantity, la.unit_price, la.line_total), (3, 500, 1500))

    def test_pas_de_retour_depuis_statut_terminal(self):
        for terminal in ('NOT_SERVED', 'DELIVERED', 'CANCELLED'):
            i = self.mk(pay='0.00')
            Invoice.objects.filter(pk=i.pk).update(status=terminal)
            for new in ('PENDING', 'DELIVERED', 'NOT_SERVED', 'CANCELLED'):
                if new == terminal:
                    continue
                self.push_inv({'id': str(i.pk), 'status': new, 'order_total': '1.00'})
                i.refresh_from_db()
                self.assertEqual(i.status, terminal, (terminal, new))
                self.assertNotEqual(i.order_total, D('1.00'), (terminal, new))

    def test_idempotence(self):
        i = self.mk(pay='1000.00')
        la = i.lines.get(bread_price=self.bpa)
        rec = {'id': str(i.pk), 'status': 'NOT_SERVED', 'order_total': '0.00', 'payment_amount': '1000.00',
               'not_served_at': timezone.now().isoformat()}
        lrec = {'id': la.pk, 'invoice': str(i.pk), 'bread_price': self.bpa.pk, 'quantity': 0, 'ordered_quantity': 4}
        for _ in range(3):
            self.push_inv(rec)
            self.push_line(lrec)
        i.refresh_from_db(); la.refresh_from_db()
        self.assertEqual((i.status, i.order_total), ('NOT_SERVED', 0))
        self.assertEqual((la.quantity, la.line_total), (0, 0))
        self.assertEqual(InvoiceLine.objects.filter(invoice=i).count(), 2)

    def test_livraison_partielle_propagee(self):
        i = self.mk(pay='0.00')
        la = i.lines.get(bread_price=self.bpa)
        self.push_inv({'id': str(i.pk), 'status': 'DELIVERED', 'order_total': '1600.00',
                       'initial_order_total': '2600.00'})
        self.push_line({'id': la.pk, 'invoice': str(i.pk), 'bread_price': self.bpa.pk,
                        'quantity': 2, 'ordered_quantity': 4})
        i.refresh_from_db(); la.refresh_from_db()
        self.assertEqual((i.status, i.order_total, i.initial_order_total), ('DELIVERED', D('1600'), D('2600')))
        self.assertEqual((la.quantity, la.ordered_quantity, la.line_total), (2, 4, 1000))

    def test_bug323_livraison_avec_delivered_at_iso_ne_plante_pas(self):
        i = self.mk(pay='0.00')
        self.push_inv({'id': str(i.pk), 'status': 'DELIVERED', 'delivered_at': timezone.now().isoformat()})
        i.refresh_from_db()
        self.assertEqual(i.status, 'DELIVERED')

    def test_rejeu_ancienne_ligne_sur_facture_non_servie_ne_ressuscite_pas_les_quantites(self):
        """Un push rejoue/retarde avec l'ancienne quantite ne doit pas rendre incoherente une facture terminale."""
        i = self.mk(pay='1000.00')
        la = i.lines.get(bread_price=self.bpa)
        self.ns(i)
        la.refresh_from_db()
        self.assertEqual(la.quantity, 0)
        self.push_line({'id': la.pk, 'invoice': str(i.pk), 'bread_price': self.bpa.pk,
                        'quantity': 4, 'ordered_quantity': 4})
        la.refresh_from_db()
        self.assertEqual(la.quantity, 0, "BUG-324 : quantite servie d'une facture NOT_SERVED reecrite par un push perime")

    def test_bug323_delivered_at_invalide_rejete_sans_500(self):
        i = self.mk(pay='0.00')
        r = self.push_inv({'id': str(i.pk), 'status': 'DELIVERED', 'delivered_at': 'pas une date'})
        self.assertEqual(r['status'], 'REJECTED')
        self.assertIn('invalide', r['reason'])
        i.refresh_from_db()
        self.assertEqual(i.status, 'PENDING')

    def test_bug323_delivered_at_iso_naif_et_not_served_at_iso(self):
        i = self.mk(pay='0.00')
        self.push_inv({'id': str(i.pk), 'status': 'DELIVERED', 'delivered_at': '2026-11-20T10:00:00'})
        i.refresh_from_db()
        self.assertEqual(i.status, 'DELIVERED')
        self.assertTrue(timezone.is_aware(i.delivered_at))

    def test_bug324_ligne_facture_livree_ne_remonte_pas_en_quantite(self):
        i = self.mk(pay='0.00')
        la = i.lines.get(bread_price=self.bpa)
        Invoice.objects.filter(pk=i.pk).update(status='DELIVERED')
        InvoiceLine.objects.filter(pk=la.pk).update(quantity=2, line_total=1000)
        self.push_line({'id': la.pk, 'invoice': str(i.pk), 'bread_price': self.bpa.pk,
                        'quantity': 4, 'ordered_quantity': 9})
        la.refresh_from_db()
        self.assertEqual((la.quantity, la.ordered_quantity, la.line_total), (2, 4, 1000))
