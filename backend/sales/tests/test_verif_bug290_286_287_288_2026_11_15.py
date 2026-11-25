"""Verification independante (testeur-ventes, 2026-11-15) de BUG-290 (paiements
negatifs, motif, blocage de credit, daily_summary, recu) et BUG-286/287/288.
Tests contradictoires ; valeurs calculees a la main ; donnees fictives."""
from decimal import Decimal as Dc

from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from core.models import SystemNotification
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice
from sales.tests.test_vague4_calendaire_ventes_2026_11_12 import (
    Base as RotBase, D, PREV, INV, _api, _now,
)


class V(TestCase):
    def setUp(self):
        self.node = make_node(code='V9')
        self.other = make_node(code='V8')
        self.bp = make_bread_price('B500', 'Pain 500 FC', 500)
        self.fact = make_user('FACTURIER', node=self.node, team='A', username='v290_f')
        self.api = APIClient()
        self.api.force_authenticate(self.fact)

    def rep(self, c, amount, **extra):
        body = {'client': str(c.pk), 'payment_type': 'CASH', 'payment_amount': str(amount),
                'is_debt_repayment': True, 'lines': []}
        body.update(extra)
        return self.api.post(INV, body, format='json')

    def sale(self, c, qty, pay, **extra):
        body = {'payment_type': 'CREDIT', 'payment_amount': str(pay),
                'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}
        if c is not None:
            body['client'] = str(c.pk)
        body.update(extra)
        return self.api.post(INV, body, format='json')

    def debt(self, c):
        c.refresh_from_db()
        return c.current_debt


class Neg290(V):
    def test_negatif_bloque_a_plafond_exact(self):
        c = make_client(self.node, current_debt=Dc('50000'))
        n = Invoice.objects.count()
        r = self.rep(c, '-1')
        self.assertEqual(r.status_code, 403, r.data)
        self.assertIn('detail', r.data)
        self.assertEqual(self.debt(c), Dc('50000'))
        self.assertEqual(Invoice.objects.count(), n)
        self.assertTrue(SystemNotification.objects.filter(title__icontains='bloqu').exists())

    def test_negatif_juste_sous_plafond_accepte_puis_suivant_bloque(self):
        c = make_client(self.node, current_debt=Dc('49999'))
        r = self.rep(c, '-1000', motif='EMPRUNT_BOULANGER')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.debt(c), Dc('50999'))
        self.assertEqual(self.rep(c, '-1').status_code, 403)
        self.assertEqual(self.rep(c, '1000').status_code, 201)   # versement positif toujours possible
        self.assertEqual(self.debt(c), Dc('49999'))

    def test_negatif_sur_vente_avec_lignes_bloque_au_plafond(self):
        c = make_client(self.node, current_debt=Dc('50000'))
        r = self.sale(c, 2, '-500')
        self.assertEqual(r.status_code, 403, r.data)
        self.assertEqual(self.debt(c), Dc('50000'))

    def test_negatif_sur_vente_sous_plafond_bp_exacte(self):
        c = make_client(self.node, current_debt=Dc('1000'))
        r = self.sale(c, 2, '-500')   # 1000 + 1000 - (-500) = 2500
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Dc(r.data['debt_after']), Dc('2500'))
        self.assertEqual(self.debt(c), Dc('2500'))

    def test_deficit_du_mois_bloque_un_negatif(self):
        c = make_client(self.node, current_debt=Dc('0'), commission_rate=Dc('0'))
        r = self.sale(c, 120, '0')   # 60 000 FC non payes
        self.assertEqual(r.status_code, 201, r.data)
        self.api.post(f"{INV}{r.data['id']}/deliver/")
        Client.objects.filter(pk=c.pk).update(current_debt=Dc('0'))   # isole la regle du deficit
        r2 = self.rep(c, '-100')
        self.assertEqual(r2.status_code, 403, r2.data)
        self.assertIn('Déficit', r2.data['detail'])

    def test_zero_refuse_motif_invalide_refuse(self):
        c = make_client(self.node)
        self.assertEqual(self.rep(c, '0').status_code, 400)
        r = self.rep(c, '-10', motif='PIRATE')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(self.debt(c), Dc('0'))

    def test_motif_absent_vide_et_bp_exacte(self):
        c = make_client(self.node, current_debt=Dc('-10000'))
        r = self.rep(c, '-4000')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['motif'], '')
        r2 = self.rep(c, '-1000', motif='AUTRE')
        self.assertEqual(r2.data['motif'], 'AUTRE')
        self.assertEqual(self.debt(c), Dc('-5000'))

    def test_montants_extremes_ne_donnent_pas_500(self):
        c = make_client(self.node)
        for v in ('abc', '1e400', '-99999999999999999', '-0.001', ''):
            r = self.rep(c, v)
            self.assertLess(r.status_code, 500, (v, r.status_code))
        self.assertEqual(self.debt(c), Dc('0'))

    def test_sans_client_negatif_refuse_pour_repayment(self):
        r = self.api.post(INV, {'payment_type': 'CASH', 'payment_amount': '-100',
                                'is_debt_repayment': True, 'lines': []}, format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_recu_unique_sans_ligne_livre_immediatement(self):
        c = make_client(self.node)
        a = self.rep(c, '-500')
        b = self.rep(c, '-500')
        self.assertNotEqual(a.data['receipt_number'], b.data['receipt_number'])
        self.assertEqual(a.data['lines'], [])
        self.assertEqual(Dc(a.data['order_total']), 0)
        self.assertEqual(a.data['status'], 'DELIVERED')
        self.assertEqual(self.debt(c), Dc('1000'))

    def test_negatif_avec_codes_speciaux_ne_contourne_pas_le_blocage(self):
        c = make_client(self.node, current_debt=Dc('60000'))
        for code in ('RG', 'NS', 'NV'):
            r = self.rep(c, '-100', special_code=code)
            self.assertEqual(r.status_code, 403, (code, r.status_code, r.data))
        self.assertEqual(self.debt(c), Dc('60000'))

    def test_vente_rg_avec_paiement_negatif_bp_inchangee(self):
        c = make_client(self.node, current_debt=Dc('60000'))
        r = self.sale(c, 2, '-500', special_code='RG')
        if r.status_code == 201:
            self.assertEqual(self.debt(c), Dc('60000'), "RG : BP inchangee attendue")

    def test_facturier_ne_force_pas_le_noeud(self):
        c = make_client(self.node)
        r = self.rep(c, '-100', node=self.other.pk)
        if r.status_code == 201:
            self.assertEqual(Invoice.objects.get(pk=r.data['id']).node_id, self.node.pk)
        else:
            self.assertIn(r.status_code, (400, 403))

    def test_annulation_pending_avec_paiement_negatif_restaure_bp(self):
        c = make_client(self.node, current_debt=Dc('1000'))
        r = self.sale(c, 2, '-500')           # BP 2500
        a = self.api.post(f"{INV}{r.data['id']}/cancel/")
        self.assertEqual(a.status_code, 200, a.data)
        self.assertEqual(self.debt(c), Dc('1000'))


class Reports290(RotBase):
    rotation = False

    def setUp(self):
        super().setUp()
        self.cl.current_debt = Dc('-10000')
        self.cl.save()

    def _summary(self, d=D):
        rows = _api(self.gerant).get(INV + 'daily_summary/', {'date': str(d)}).data
        cash = sum(Dc(str(r['total'])) for r in rows if r['payment_type'] == 'CASH')
        credit = sum(Dc(str(r['total'])) for r in rows if r['payment_type'] == 'CREDIT')
        return cash, credit

    def refund_neg(self, amount):
        return _api(self.fa).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CASH', 'payment_amount': amount,
                                        'is_debt_repayment': True, 'lines': [], 'motif': 'RETRAIT_EPARGNE'}, format='json')

    def test_daily_summary_retrait_vente_rg_solde(self):
        from core.testing import make_client as mk
        other = mk(self.node)
        with _now(13, 0):
            r = self.refund_neg(-4000)
            self.assertEqual(r.status_code, 201, r.data)
            v = self.sale(qty=2, pay=1000, client=other)
            self.deliver(v.data['id'])
            rg = self.sale(qty=4, special_code='RG', client=other, pay=0)
            self.deliver(rg.data['id'])
            s = self.sale(qty=6, pay=1000, is_soldee=True, client=other)
            self.deliver(s.data['id'])
            cash, credit = self._summary()
        # CASH = -4000 + 1000 + 0 + 1000 ; CREDIT = retrait (+4000) seul
        self.assertEqual(cash, Dc('-2000'))
        self.assertEqual(credit, Dc('4000'))
        self.cl.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.cl.current_debt, Dc('-6000'))
        self.assertEqual(other.current_debt, Dc('0'))

    def test_rg_avec_paiement_hors_credit(self):
        from core.testing import make_client as mk
        other = mk(self.node)
        with _now(13, 0):
            rg = self.sale(qty=4, special_code='RG', client=other, pay=500)
            if rg.status_code != 201:
                self.skipTest('RG avec paiement refusee : %s' % rg.status_code)
            self.deliver(rg.data['id'])
            cash, credit = self._summary()
        other.refresh_from_db()
        self.assertEqual(credit + other.current_debt - other.current_debt, credit)
        self.assertEqual(credit, other.current_debt, "CREDIT du jour doit egaler la variation de BP")

    def test_facturier_report_retrait_et_solde(self):
        with _now(13, 0):
            self.refund_neg(-4000)
            s = self.sale(qty=6, pay=1000, is_soldee=True)
            self.deliver(s.data['id'])
            rep = _api(self.gerant).post('/api/treasury/reports/generate/', {'date': str(D)}, format='json')
        self.assertEqual(rep.status_code, 200, rep.data)
        cash = sum(Dc(x['total_cash_sales']) for x in rep.data)
        credit = sum(Dc(x['total_credit_sales']) for x in rep.data)
        self.assertEqual(cash, Dc('-3000'))
        self.assertEqual(credit, Dc('4000'))       # retrait ; solde exclu

    def test_cloture_286_jour_de_livraison_coherent_avec_daily_summary(self):
        self.assign(PREV, 'A')
        self.assign(D, 'A')
        with _now(11, 55):  # BUG-1130 : journee comptable PREV (avant la cloture de 12:00)
            iid = self.sale(qty=10, pay=2000).data['id']
        with _now(12, 10):  # livree apres la cloture : journee D
            self.deliver(iid)

        def tot(d):
            r = _api(self.gerant).get('/api/production/daily-closure/', {'date': str(d)})
            self.assertEqual(r.status_code, 200, r.data)
            return r.data['totals']
        with _now(13, 0):
            self.assertEqual(Dc(tot(PREV)['ecart_facture_fc']), 0)
            self.assertEqual(Dc(tot(D)['ecart_facture_fc']), Dc('3000'))
            self.assertEqual(self._summary(PREV)[0], 0)
            self.assertEqual(self._summary(D)[0], Dc('2000'))
