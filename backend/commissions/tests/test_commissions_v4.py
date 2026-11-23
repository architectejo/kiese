"""Commissions - ronde v4 (testeur Clients/Commissions, 2026-11-22-b4).

Verification independante de BUG-745, 749, 750 (set_manuel), BUG-821 / 822
(partie commissions) / 824 (ajustements), attaque du 400 "aucun champ" et
des bornes de set_manuel. Valeurs calculees a la main. Donnees FICTIVES.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as D
from unittest import expectedFailure

from django.utils import timezone

from clients.models import Client
from commissions.models import ClientCommission
from commissions.tests.test_commissions_v2 import COMM, Base, api
from core.models import Config
from core.testing import make_bread_price, make_client
from sales.models import Invoice, InvoiceLine

TODAY = timezone.localdate()


class AdjBase(Base):
    def setUp(self):
        super().setUp()
        self.p200 = make_bread_price('MINI', 'Pain 200 FC', 200)

    def inv(self, client, qty, price=None, day=None, **kw):
        price = price or self.p500
        i = Invoice.objects.create(
            node=self.n1, client=client, payment_type='CREDIT', status='DELIVERED',
            payment_amount=D('0'), invoice_date=day or TODAY, node_origin='QA1', **kw)
        InvoiceLine.objects.create(invoice=i, bread_price=price, quantity=qty)
        i.compute_order_total()
        i.save(update_fields=['order_total'])
        return i

    def adjust(self, inv, sign, qty, price=None, expect=201, user=None):
        r = api(user or self.g1).post(f'/api/sales/invoices/{inv.pk}/adjust/', {
            'adjustment_sign': sign, 'payment_amount': '0.00', 'invoice_date': str(TODAY),
            'lines': [{'bread_price': (price or self.p500).pk, 'quantity': qty}]}, format='json')
        self.assertEqual(r.status_code, expect, r.data)
        return r

    def gen(self):
        return self.generate(self.n1, month=TODAY.month, year=TODAY.year)

    def commission(self, c):
        return ClientCommission.objects.filter(client=c, period__node=self.n1).first()


class Ajustements821_822(AdjBase):
    def test_821_ajustement_d_une_rg_ne_donne_aucune_cm(self):
        c = make_client(self.n1)
        rg = self.inv(c, 10, special_code='RG')
        self.adjust(rg, 1, 2)
        self.gen()
        self.assertIsNone(self.commission(c))

    def test_821_ajustement_negatif_d_une_rg_aucune_cm(self):
        c = make_client(self.n1)
        rg = self.inv(c, 10, special_code='RG')
        self.adjust(rg, -1, 3)
        self.gen()
        self.assertIsNone(self.commission(c))

    def test_821_rg_et_vente_normale_seule_la_vente_compte(self):
        c = make_client(self.n1)
        rg = self.inv(c, 10, special_code='RG')
        self.adjust(rg, 1, 4)
        self.inv(c, 20)                      # 10 000 FC, 20 pains
        self.gen()
        r = self.commission(c)
        self.assertEqual((r.order_value, r.total_breads, r.commission_gross),
                         (D('10000.00'), 20, D('2500.00')))   # 20 x 500 x 0,25

    def test_821_ajustement_d_une_vente_normale_compte_dans_la_base(self):
        c = make_client(self.n1)
        v = self.inv(c, 10)                  # 5 000
        self.adjust(v, 1, 2)                 # +1 000
        self.gen()
        r = self.commission(c)
        self.assertEqual((r.order_value, r.total_breads), (D('6000.00'), 12))
        self.assertEqual(r.commission_gross, D('1500.00'))     # 6 000 x 0,25

    def test_821_ajustement_d_une_vente_soldee_reste_exclu(self):
        c = make_client(self.n1)
        v = self.inv(c, 10, is_soldee=True)
        self.adjust(v, 1, 2)
        self.gen()
        self.assertIsNone(self.commission(c))

    def test_822_total_pains_ajustement_negatif_soustrait(self):
        c = make_client(self.n1)
        v = self.inv(c, 10)
        self.adjust(v, -1, 3)
        self.gen()
        r = self.commission(c)
        self.assertEqual((r.total_breads, r.order_value), (7, D('3500.00')))
        self.assertEqual(r.commission_gross, D('875.00'))      # 3 500 x 0,25

    def test_822_chaine_plus_moins_plus(self):
        c = make_client(self.n1)
        v = self.inv(c, 10)
        self.adjust(v, -1, 4)                # 6
        self.adjust(v, 1, 1)                 # 7
        self.adjust(v, -1, 2)                # 5
        self.gen()
        r = self.commission(c)
        self.assertEqual((r.total_breads, r.order_value), (5, D('2500.00')))

    def test_822_deux_categories_dans_un_ajustement_negatif(self):
        c = make_client(self.n1)
        v = self.inv(c, 10)
        InvoiceLine.objects.create(invoice=v, bread_price=self.p200, quantity=5)
        v.compute_order_total()
        v.save(update_fields=['order_total'])   # 5 000 + 1 000
        r = api(self.g1).post(f'/api/sales/invoices/{v.pk}/adjust/', {
            'adjustment_sign': -1, 'payment_amount': '0', 'invoice_date': str(TODAY),
            'lines': [{'bread_price': self.p500.pk, 'quantity': 2}, {'bread_price': self.p200.pk, 'quantity': 5}]},
            format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.gen()
        row = self.commission(c)
        self.assertEqual((row.total_breads, row.order_value), (8, D('4000.00')))   # 15 - 7 ; 6 000 - 2 000

    def test_822_net_negatif_du_mois_pas_de_ligne_ni_pains_negatifs(self):
        """Original le mois precedent, ajustement negatif ce mois : nette negative = exclue."""
        c = make_client(self.n1)
        v = self.inv(c, 10, day=TODAY - timedelta(days=45))
        self.adjust(v, -1, 3)
        self.gen()
        self.assertIsNone(self.commission(c))


class Compteur824(AdjBase):
    def setUp(self):
        super().setUp()
        self.c = make_client(self.n1)
        Client.objects.filter(pk=self.c.pk).update(total_breads_received=10)

    def total(self):
        self.c.refresh_from_db()
        return self.c.total_breads_received

    def test_negatif_diminue(self):
        v = self.inv(self.c, 10)
        self.adjust(v, -1, 3)
        self.assertEqual(self.total(), 7)

    def test_positif_augmente(self):
        v = self.inv(self.c, 10)
        self.adjust(v, 1, 5)
        self.assertEqual(self.total(), 15)

    def test_plusieurs_lignes_sommees(self):
        v = self.inv(self.c, 10)
        InvoiceLine.objects.create(invoice=v, bread_price=self.p200, quantity=4)
        r = api(self.g1).post(f'/api/sales/invoices/{v.pk}/adjust/', {
            'adjustment_sign': 1, 'payment_amount': '0', 'invoice_date': str(TODAY),
            'lines': [{'bread_price': self.p500.pk, 'quantity': 2}, {'bread_price': self.p200.pk, 'quantity': 3}]},
            format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.total(), 15)

    def test_plancher_zero(self):
        v = self.inv(self.c, 10)
        Client.objects.filter(pk=self.c.pk).update(total_breads_received=2)
        self.adjust(v, -1, 10)
        self.assertEqual(self.total(), 0)

    def test_ns_ne_touche_pas_le_compteur(self):
        v = self.inv(self.c, 10, special_code='NS')
        self.adjust(v, 1, 5)
        self.assertEqual(self.total(), 10)

    def test_vente_sans_client_ne_plante_pas(self):
        v = self.inv(None, 10)
        self.adjust(v, -1, 2)

    def test_categorie_meilleur_client_suit_le_seuil(self):
        cfg = Config.get_instance()
        cfg.best_client_threshold = 100
        cfg.save()
        Client.objects.filter(pk=self.c.pk).update(total_breads_received=98)
        v = self.inv(self.c, 10)
        self.adjust(v, 1, 1)                 # 99 : sous le seuil
        self.c.refresh_from_db()
        self.assertEqual(self.c.category, Client.Category.NORMAL)
        self.adjust(v, 1, 1)                 # 100 : seuil atteint (>=)
        self.c.refresh_from_db()
        self.assertEqual(self.c.category, Client.Category.BEST)
        self.adjust(v, -1, 1)                # 99 : retombe
        self.c.refresh_from_db()
        self.assertEqual((self.c.total_breads_received, self.c.category), (99, Client.Category.NORMAL))

    def test_a_risque_prime_sur_meilleur_client(self):
        cfg = Config.get_instance()
        cfg.best_client_threshold = 5
        cfg.save()
        Client.objects.filter(pk=self.c.pk).update(credit_limit=D('1000'), current_debt=D('900'))
        v = self.inv(self.c, 10)
        self.adjust(v, 1, 1)                 # +500 de dette -> 1 400 >= 1 000
        self.c.refresh_from_db()
        self.assertEqual(self.c.category, Client.Category.RISK)

    def test_ajustement_refuse_ne_change_pas_le_compteur(self):
        v = self.inv(self.c, 10)
        self.adjust(v, -1, 11, expect=400)   # plus que ce qui reste
        self.adjust(v, 1, 1, expect=403, user=self.f1)
        self.assertEqual(self.total(), 10)


class SetManuelV4(Base):
    def setUp(self):
        super().setUp()
        self.c = make_client(self.n1)
        self.invoice(self.n1, self.c, 100)
        self.r = self.row(self.generate(self.n1), self.c)   # CM 12 500, social 2 000, carte 1 000, net 9 500

    def url(self):
        return f'{COMM}{self.r.id}/set_manuel/'

    def patch(self, body, user=None):
        return api(user or self.direction).patch(self.url(), body, format='json')

    def fresh(self):
        self.r.refresh_from_db()
        return self.r

    def test_corps_vide_400_aucun_effet(self):
        self.patch({'manuel_adjustment': '700'})
        r = self.patch({})
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn('detail', r.data)
        self.assertEqual(self.fresh().manuel_adjustment, D('700.00'))

    def test_corps_champs_inconnus_seuls_400(self):
        r = self.patch({'foo': 1, 'net_payable': '999999'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.fresh().net_payable, D('9500.00'))

    def test_corps_non_objet(self):
        for body in ([], [1], 'x', 5):
            with self.subTest(body=body):
                r = api(self.direction).patch(self.url(), body, format='json')
                self.assertIn(r.status_code, (400, 415), (body, r.status_code))
        self.assertEqual(self.fresh().net_payable, D('9500.00'))

    def test_notes_seules_conservent_l_ajustement_et_le_net(self):
        self.patch({'manuel_adjustment': '1234.5', 'manuel_notes': 'v1'})
        r = self.patch({'manuel_notes': 'v2'})
        self.assertEqual(r.status_code, 200, r.data)
        x = self.fresh()
        self.assertEqual((x.manuel_adjustment, x.manuel_notes, x.net_payable), (D('1234.50'), 'v2', D('1234.50')))

    def test_notes_seules_sans_ajustement_ne_cree_pas_d_ajustement(self):
        r = self.patch({'manuel_notes': 'note'})
        self.assertEqual(r.status_code, 200, r.data)
        x = self.fresh()
        self.assertIsNone(x.manuel_adjustment)
        self.assertEqual((x.manuel_notes, x.net_payable), ('note', D('9500.00')))

    def test_notes_null_devient_vide_et_conserve_l_ajustement(self):
        self.patch({'manuel_adjustment': '50', 'manuel_notes': 'a'})
        r = self.patch({'manuel_notes': None})
        self.assertEqual(r.status_code, 200, r.data)
        x = self.fresh()
        self.assertEqual((x.manuel_notes, x.manuel_adjustment), ('', D('50.00')))

    def test_null_explicite_efface_et_restaure_le_calcul(self):
        self.patch({'manuel_adjustment': '50', 'manuel_notes': 'a'})
        r = self.patch({'manuel_adjustment': None})
        self.assertEqual(r.status_code, 200, r.data)
        x = self.fresh()
        self.assertEqual((x.manuel_adjustment, x.manuel_notes, x.net_payable), (None, '', D('9500.00')))

    def test_null_explicite_avec_notes_efface_l_ajustement(self):
        self.patch({'manuel_adjustment': '50'})
        r = self.patch({'manuel_adjustment': None, 'manuel_notes': 'garde ?'})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone(self.fresh().manuel_adjustment)

    def test_notes_non_chaine_jamais_500(self):
        for notes in (123, ['a'], {'a': 1}, True):
            with self.subTest(notes=notes):
                r = self.patch({'manuel_adjustment': '10', 'manuel_notes': notes})
                self.assertIn(r.status_code, (200, 400), (notes, r.status_code))
        self.assertEqual(api(self.direction).get(COMM).status_code, 200)

    def test_notes_tres_longues(self):
        r = self.patch({'manuel_adjustment': '10', 'manuel_notes': 'e' * 100000})
        self.assertIn(r.status_code, (200, 400))

    def test_exposants_gigantesques_aucun_empoisonnement(self):
        for v in ('1E999999999', '-1E999999999', '1E+99999999999', '1e-999999999', '-1e-999999999',
                  '0E-999999999', '9' * 400, '1' + '0' * 5000, '.' + '0' * 5000 + '1'):
            with self.subTest(v=v[:25]):
                before = self.fresh().manuel_adjustment
                r = self.patch({'manuel_adjustment': v})
                self.assertIn(r.status_code, (200, 400), (v[:25], r.status_code))
                if r.status_code == 400:
                    self.assertEqual(self.fresh().manuel_adjustment, before)
                self.assertEqual(api(self.direction).get(COMM).status_code, 200)

    def test_zero_est_un_ajustement_valide_distinct_de_null(self):
        r = self.patch({'manuel_adjustment': '0'})
        self.assertEqual(r.status_code, 200)
        x = self.fresh()
        self.assertEqual((x.manuel_adjustment, x.net_payable), (D('0.00'), D('0.00')))

    def test_bornes_exactes(self):
        for v, ok in (('999999999999.99', True), ('999999999999.994', True),
                      ('1000000000000', False), ('-1000000000000', False), ('-999999999999.99', True)):
            with self.subTest(v=v):
                r = self.patch({'manuel_adjustment': v})
                self.assertEqual(r.status_code, 200 if ok else 400, (v, r.data))
        self.assertEqual(api(self.direction).get(COMM).status_code, 200)

    def test_permissions(self):
        for u in (self.g1, self.f1, self.l1, self.comptable):
            with self.subTest(role=u.role):
                r = self.patch({'manuel_adjustment': '1'}, user=u)
                self.assertEqual(r.status_code, 403, (u.role, r.status_code))
        self.assertIsNone(self.fresh().manuel_adjustment)

    def test_commission_payee_refuse_aussi_pour_notes_seules(self):
        ClientCommission.objects.filter(pk=self.r.pk).update(is_paid=True)
        for body in ({'manuel_notes': 'x'}, {'manuel_adjustment': '5'}, {'manuel_adjustment': None}):
            with self.subTest(body=body):
                r = self.patch(body)
                self.assertEqual(r.status_code, 400, (body, r.status_code))
        x = self.fresh()
        self.assertEqual((x.manuel_notes, x.manuel_adjustment, x.net_payable), ('', None, D('9500.00')))

    def test_commission_inconnue_404(self):
        r = api(self.direction).patch(f'{COMM}{uuid.uuid4()}/set_manuel/', {'manuel_adjustment': '1'}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_decimal_exact_en_sortie(self):
        r = self.patch({'manuel_adjustment': '0.1'})
        self.assertEqual(r.data['net_payable'], '0.10')
        self.assertEqual(r.data['manuel_adjustment'], '0.10')
        self.assertIsInstance(self.fresh().net_payable, D)

    def test_corps_non_objet_sur_les_autres_actions_commissions(self):
        for url in (f'{COMM}{self.r.id}/mark_paid/', '/api/commissions/periods/generate/'):
            for body in ([], [1], 'x', 5):
                with self.subTest(url=url, body=body):
                    r = api(self.direction).post(url, body, format='json')
                    self.assertIn(r.status_code, (400, 415), (url, body, r.status_code))
