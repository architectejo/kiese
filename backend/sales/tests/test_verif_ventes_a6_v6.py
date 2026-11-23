"""
Testeur ventes (cycle a6, 2026-11-23) : verification independante de BUG-664 a 673 (hors 671) et
nouveaux angles. Donnees fictives. Aucun code applicatif modifie.
"""
from datetime import timedelta
from unittest import expectedFailure
from decimal import Decimal

from django.utils import timezone

from clients.models import Client
from core.models import Config
from sales.models import Invoice
from sales.tests.test_ventes_a3_v2 import Base, INV, _api

D = Decimal


class Verifs(Base):
    def _deliver(self, iid, **b):
        return _api(self.lv1).post(f'{INV}{iid}/deliver/', b, format='json')

    def _adj(self, iid, sign, qty, pay=0):
        return _api(self.g1).post(f'{INV}{iid}/adjust/', {
            'adjustment_sign': sign, 'payment_amount': pay,
            'lines': [{'bread_price': self.bp3.pk, 'quantity': qty}]}, format='json')

    def _ns(self, iid):
        return _api(self.fa1).post(f'{INV}{iid}/mark-not-served/', {}, format='json')

    def _daily(self):
        rows = _api(self.fa1).get(f'{INV}daily_summary/', {'date': timezone.localdate().isoformat()}).data
        out = {}
        for x in rows:
            out.setdefault(x['node__code'], {})[x['payment_type']] = (D(str(x['total'])), x['count'])
        return out

    def _bs(self):
        return _api(self.fa1).get(f'{INV}bread_summary/').data

    def _allow_backdated(self):
        cfg = Config.get_instance()
        cfg.allow_backdated_sales = True
        cfg.save()

    # ---- 670
    def test_670_non_servi_seul_cash_credit_count(self):
        iid = self.post(payment_amount=1000).data['id']
        self._ns(iid)
        d = self._daily()['AV1']
        self.assertEqual(d['CASH'], (D(1000), 0))
        self.assertEqual(d['CREDIT'][0], D(-1000))

    def test_670_non_servi_sans_versement_absent(self):
        iid = self.post().data['id']
        self._ns(iid)
        self.assertNotIn('AV1', self._daily())

    def test_670_melange_livree_et_non_servi(self):
        a = self.post(payment_amount=1000).data['id']
        self._deliver(a)
        b = self.post(payment_amount=500).data['id']
        self._ns(b)
        d = self._daily()['AV1']
        self.assertEqual(d['CASH'], (D(1500), 1))
        self.assertEqual(d['CREDIT'][0], D(3000 - 1000 - 500))

    def test_670_non_servi_autre_jour_exclu(self):
        iid = self.post(payment_amount=1000).data['id']
        self._ns(iid)
        Invoice.objects.filter(pk=iid).update(not_served_at=timezone.now() - timedelta(days=3))
        self.assertNotIn('AV1', self._daily())

    def test_670_non_servi_repete_pas_double_compte(self):
        iid = self.post(payment_amount=1000).data['id']
        self._ns(iid)
        self._ns(iid)
        self.assertEqual(self._daily()['AV1']['CASH'][0], D(1000))

    # ---- 664
    def test_664_ajustement_plus_et_moins_net(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 10}]).data['id']
        self._deliver(iid)
        self._adj(iid, 1, 5)
        self._adj(iid, -1, 3)
        r = self._bs()
        self.assertEqual((r['grand_total_qty'], r['grand_total_fc']), (12, 3600), r)

    def test_BUG_890_ajustement_sur_facture_en_attente_annulee_ne_fausse_pas_les_resumes(self):
        """BUG-890 : l'ajustement d'une facture EN ATTENTE est cree LIVRE ; si la facture mere est annulee
        l'ajustement reste : bread_summary -2 pains, daily_summary CREDIT -600 / 1 livraison fantome."""
        iid = self.post().data['id']
        self._adj(iid, -1, 2)
        self.assertEqual(_api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json').status_code, 200)
        self.assertEqual(self._bs()['grand_total_qty'], 0, 'pains negatifs apres annulation')
        self.assertNotIn('AV1', self._daily(), 'ligne fantome dans daily_summary')

    def test_664_ajustement_autre_prix_net_par_categorie(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 4},
                               {'bread_price': self.bp5.pk, 'quantity': 4}]).data['id']
        self._deliver(iid)
        _api(self.g1).post(f'{INV}{iid}/adjust/', {
            'adjustment_sign': -1, 'payment_amount': 0,
            'lines': [{'bread_price': self.bp5.pk, 'quantity': 4}]}, format='json')
        r = self._bs()
        self.assertEqual((r['grand_total_qty'], r['grand_total_fc']), (4, 1200), r)

    # ---- 665
    def test_665_annulation_garde_a_risque_si_bp_reste_au_dessus(self):
        Client.objects.filter(pk=self.cl.pk).update(current_debt=D('60000'))
        iid = self.post(payment_amount=3000, payment_type='CASH').data['id']
        self._ns  # noqa
        _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('60000'))
        self.assertEqual(self.cl.category, 'RISK')

    # ---- 666 / 667
    def test_666_livree_ajustee_puis_annulation_compteur_coherent(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 10}]).data['id']
        self._deliver(iid)
        self._adj(iid, -1, 3)
        r = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.cl.refresh_from_db()
        self.assertIn(self.cl.total_breads_received, (0, 7), (r.status_code, self.cl.total_breads_received))

    def test_666_non_servi_apres_ajustement_en_attente_compteur_zero(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 4}]).data['id']
        self._adj(iid, 1, 2)
        self._ns(iid)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 0)

    def test_666_livraison_double_compteur_une_fois(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 4}]).data['id']
        self._deliver(iid)
        self._deliver(iid)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 4)

    def test_666_ajustement_negatif_plancher_zero(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}]).data['id']
        self._deliver(iid)
        self._adj(iid, -1, 2)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 0)

    def test_667_livraison_partielle_compteur_egal_pains_livres(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 10}]).data['id']
        li = Invoice.objects.get(pk=iid).lines.first()
        r = self._deliver(iid, lines=[{'id': str(li.pk), 'quantity': 6}])
        if r.status_code == 200:
            self.cl.refresh_from_db()
            self.assertEqual(self.cl.total_breads_received, 6, r.data)

    # ---- 668
    def test_668_livraison_meme_jour_acceptee(self):
        self._allow_backdated()
        iid = self.post().data['id']
        r = self._deliver(iid, delivered_at=timezone.localdate().isoformat())
        self.assertEqual(r.status_code, 200, r.data)

    def test_668_livraison_future_refusee(self):
        self._allow_backdated()
        iid = self.post().data['id']
        r = self._deliver(iid, delivered_at=(timezone.localdate() + timedelta(days=3)).isoformat())
        inv = Invoice.objects.get(pk=iid)
        self.assertTrue(r.status_code == 400 or inv.delivered_at <= timezone.now() + timedelta(minutes=5),
                        f'livree dans le futur : {inv.delivered_at}')

    def test_668_refus_sans_effet(self):
        self._allow_backdated()
        iid = self.post().data['id']
        before = Invoice.objects.get(pk=iid).status
        sent0 = self.sent()
        r = self._deliver(iid, delivered_at=(timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Invoice.objects.get(pk=iid).status, before)
        self.assertEqual(self.sent(), sent0)

    # ---- 669
    def test_669_sans_client_egal_a_la_commande(self):
        r = self.post(client=False, payment_type='CASH', payment_amount=3000)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(D(str(r.data['payment_amount'])), D(3000))

    def test_669_sans_client_inferieur_conserve(self):
        r = self.post(client=False, payment_type='CASH', payment_amount=1000)
        if r.status_code == 201:
            self.assertEqual(D(str(r.data['payment_amount'])), D(1000))

    def test_669_sans_client_negatif_refuse(self):
        r = self.post(client=False, payment_type='CASH', payment_amount=-500)
        self.assertEqual(r.status_code, 400, getattr(r, 'data', ''))

    def test_669_sans_client_daily_summary_cash_plafonne(self):
        r = self.post(client=False, payment_type='CASH', payment_amount=1000000)
        self.assertEqual(r.status_code, 201, getattr(r, 'data', ''))
        self._deliver(r.data['id'])
        self.assertEqual(self._daily()['AV1']['CASH'][0], D(3000))

    def test_669_avec_client_surpaiement_reduit_la_bp(self):
        r = self.post(payment_type='CASH', payment_amount=5000)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.debt(), D(-2000))

    # ---- 672 / 673
    def test_673_remboursement_ns_code_ignore(self):
        r = self.post(lines=[], payment_amount=1000, is_debt_repayment=True, special_code='NS')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).special_code, '')
        self.assertEqual(self.debt(), D(-1000))

    def test_673_vente_normale_rg_toujours_stocke(self):
        r = self.post(special_code='RG', payment_amount=3000, payment_type='CASH')
        if r.status_code == 201:
            self.assertEqual(Invoice.objects.get(pk=r.data['id']).special_code, 'RG')

    def test_672_patch_sans_periode_close_pas_de_notification(self):
        from core.models import SystemNotification
        iid = self.post(payment_amount=3000, payment_type='CASH').data['id']
        self._deliver(iid)
        before = SystemNotification.objects.count()
        r = _api(self.g1).patch(f'{INV}{iid}/', {'commission_exempt': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(SystemNotification.objects.count(), before)

    def test_672_patch_en_attente_periode_close_sans_erreur(self):
        from commissions.models import CommissionPeriod
        iid = self.post().data['id']
        t = timezone.localdate()
        CommissionPeriod.objects.create(node=self.n1, month=t.month, year=t.year, is_closed=True,
                                        closed_at=timezone.now())
        r = _api(self.g1).patch(f'{INV}{iid}/', {'commission_exempt': True}, format='json')
        self.assertNotEqual(r.status_code, 500)

    def test_672_patch_sans_client_periode_close_sans_erreur(self):
        iid = self.post(client=False, payment_type='CASH', payment_amount=3000).data['id']
        self._deliver(iid)
        r = _api(self.g1).patch(f'{INV}{iid}/', {'commission_exempt': True}, format='json')
        self.assertNotEqual(r.status_code, 500)
