"""BUG-290 (décision client 2026-11-14) : le signe « − » est accepté pour un
paiement (sortie de caisse : retrait d'épargne, emprunt boulanger, manquant
d'équipe). BP après = BP avant + commande - paiement, donc la BP augmente.
Valeurs calculées à la main ; données fictives uniquement."""
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clients.models import Client
from commissions.models import ClientCommission
from core.models import SystemNotification
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice
from treasury.models import CashClosure, CashbookEntry
from treasury.services import promote_closure_to_cashbook, regenerate_facturier_reports

INV = '/api/sales/invoices/'


class Base(TestCase):
    def setUp(self):
        self.node = make_node(code='N9')
        self.bp = make_bread_price('B500', 'Pain 500 FC', 500)
        self.fact = make_user('FACTURIER', node=self.node, team='A', username='n290_f')
        self.gerant = make_user('GERANT', node=self.node, team='', username='n290_g')
        self.api = APIClient()
        self.api.force_authenticate(self.fact)

    def versement(self, client, amount, **extra):
        body = {'client': str(client.pk), 'payment_type': 'CASH', 'payment_amount': str(amount),
                'is_debt_repayment': True, 'lines': []}
        body.update(extra)
        return self.api.post(INV, body, format='json')

    def vente(self, client, qty, pay, **extra):
        body = {'client': str(client.pk), 'payment_type': 'CREDIT', 'payment_amount': str(pay),
                'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}
        body.update(extra)
        return self.api.post(INV, body, format='json')

    def debt(self, client):
        client.refresh_from_db()
        return client.current_debt


class Bug290PaiementNegatif(Base):
    def test_versement_sans_commande_negatif_augmente_la_bp_et_garde_le_motif(self):
        c = make_client(self.node, current_debt=D('-10000'))           # client épargne
        r = self.versement(c, '-4000', motif='RETRAIT_EPARGNE')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(D(r.data['payment_amount']), D('-4000'))
        self.assertEqual(D(r.data['order_total']), D('0'))
        self.assertEqual(D(r.data['debt_before']), D('-10000'))
        self.assertEqual(D(r.data['debt_after']), D('-6000'))          # -10 000 + 0 - (-4 000)
        self.assertEqual(r.data['motif'], 'RETRAIT_EPARGNE')
        self.assertEqual(self.debt(c), D('-6000'))
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual(inv.status, Invoice.Status.DELIVERED)
        self.assertTrue(inv.is_debt_repayment)

    def test_facture_avec_commande_et_paiement_negatif(self):
        c = make_client(self.node, current_debt=D('1000'))
        r = self.vente(c, 2, '-500')                                   # commande 1 000
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(D(r.data['debt_after']), D('2500'))           # 1 000 + 1 000 - (-500)
        self.assertEqual(self.debt(c), D('2500'))

    def test_motif_facultatif_defaut_vide_et_valeurs_controlees(self):
        c = make_client(self.node)
        r = self.vente(c, 1, '500')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['motif'], '')
        for m in ('RETRAIT_EPARGNE', 'EMPRUNT_BOULANGER', 'MANQUANT_EQUIPE', 'AUTRE'):
            self.assertEqual(self.versement(c, '-100', motif=m).status_code, 201, m)
        bad = self.versement(c, '-100', motif='NIMPORTE')
        self.assertEqual(bad.status_code, 400)

    def test_versement_a_zero_toujours_refuse(self):
        c = make_client(self.node)
        r = self.versement(c, '0')
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.data)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_client_en_depassement_de_plafond_reste_bloque_par_un_paiement_negatif(self):
        c = make_client(self.node, credit_limit=D('50000'), current_debt=D('50000'))
        n0 = SystemNotification.objects.count()
        r = self.versement(c, '-1000')
        self.assertEqual(r.status_code, 403, r.data)
        self.assertIn('Plafond', r.data['detail'])
        r = self.vente(c, 2, '-500')
        self.assertEqual(r.status_code, 403, r.data)
        self.assertEqual(self.debt(c), D('50000'))
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertGreater(SystemNotification.objects.count(), n0)

    def test_client_sous_le_plafond_peut_sortir_de_la_caisse(self):
        c = make_client(self.node, credit_limit=D('50000'), current_debt=D('49000'))
        r = self.versement(c, '-1000', motif='EMPRUNT_BOULANGER')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.debt(c), D('50000'))                     # désormais au plafond : bloqué ensuite
        self.assertEqual(self.versement(c, '-1000').status_code, 403)

    def test_versement_positif_sur_client_au_plafond_reste_possible(self):
        c = make_client(self.node, credit_limit=D('50000'), current_debt=D('50000'))
        r = self.versement(c, '2000')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.debt(c), D('48000'))


class Bug290Coherence(Base):
    def _jour(self):
        return str(timezone.localdate())

    def test_daily_summary_cash_negatif_et_credit(self):
        c = make_client(self.node)
        self.assertEqual(self.versement(c, '-5000', motif='RETRAIT_EPARGNE').status_code, 201)
        rows = APIClient()
        rows.force_authenticate(self.gerant)
        data = rows.get(INV + 'daily_summary/', {'date': self._jour()}).data
        cash = [x for x in data if x['payment_type'] == 'CASH'][0]
        credit = [x for x in data if x['payment_type'] == 'CREDIT'][0]
        self.assertEqual(D(str(cash['total'])), D('-5000'))
        self.assertEqual(D(str(credit['total'])), D('5000'))          # variation de BP = +5 000

    def test_rapport_facturier_cloture_et_livre_de_caisse_sortie(self):
        c = make_client(self.node)
        self.assertEqual(self.versement(c, '-5000', motif='MANQUANT_EQUIPE').status_code, 201)
        today = timezone.localdate()
        reports = regenerate_facturier_reports(self.node, today)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].total_cash_sales, D('-5000.00'))
        self.assertEqual(reports[0].theoretical_cash, D('-5000.00'))
        closure = CashClosure.objects.create(
            node=self.node, date=today, gerant=self.gerant, total_entries=D('-5000'),
            total_expenses=D('0'), is_validated=True)
        closure.compute_physical_cash()
        closure.save()
        self.assertEqual(closure.net_cash, D('-5000'))
        entry = promote_closure_to_cashbook(closure, acting_user=self.gerant)
        self.assertEqual(entry.entry_amount, D('0'))
        self.assertEqual(entry.exit_amount, D('5000'))                 # sortie du livre de caisse
        self.assertEqual(CashbookEntry.objects.filter(source_closure=closure).count(), 1)

    def test_vente_plus_sortie_somme_algebrique_du_cash_du_jour(self):
        c1 = make_client(self.node)
        c2 = make_client(self.node)
        self.assertEqual(self.vente(c1, 2, '1000', payment_type='CASH').status_code, 201)
        self.assertEqual(self.versement(c2, '-300', motif='AUTRE').status_code, 201)
        # la vente en attente n'est comptée qu'à la livraison
        iid = Invoice.objects.get(client=c1).pk
        self.assertEqual(self.api.post(f'{INV}{iid}/deliver/').status_code, 200)
        reports = regenerate_facturier_reports(self.node, timezone.localdate())
        self.assertEqual(sum((r.total_cash_sales for r in reports), D('0')), D('700.00'))   # 1 000 - 300

    def test_commissions_excluent_les_lignes_sans_commande(self):
        from commissions.models import CommissionPeriod
        sans = make_client(self.node)
        avec = make_client(self.node)
        self.assertEqual(self.versement(sans, '-5000', motif='RETRAIT_EPARGNE').status_code, 201)
        r = self.vente(avec, 2, '1000', payment_type='CASH')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.api.post(f'{INV}{r.data["id"]}/deliver/').status_code, 200)
        today = timezone.localdate()
        d = make_user('DIRECTION', node=None, team='', username='n290_d')
        api = APIClient()
        api.force_authenticate(d)
        g = api.post('/api/commissions/periods/generate/',
                     {'node': self.node.pk, 'month': today.month, 'year': today.year}, format='json')
        self.assertEqual(g.status_code, 201, g.data)
        period = CommissionPeriod.objects.get(node=self.node, month=today.month, year=today.year)
        clients = set(ClientCommission.objects.filter(period=period).values_list('client_id', flat=True))
        self.assertEqual(clients, {avec.pk})
        cc = ClientCommission.objects.get(period=period, client=avec)
        self.assertEqual(cc.order_value, D('1000'))
        self.assertEqual(cc.commission_gross, D('250'))
