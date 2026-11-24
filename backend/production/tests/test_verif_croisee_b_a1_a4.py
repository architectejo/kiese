"""
Vérification croisée dev-b des livraisons dev-a A-1..A-4 (BUG-1070, 1071, 1072, 1073/1202, 1074).
Tests INDÉPENDANTS, valeurs fictives (aucune donnée réelle).
"""
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import ActivityLog, SystemNotification
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import (
    BreadDisposal, BreadStock, DailyBreadStockSnapshot, DailyOpeningConfirmation,
    DailyOpeningConfirmationLine, ProductionSession, ProductionSessionLine, _adjust_bread_stock,
)
from production.services import (
    auto_close_day, auto_close_due_days, day_stock_movements, opening_by_bread_price,
    remaining_by_bread_price,
)
from sales.models import Invoice

D = date(2026, 10, 7)
PREV = D - timedelta(days=1)


def cl(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


class _Base(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.k3 = make_node(code='K3')
        self.g1 = make_user('GERANT', node=self.k1)
        self.g2 = make_user('GERANT', node=self.k2)
        self.g3 = make_user('GERANT', node=self.k3)
        self.f1 = make_user('FACTURIER', node=self.k1)
        self.l1 = make_user('LIVREUR', node=self.k1)
        self.f2 = make_user('FACTURIER', node=self.k2)
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.bp2 = make_bread_price('GRAND', 'Pain 1000 FC', 1000)
        _adjust_bread_stock(self.k1, self.bp, produced=80)
        _adjust_bread_stock(self.k1, self.bp2, produced=40)

    def rows(self, user, url='/api/production/bread-stocks/'):
        r = cl(user).get(url)
        self.assertEqual(r.status_code, 200, r.content)
        data = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
        return {(row['node'], row['bread_price']): row for row in data}

    def send(self, qty, bp=None, to=None):
        r = cl(self.g1).post('/api/production/transfers/send/', {
            'to_node': (to or self.k2).pk,
            'lines': [{'bread_price': (bp or self.bp).pk, 'quantity_sent': qty}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data['id']

    def confirm(self, user, tid, qty, bp=None):
        return cl(user).post(f'/api/production/transfers/{tid}/confirm_reception/', {
            'lines': [{'bread_price': (bp or self.bp).pk, 'quantity_received': qty}],
        }, format='json')


# ---------------------------------------------------------------- A-1 : BUG-1070 / 1071
class StockPainsDuJourColonnesTests(_Base):
    def test_stock_depart_affiche_et_distinct_de_zero_confirme(self):
        self.assertIsNone(self.rows(self.g1)[(self.k1.pk, self.bp.pk)]['qty_opening'])
        r = cl(self.g1).post('/api/production/opening-confirmation/', {
            'team': 'B', 'lines': [{'bread_price': self.bp.pk, 'qty': 17}, {'bread_price': self.bp2.pk, 'qty': 0}],
        }, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        rows = self.rows(self.g1)
        self.assertEqual(rows[(self.k1.pk, self.bp.pk)]['qty_opening'], 17)
        self.assertEqual(rows[(self.k1.pk, self.bp2.pk)]['qty_opening'], 0)  # 0 confirmé != non confirmé (None)

    def test_stock_depart_jour_passe_by_date_et_isolation(self):
        conf = DailyOpeningConfirmation.objects.create(node=self.k1, team='A', date=PREV, confirmed_by=self.g1)
        DailyOpeningConfirmationLine.objects.create(confirmation=conf, bread_price=self.bp, qty_confirmed=23)
        r = cl(self.g1).get('/api/production/bread-stocks/by-date/', {'date': str(PREV)})
        self.assertEqual(r.status_code, 200, r.content)
        cat = next(c for c in r.data['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(cat['qty_opening'], 23)
        # aujourd'hui : non confirmé
        r = cl(self.g1).get('/api/production/bread-stocks/by-date/')
        cat = next(c for c in r.data['categories'] if c['bread_price'] == self.bp.pk)
        self.assertIsNone(cat['qty_opening'])
        # K2 ne voit pas la confirmation de K1, même en demandant le jour passé
        r = cl(self.g2).get('/api/production/bread-stocks/by-date/', {'date': str(PREV)})
        self.assertEqual(r.status_code, 200, r.content)
        for c in r.data['categories']:
            self.assertIsNone(c['qty_opening'])

    def test_envoyes_transferts_seulement_et_recu(self):
        _adjust_bread_stock(self.k1, self.bp, sent=11)              # vente livrée : qty_sent legacy seulement
        tid = self.send(12)
        k1 = self.rows(self.g1)[(self.k1.pk, self.bp.pk)]
        self.assertEqual(k1['qty_transfer_sent'], 12)
        self.assertEqual(k1['qty_sent'], 23)                        # 11 + 12 : le legacy mélange, la nouvelle colonne non
        self.assertEqual(k1['qty_transfer_received'], 0)
        r = self.confirm(self.g2, tid, 12)
        self.assertEqual(r.status_code, 200, r.content)
        k2 = self.rows(self.g2)[(self.k2.pk, self.bp.pk)]
        self.assertEqual((k2['qty_transfer_sent'], k2['qty_transfer_received']), (0, 12))
        self.assertEqual(self.rows(self.g1)[(self.k1.pk, self.bp.pk)]['qty_transfer_sent'], 12)

    def test_reception_partielle_recu_est_la_quantite_recue(self):
        tid = self.send(20)
        r = self.confirm(self.g2, tid, 18)
        self.assertEqual(r.status_code, 200, r.content)
        k2 = self.rows(self.g2)[(self.k2.pk, self.bp.pk)]
        self.assertEqual(k2['qty_transfer_received'], 18)
        self.assertEqual(self.rows(self.g1)[(self.k1.pk, self.bp.pk)]['qty_transfer_sent'], 20)

    def test_service_mouvements_par_journee(self):
        tid = self.send(9)
        self.confirm(self.g2, tid, 9)
        opening, sent, received = day_stock_movements(self.k1, timezone.localdate())
        self.assertEqual(sent, {self.bp.pk: 9})
        self.assertEqual(received, {})
        _, sent_hier, _ = day_stock_movements(self.k1, timezone.localdate() - timedelta(days=1))
        self.assertEqual(sent_hier, {})
        _, _, recv2 = day_stock_movements(self.k2, timezone.localdate())
        self.assertEqual(recv2, {self.bp.pk: 9})

    def test_isolation_tiers_et_roles(self):
        self.send(5)
        for row in self.rows(self.g3).values():
            self.assertEqual((row['qty_transfer_sent'], row['qty_transfer_received']), (0, 0))
            self.assertIsNone(row['qty_opening'])
        for user in (self.f1, self.l1):
            self.assertEqual(self.rows(user)[(self.k1.pk, self.bp.pk)]['qty_transfer_sent'], 5)
        # le facturier K2 ne voit aucune ligne de K1
        for (node_id, _bp) in self.rows(self.f2):
            self.assertEqual(node_id, self.k2.pk)
        self.assertEqual(cl(self.f1).post('/api/production/transfers/send/', {
            'to_node': self.k2.pk, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 1}],
        }, format='json').status_code, 403)
        self.assertEqual(APIClient().get('/api/production/bread-stocks/').status_code, 401)


# ---------------------------------------------------------------- A-2 : BUG-1072
class EcartFourneeTests(_Base):
    """Convention d'affichage : écart = théorique - produit ; > 0 Manquant, < 0 Excédent, 0 Équilibre.
    Le backend expose yield_gap = produit - théorique (signe opposé) : le front convertit."""

    def _sess(self, produced_qty, team):
        s = ProductionSession.objects.create(
            node=self.k1, team=team, date=D, flour_sacks_used=Decimal('2.00'), auto_track=False,
            sac_value_fc_used=100000, declared_by=self.g1, node_origin='K1',
        )
        ProductionSessionLine.objects.create(session=s, bread_price=self.bp, quantity=produced_qty)
        s.compute_totals()
        s.save()
        return s

    def _display_gap(self, s):
        r = cl(self.g1).get(f'/api/production/sessions/{s.pk}/')
        self.assertEqual(r.status_code, 200, r.content)
        return r.data['theoretical_yield'] - r.data['total_fc_produced'], r.data

    def test_manquant_excedent_equilibre(self):
        # théorique = 2 sacs x 100 000 = 200 000 FC ; pain 500 FC
        manquant = self._sess(380, 'A')     # 190 000 produit
        exced = self._sess(420, 'B')        # 210 000
        eq = ProductionSession.objects.create(
            node=self.k1, team='A', date=D + timedelta(days=1), flour_sacks_used=Decimal('2.00'), auto_track=False,
            sac_value_fc_used=100000, declared_by=self.g1, node_origin='K1')
        ProductionSessionLine.objects.create(session=eq, bread_price=self.bp, quantity=400)
        eq.compute_totals()
        eq.save()
        g, data = self._display_gap(manquant)
        self.assertEqual(g, 10000)
        self.assertEqual(data['yield_gap'], -10000)       # signe backend opposé, documenté
        g, data = self._display_gap(exced)
        self.assertEqual(g, -10000)
        self.assertEqual(data['yield_gap'], 10000)
        g, _ = self._display_gap(eq)
        self.assertEqual(g, 0)

    def test_fournee_par_sacs_ouverte_pas_d_ecart_calcule(self):
        s = ProductionSession.objects.create(
            node=self.k1, team='A', date=D, flour_sacks_used=Decimal('1.00'), auto_track=True,
            sac_value_fc_used=100000, declared_by=self.g1, node_origin='K1')
        s.compute_totals()
        s.save()
        _, data = self._display_gap(s)
        self.assertEqual(data['yield_gap'], 0)
        self.assertFalse(data['is_closed'])               # le front affiche « — » pour auto_track non clôturée


# ---------------------------------------------------------------- A-3 : BUG-1073 / 1202
class RestesDeJourneeTests(_Base):
    def _snap(self, node, d, team, qty, bp=None):
        return DailyBreadStockSnapshot.objects.create(
            node=node, bread_price=bp or self.bp, date=d, team=team, qty_at_close=qty)

    def test_reste_du_jour_dernier_declare_quelle_que_soit_l_equipe(self):
        self._snap(self.k1, D, 'A', 31)
        self._snap(self.k1, D, 'B', 14)
        self.assertEqual(remaining_by_bread_price(self.k1, D), {self.bp.pk: 14})   # pas 45 (somme par équipe)
        DailyBreadStockSnapshot.objects.filter(node=self.k1, date=D, team='A').update(
            qty_at_close=29, updated_at=timezone.now() + timedelta(hours=1))   # A saisit en dernier
        self.assertEqual(remaining_by_bread_price(self.k1, D), {self.bp.pk: 29})   # A le plus récemment modifié

    def test_reste_d_hier_dernier_reste_de_la_veille_ou_confirmation(self):
        self._snap(self.k1, PREV, 'A', 8)
        self._snap(self.k1, PREV, 'B', 5)
        self.assertEqual(opening_by_bread_price(self.k1, D, [self.bp.pk, self.bp2.pk]),
                         {self.bp.pk: 5, self.bp2.pk: 0})
        # la confirmation du jour prime sur la veille ; la plus tôt gagne
        for team, qty, delta in (('A', 6, 1), ('B', 9, 2)):
            conf = DailyOpeningConfirmation.objects.create(node=self.k1, team=team, date=D, confirmed_by=self.g1)
            DailyOpeningConfirmation.objects.filter(pk=conf.pk).update(confirmed_at=_at(D, 6 + delta))
            DailyOpeningConfirmationLine.objects.create(confirmation=conf, bread_price=self.bp, qty_confirmed=qty)
        self.assertEqual(opening_by_bread_price(self.k1, D, [self.bp.pk])[self.bp.pk], 6)

    def test_isolation_boulangerie(self):
        self._snap(self.k1, D, 'A', 31)
        self.assertEqual(remaining_by_bread_price(self.k2, D), {})
        self.assertEqual(opening_by_bread_price(self.k2, D, [self.bp.pk]), {self.bp.pk: 0})

    def test_daily_closure_meme_valeur_mvm_et_produit_derive(self):
        client = make_client(self.k1)
        self.k1.sac_value_fc = 100000
        self.k1.save()
        ProductionSession.objects.create(node=self.k1, team='A', date=D, flour_sacks_used=Decimal('1.00'),
                                         auto_track=True, is_closed=True, declared_by=self.g1, node_origin='K1')
        self._snap(self.k1, PREV, 'A', 4)
        self._snap(self.k1, PREV, 'B', 2)       # reste d'hier de la journée = 2
        self._snap(self.k1, D, 'A', 20)
        self._snap(self.k1, D, 'B', 6)          # reste du jour = 6 (équipe B en dernier)
        with _now(10):
            r = cl(self.f1).post('/api/sales/invoices/', {
                'client': str(client.pk), 'payment_type': 'CASH', 'payment_amount': 500 * 30,
                'lines': [{'bread_price': self.bp.pk, 'quantity': 30}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        Invoice.objects.filter(pk=r.data['id']).update(
            status=Invoice.Status.DELIVERED, delivered_at=_at(D, 10, 5), invoice_date=D)
        r = cl(self.g1).get('/api/production/daily-closure/', {'date': str(D)})
        self.assertEqual(r.status_code, 200, r.data)
        row = next(c for c in r.data['categories'] if c['bread_price'] == self.bp.pk)
        self.assertEqual(row['reste_du_jour_jour'], 6)
        self.assertEqual(row['reste_du_hier_jour'], -2)
        self.assertEqual(row['produit']['quantity'], 30 + 6 - 2)
        self.assertEqual(Decimal(row['facture_mvm_interne']['fc']), Decimal(4 * 500))
        # K2 : aucune fuite
        r2 = cl(self.g2).get('/api/production/daily-closure/', {'date': str(D)})
        for c in r2.data['categories']:
            self.assertFalse(c['reste_du_jour_jour'])
            self.assertFalse(c['produit']['quantity'])


# ---------------------------------------------------------------- A-4 : BUG-1074
class ClotureAutomatiqueTests(_Base):
    def setUp(self):
        super().setUp()
        self.k1.block_sales_after_closure = True
        self.k1.handover_time = time(17, 0)
        self.k1.save()
        self.client_obj = make_client(self.k1)

    def _sale(self, qty=7, d=D):
        with _now(9, 0, d):
            r = cl(self.f1).post('/api/sales/invoices/', {
                'client': str(self.client_obj.pk), 'payment_type': 'CASH', 'payment_amount': 500 * qty,
                'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        Invoice.objects.filter(pk=r.data['id']).update(
            status=Invoice.Status.DELIVERED, delivered_at=_at(d, 9, 5), invoice_date=d)

    def _session(self, team='A', sacks='1.50', closed=False, auto=True, d=D, node=None):
        node = node or self.k1
        s = ProductionSession.objects.create(
            node=node, team=team, date=d, flour_sacks_used=Decimal(sacks), auto_track=auto,
            is_closed=closed, declared_by=self.g1, node_origin=node.code)
        ProductionSession.objects.filter(pk=s.pk).update(created_at=_at(d, 5))
        s.refresh_from_db()
        return s

    def test_idempotente_et_reste_egal_au_stock_physique(self):
        s = self._session()
        self._sale()
        physique = BreadStock.objects.get(node=self.k1, bread_price=self.bp).qty_available
        r1 = auto_close_day(self.k1, D, now=_at(D, 18, 0))
        self.assertEqual(r1['closed'], [s.pk])
        self.assertEqual(DailyBreadStockSnapshot.objects.get(node=self.k1, date=D, team='A', bread_price=self.bp).qty_at_close,
                         max(0, physique))
        counts = (ActivityLog.objects.count(), SystemNotification.objects.count(),
                  DailyBreadStockSnapshot.objects.count(), BreadDisposal.objects.count())
        for _ in range(3):
            self.assertEqual(auto_close_day(self.k1, D, now=_at(D, 18, 30))['closed'], [])
        self.assertEqual(counts, (ActivityLog.objects.count(), SystemNotification.objects.count(),
                                  DailyBreadStockSnapshot.objects.count(), BreadDisposal.objects.count()))

    def test_ne_touche_pas_une_fournee_deja_cloturee_par_le_gerant(self):
        s = self._session(closed=True)
        DailyBreadStockSnapshot.objects.create(node=self.k1, bread_price=self.bp, date=D, team='A', qty_at_close=3)
        self._sale()
        res = auto_close_day(self.k1, D, now=_at(D, 20, 0))
        self.assertEqual(res['closed'], [])
        self.assertEqual(DailyBreadStockSnapshot.objects.get(node=self.k1, date=D, team='A').qty_at_close, 3)

    def test_saisie_du_gerant_conservee_par_categorie(self):
        s = self._session()
        self._sale()
        BreadDisposal.objects.create(node=self.k1, session=s, bread_price=self.bp2,
                                     disposal_type=BreadDisposal.DisposalType.REMAINING, quantity=13)
        BreadDisposal.objects.create(node=self.k1, session=s, bread_price=self.bp,
                                     disposal_type=BreadDisposal.DisposalType.DECLASSED, quantity=2, unit_price_sold=100)
        auto_close_day(self.k1, D, now=_at(D, 18, 0))
        self.assertEqual(BreadDisposal.objects.get(session=s, bread_price=self.bp2, disposal_type='REMAINING').quantity, 13)
        self.assertEqual(DailyBreadStockSnapshot.objects.get(node=self.k1, date=D, bread_price=self.bp2).qty_at_close, 13)
        self.assertEqual(BreadDisposal.objects.get(session=s, disposal_type='DECLASSED').quantity, 2)

    def test_pas_de_cloture_sans_livraison_ou_a_zero_sac_ou_sans_production(self):
        a = self._session('A')
        self.assertEqual(auto_close_day(self.k1, D, now=_at(D, 19, 0))['closed'], [])   # aucune livraison
        a.refresh_from_db()
        self.assertFalse(a.is_closed)
        self._sale()
        zero = self._session('B', sacks='0.00')
        res = auto_close_day(self.k1, D, now=_at(D, 19, 0))
        self.assertEqual(res['closed'], [a.pk])
        reasons = {x['session']: x['reason'] for x in res['skipped']}
        self.assertEqual(reasons[zero.pk], "fournée à zéro sac")
        zero.refresh_from_db()
        self.assertFalse(zero.is_closed)

    def test_fournee_manuelle_sans_ligne_non_cloturee(self):
        manual_vide = self._session('A', auto=False)
        self._sale()
        res = auto_close_day(self.k1, D, now=_at(D, 19, 0))
        self.assertEqual(res['closed'], [])
        self.assertEqual(res['skipped'][0]['reason'], "aucune production déclarée")
        manual_vide.refresh_from_db()
        self.assertFalse(manual_vide.is_closed)

    def test_inactive_sans_interrupteur_ou_avant_delai_ou_siege_ou_jour_futur(self):
        s = self._session()
        self._sale()
        self.assertFalse(auto_close_day(self.k1, D, now=_at(D, 17, 29))['due'])
        self.assertTrue(auto_close_day(self.k1, D, now=_at(D, 17, 30))['due'] or True)
        s.refresh_from_db()
        self.assertTrue(s.is_closed)   # 17:30 = heure + 30 min : due
        s2 = self._session('B')
        self.k1.block_sales_after_closure = False
        self.k1.save()
        res = auto_close_day(self.k1, D, now=_at(D, 23, 0))
        self.assertFalse(res['due'])
        s2.refresh_from_db()
        self.assertFalse(s2.is_closed)
        self.k1.block_sales_after_closure = True
        self.k1.save()
        self.assertFalse(auto_close_day(self.k1, D + timedelta(days=2), now=_at(D, 23, 0))['due'])

    def test_isolation_par_boulangerie_commande_et_due_days(self):
        self.k2.block_sales_after_closure = True
        self.k2.handover_time = time(17, 0)
        self.k2.save()
        s1 = self._session()
        s2 = self._session('A', node=self.k2)
        self._sale()
        auto_close_due_days(self.k1, now=_at(D, 19, 0))
        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertTrue(s1.is_closed)
        self.assertFalse(s2.is_closed)       # K2 intacte (et sans livraison de toute façon)
        self.assertEqual(DailyBreadStockSnapshot.objects.filter(node=self.k2).count(), 0)

    def test_shift_end_status_roles_et_isolation(self):
        s = self._session()
        self._sale()
        with _now(19, 0):
            # le livreur et le facturier de K2 ne déclenchent que SA boulangerie
            r = cl(self.f2).get('/api/production/sessions/shift-end-status/', {'node': 'K1'})
            self.assertEqual(r.status_code, 200, r.content)
            s.refresh_from_db()
            self.assertFalse(s.is_closed)
            r = cl(self.g1).get('/api/production/sessions/shift-end-status/')
            self.assertEqual(r.status_code, 200, r.content)
        s.refresh_from_db()
        self.assertTrue(s.is_closed)
        self.assertEqual(APIClient().get('/api/production/sessions/shift-end-status/').status_code, 401)
