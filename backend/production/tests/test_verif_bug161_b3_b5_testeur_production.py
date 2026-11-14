"""
Vérification BUG-161 volet production, étapes B3 (production), B4, B5, F2/F3
(testeur-production, 2026-11-12). Tests indépendants de ceux du développeur.

Horloge simulée : `django.utils.timezone.now` renvoie un datetime UTC aware
(comme le vrai), Kinshasa = UTC+1. BUG-247 (décision client 2026-11-12) : la
date de travail est le JOUR CALENDAIRE local, avec ou sans rotation ; seule
l'équipe change à la relève (périodes de service de relève à relève).
"""
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import (
    BreadStock, DailyBreadStockSnapshot, DailyOpeningConfirmation, DailyTeamAssignment,
    ProductionSession, ProductionSessionLine,
)
from sales.models import Invoice

J = date(2026, 11, 12)
J1 = date(2026, 11, 13)
J2 = date(2026, 11, 14)
ASSIGN = '/api/production/team-assignment/'
OPENING = '/api/production/opening-confirmation/'
SESSIONS = '/api/production/sessions/'
SHIFT = '/api/production/sessions/shift-end-status/'
CLOSURE = '/api/production/daily-closure/'
BYDATE = '/api/production/bread-stocks/by-date/'


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=J):
    """Heure LOCALE (Kinshasa) simulée, servie en UTC aware."""
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


def _utc(y, mo, d, h, mi):
    return patch('django.utils.timezone.now', return_value=datetime(y, mo, d, h, mi, tzinfo=dt_timezone.utc))


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', sac_value_fc=Decimal('200000'))
        self.bp500 = make_bread_price('VB35_500', 'Pain 500 FC', 500)
        self.bp300 = make_bread_price('VB35_300', 'Pain 300 FC', 300)
        self.bp200 = make_bread_price('VB35_200', 'Pain 200 FC', 200)
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.facturier = make_user('FACTURIER', node=self.node, team='A')
        self.client1 = make_client(self.node, credit_limit=Decimal('900000.00'))
        self.g = APIClient()
        self.g.force_authenticate(self.gerant)
        self.f = APIClient()
        self.f.force_authenticate(self.facturier)

    def _rotation(self, node=None, handover=time(12, 0)):
        node = node or self.node
        node.team_rotation_enabled = True
        node.handover_time = handover
        node.save()

    def _assign(self, team, api=None):
        r = (api or self.g).post(ASSIGN, {'team': team}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        return r

    def _produce(self, qtys, sacs='2.00', api=None):
        payload = {
            'flour_sacks_used': sacs,
            'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in qtys],
        }
        r = (api or self.g).post(SESSIONS, payload, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r

    def _invoice(self, bp, qty, code='', deliver=True, api=None):
        api = api or self.f
        total = Decimal(bp.unit_price) * qty
        payload = {
            'payment_type': 'CASH' if not code else 'CREDIT',
            'payment_amount': str(total) if not code else '0.00',
            'special_code': code,
            'client': str(self.client1.pk),
            'lines': [{'bread_price': bp.pk, 'quantity': qty}],
        }
        r = api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        if deliver and code != 'NS':
            d = api.post(f"/api/sales/invoices/{r.data['id']}/deliver/")
            self.assertEqual(d.status_code, 200, d.data)
        return r.data

    def _stock(self, bp, node=None):
        return BreadStock.objects.get(node=node or self.node, bread_price=bp).qty_available

    def _rows(self, response):
        return {row['bread_price']: row for row in response.data['categories']}

    def _proposed(self, response):
        return {c['bread_price']: c['qty_proposed'] for c in response.data['categories']}

    def _session_row(self, d, team):
        return ProductionSession.objects.filter(node=self.node, date=d, team=team).values().get()

    def _snaps(self, d):
        return list(
            DailyBreadStockSnapshot.objects.filter(node=self.node, date=d)
            .order_by('bread_price_id', 'team')
            .values_list('bread_price_id', 'team', 'qty_at_close', 'updated_at')
        )


def _strip(report_data):
    """Rapport sans les champs d'horloge (identiques ici, mais on isole le contenu)."""
    return {k: v for k, v in report_data.items() if k not in ('server_now', 'work_date')}


class FullRotationDayTests(_Base):
    """Scénarios (1), (2), (3) : journée complète puis chaînage A -> B -> A."""

    def test_full_cycle_a_to_b_to_a(self):
        self._rotation()
        bp5, bp3, bp2 = self.bp500, self.bp300, self.bp200

        # ---- J 12:05 : désignation A, stock de départ, fournée -------------
        with _now(12, 5):
            self._assign('A')
            r = self.g.get(OPENING)
            self.assertTrue(r.data['needs_confirmation'])
            self.assertEqual(r.data['opening_team'], 'A')
            self.assertEqual(self._proposed(r)[bp5.pk], 0)
            c = self.g.post(OPENING, {'lines': [
                {'bread_price': bp5.pk, 'qty': 5}, {'bread_price': bp3.pk, 'qty': 0},
            ]}, format='json')
            self.assertEqual(c.status_code, 200, c.data)
            self.assertEqual(c.data['work_date'], '2026-11-12')
        with _now(14, 0):
            self._produce([(bp5, 100), (bp3, 40)])

        # ---- J 20:00 : ventes de l'équipe A (période démarrée à 12:00) -----
        with _now(20, 0):
            inv1 = self._invoice(bp5, 60)
            inv2 = self._invoice(bp3, 70)          # dépasse le disponible : reste négatif
            ns = self._invoice(bp5, 5, code='NS')  # non servi (pas de stock)
            for i in (inv1, inv2, ns):
                inv = Invoice.objects.get(pk=i['id'])
                self.assertEqual(inv.invoice_date, J, 'jour calendaire de la vente')
                self.assertEqual(inv.team, 'A')
        self.assertEqual(self._stock(bp5), 45)
        self.assertEqual(self._stock(bp3), -30)

        sess_j = ProductionSession.objects.get(node=self.node, date=J, team='A')
        self.assertEqual(sess_j.date, J, 'fournée de 14:00 (J) rattachée à J')
        self.assertFalse(sess_j.is_closed)

        # ---- J+1 : passage de minuit (reste du jour J, session J1 ouverte pour A),
        # puis relève : annonce à 12:10, clôture forcée à 12:30
        with _now(11, 59, d=J1):
            r = self.g.get(SHIFT)
            self.assertFalse(r.data['pending_validation'])
            self.assertTrue(r.data['auto_closed'])  # reste du jour J enregistré
            self.assertEqual(r.data['work_date'], '2026-11-12')
        with _now(12, 10, d=J1):
            r = self.g.get(SHIFT)
            self.assertTrue(r.data['pending_validation'])
            self.assertEqual(r.data['team'], 'A')
            self.assertEqual(r.data['work_date'], '2026-11-13')
            rem = {x['bread_price']: x['quantity_suggested'] for x in r.data['remaining']}
            self.assertEqual(rem[bp5.pk], 45)
            self.assertEqual(rem[bp3.pk], -30)
            self.assertNotIn(bp2.pk, rem)  # catégorie sans stock : absente
            # La désignation est requise, le stock de départ pas encore proposé.
            o = self.g.get(OPENING)
            self.assertTrue(o.data['team_assignment_required'])
            self.assertFalse(o.data['needs_confirmation'])
        with _now(12, 30, d=J1):
            r = self.g.get(SHIFT)
            self.assertTrue(r.data['auto_closed'])
            self.assertEqual(r.data['team'], 'A')
        sess_j.refresh_from_db()
        self.assertTrue(sess_j.is_closed)
        snaps_j = {(b, t): q for b, t, q, _ in self._snaps(J)}
        self.assertEqual(snaps_j[(bp5.pk, 'A')], 45)
        self.assertEqual(snaps_j[(bp3.pk, 'A')], -30)
        self.assertTrue(SystemNotification.objects.filter(severity='WARNING').exists())

        # ---- J+1 12:31 : désignation B, stock de départ = reste de A -------
        with _now(12, 31, d=J1):
            t = self.g.get(ASSIGN)
            self.assertIsNone(t.data['team'])
            self.assertEqual(t.data['suggested'], 'B')
            self._assign('B')
            o = self.g.get(OPENING)
            self.assertTrue(o.data['needs_confirmation'])
            self.assertEqual(o.data['opening_team'], 'B')
            prop = self._proposed(o)
            self.assertEqual(prop[bp5.pk], 45)   # reste de A chaîné
            self.assertEqual(prop[bp3.pk], -30)  # NÉGATIF conservé
            self.assertEqual(prop[bp2.pk], 0)    # catégorie absente

            # ---- (2) GARDE : confirmer/modifier J+1 ne touche pas J --------
            before_report = _strip(self.g.get(CLOSURE, {'date': str(J)}).data)
            before_session = self._session_row(J, 'A')
            before_snaps = self._snaps(J)
            c = self.g.post(OPENING, {'lines': [
                {'bread_price': bp5.pk, 'qty': 44}, {'bread_price': bp3.pk, 'qty': -30},
            ]}, format='json')
            self.assertEqual(c.status_code, 200, c.data)
            c = self.g.post(OPENING, {'lines': [
                {'bread_price': bp5.pk, 'qty': 40}, {'bread_price': bp3.pk, 'qty': -30},
            ]}, format='json')
            self.assertEqual(c.status_code, 200, c.data)
            self.assertEqual(_strip(self.g.get(CLOSURE, {'date': str(J)}).data), before_report)
            self.assertEqual(self._session_row(J, 'A'), before_session)
            self.assertEqual(self._snaps(J), before_snaps)
        self.assertEqual(
            DailyOpeningConfirmation.objects.filter(node=self.node, date=J1).count(), 1,
            'une seule confirmation par journée de travail',
        )
        self.assertEqual(self._stock(bp5), 40)

        # ---- J+1 13:00 : B produit 10 et vend 20 + un NS de 5 --------------
        with _now(13, 0, d=J1):
            self._produce([(bp5, 10)])
            inv = Invoice.objects.get(pk=self._invoice(bp5, 20)['id'])
            self.assertEqual((inv.invoice_date, inv.team), (J1, 'B'))
            self._invoice(bp5, 5, code='NS')
        self.assertEqual(self._stock(bp5), 30)

        # ---- (3) rapport J+1 recalculé à la main ---------------------------
        with _now(14, 0, d=J1):
            rep = self.g.get(CLOSURE, {'date': str(J1)})
        rows = self._rows(rep)
        r5 = rows[bp5.pk]
        self.assertEqual(r5['produit'], {'quantity': 10, 'fc': '5000.00'})  # CARRYOVER exclu (BUG-142)
        self.assertEqual(r5['facture_jr']['fc'], '10000.00')
        # BUG-247 : début de journée porté UNE seule fois, par l'équipe en service à minuit (A) :
        # reste de A (45) corrigé de l'écart constaté par B à la relève (40 confirmé : -5).
        self.assertEqual(r5['reste_du_hier'], {'A': -40, 'B': 0})
        self.assertEqual(r5['non_servi']['fc'], '2500.00')
        self.assertEqual(r5['facture_mvm_interne']['fc'], str(Decimal('-20000') - Decimal('2500')) + '.00')
        self.assertEqual(rows[bp3.pk]['reste_du_hier'], {'A': 30, 'B': 0})
        # total = facture + mvm_interne = 10000 + (-22500) + (0 sans reste du jour) ...
        # reste du jour non encore clôturé -> on contrôle la formule après clôture ci-dessous.

        # ---- clôture de B à J+2 12:30 (chaînage B -> A) ---------------------
        with _now(12, 30, d=J2):
            r = self.g.get(SHIFT)
            self.assertTrue(r.data['auto_closed'])
            self.assertEqual(r.data['team'], 'B')
            self.assertEqual(r.data['work_date'], '2026-11-13')
        snaps_j1 = {(b, t): q for b, t, q, _ in self._snaps(J1)}
        self.assertEqual(snaps_j1[(bp5.pk, 'B')], 30)
        self.assertEqual(snaps_j1[(bp3.pk, 'B')], -30)
        with _now(12, 31, d=J2):
            self._assign('A')
            o = self.g.get(OPENING)
            prop = self._proposed(o)
            self.assertEqual(prop[bp5.pk], 30)
            self.assertEqual(prop[bp3.pk], -30)
            rep1 = self.g.get(CLOSURE, {'date': str(J1)})
            rep0 = self.g.get(CLOSURE, {'date': str(J)})

        # Journée J1 (B) : total = facture + Σ(reste_jour + reste_hier)*prix - NS
        rows = self._rows(rep1)
        total = Decimal(rep1.data['totals']['total_du_jour_fc'])
        # 10000 (facture 500) + [30*500 - 40*500 = -5000] + [(-30)*300 + 30*300 = 0] - 2500 (NS)
        self.assertEqual(total, Decimal('2500.00'))
        # = valeur produite déclarée (10 x 500) moins le non-servi (2 x 2500 NS comptés une fois) :
        self.assertEqual(Decimal(rows[bp5.pk]['produit']['fc']) - Decimal('2500'), total)

        # Journée J (A) : 100x500 + 40x300 = 62000 produits ; NS 5x500 = 2500 retranchés
        rows0 = self._rows(rep0)
        self.assertEqual(rows0[bp5.pk]['produit']['quantity'], 100)  # DECLARED seul, pas 105
        self.assertEqual(rows0[bp5.pk]['reste_du_hier'], {'A': -5, 'B': 0})
        self.assertEqual(rows0[bp5.pk]['reste_du_jour'], {'A': 45, 'B': None})
        total0 = Decimal(rep0.data['totals']['total_du_jour_fc'])
        self.assertEqual(total0, Decimal('62000') - Decimal('2500'))
        pct = rep0.data['totals']['repartition_pct_par_quantite']
        self.assertEqual(sum(Decimal(p['pct']) for p in pct), Decimal('100.00'))  # BUG-186
        self.assertEqual(rep0.data['totals']['total_breads_produced'], 145)  # carryover inclus (BUG-142)

    def test_stale_snapshot_proposed_for_category_absent_from_last_closure(self):
        """Caractérisation (non ticket) : catégorie absente du dernier snapshot -> dernier snapshot connu."""
        self._rotation()
        DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp200, date=J - timedelta(days=5), team='A', qty_at_close=7)
        with _now(12, 5):
            self._assign('B')
            o = self.g.get(OPENING)
        self.assertEqual(self._proposed(o)[self.bp200.pk], 7)


class OpeningPostGuardsTests(_Base):
    """Scénario (8)."""

    def _counts(self):
        return (
            DailyOpeningConfirmation.objects.count(),
            ProductionSession.objects.count(),
            BreadStock.objects.count(),
            sum(b.qty_adjusted for b in BreadStock.objects.all()),
        )

    def _post(self, **extra):
        payload = {'lines': [{'bread_price': self.bp500.pk, 'qty': 9}]}
        payload.update(extra)
        return self.g.post(OPENING, payload, format='json')

    def test_guards_without_any_write(self):
        self._rotation()
        with _now(13, 0):
            before = self._counts()
            # sans désignation : 403 TEAM_NOT_ASSIGNED
            r = self._post()
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.data['code'], 'TEAM_NOT_ASSIGNED')
            self.assertEqual(self._counts(), before)
            # date différente de la journée courante : 400 (avant même la désignation)
            for bad in ('2026-11-11', '2026-11-13'):
                r = self._post(date=bad)
                self.assertEqual(r.status_code, 400, r.data)
                self.assertEqual(self._counts(), before)
            self._assign('A')
            before = self._counts()
            # équipe différente de la désignée : 400
            r = self._post(team='B')
            self.assertEqual(r.status_code, 400, r.data)
            self.assertEqual(self._counts(), before)
            r = self._post(date='2026-11-11', team='A')
            self.assertEqual(r.status_code, 400, r.data)
            self.assertEqual(self._counts(), before)
            # l'équipe désignée + date courante explicite : acceptée
            r = self._post(team='A', date='2026-11-12')
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(DailyOpeningConfirmation.objects.count(), before[0] + 1)

    def test_bug194_non_object_body_on_opening_post(self):
        """BUG-194 (réserve de BUG-187) : corps JSON non objet sur opening-confirmation -> 500."""
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            r = self.g.post(OPENING, ['A'], format='json')
        self.assertLess(r.status_code, 500, 'corps JSON non objet : jamais de 500')


class MidnightTests(_Base):
    """Scénario (6) : entre 00:00 et 01:00 locale = date UTC de la veille."""

    def test_work_date_and_server_now_are_local(self):
        self._rotation()
        k3 = make_node(code='K3')  # sans rotation
        g3 = make_user('GERANT', node=k3)
        api3 = APIClient()
        api3.force_authenticate(g3)
        with _utc(2026, 11, 11, 23, 30):  # = 2026-11-12 00:30 à Kinshasa
            o = self.g.get(OPENING)
            self.assertEqual(o.data['work_date'], '2026-11-12')  # BUG-247 : jour calendaire local, même en rotation
            self.assertTrue(o.data['server_now'].startswith('2026-11-12T00:30'), o.data['server_now'])
            s = self.g.get(SHIFT)
            self.assertEqual(s.data['current_work_date'], '2026-11-12')
            self.assertTrue(s.data['server_now'].startswith('2026-11-12T00:30'))
            b = self.g.get(BYDATE, {'date': '2026-11-12'})
            self.assertEqual(b.data['work_date'], '2026-11-12')
            rep = self.g.get(CLOSURE, {'date': '2026-11-11'})
            self.assertEqual(rep.data['work_date'], '2026-11-12')
            # nœud SANS rotation : date calendaire LOCALE (12/11), jamais la date UTC (11/11)
            o3 = api3.get(OPENING)
            self.assertEqual(o3.data['work_date'], '2026-11-12')
            self.assertEqual(o3.data['date'], '2026-11-12')
            self.assertNotIn('rotation', o3.data)
            s3 = api3.get(SHIFT)
            self.assertEqual(s3.data, {'pending_validation': False})
            c3 = api3.post(OPENING, {'team': 'A', 'lines': [{'bread_price': self.bp500.pk, 'qty': 3}]}, format='json')
            self.assertEqual(c3.status_code, 200, c3.data)
        self.assertEqual(DailyOpeningConfirmation.objects.get(node=k3).date, date(2026, 11, 12))

    def test_rotation_just_after_midnight_rolls_the_calendar_day_not_the_handover(self):
        self._rotation()
        s = ProductionSession.objects.create(
            node=self.node, team='A', date=J, declared_by=self.gerant, node_origin='K1')
        DailyTeamAssignment.objects.create(node=self.node, work_date=J, team='A')
        # BUG-247 : 00:30 locale le 13/11 : minuit a changé la date de travail ; l'équipe A
        # (période démarrée le 12/11 à 12:00) continue : session du 12/11 clôturée (reste du
        # jour 12/11), session du 13/11 ouverte pour A — pas de validation de relève.
        with _utc(2026, 11, 12, 23, 30):
            r = self.g.get(SHIFT)
        self.assertFalse(r.data['pending_validation'])
        self.assertTrue(r.data['auto_closed'])
        self.assertEqual(r.data['current_work_date'], '2026-11-13')
        s.refresh_from_db()
        self.assertTrue(s.is_closed)
        self.assertTrue(ProductionSession.objects.filter(node=self.node, team='A', date=J1, is_closed=False).exists())


class SeveralOpenDaysTests(_Base):
    """Scénario (4)."""

    def test_three_open_days_closed_one_per_call_in_order_idempotent(self):
        self._rotation()
        d1, d2, d3 = J - timedelta(days=2), J - timedelta(days=1), J
        sessions = []
        for d, team in ((d3, 'A'), (d1, 'A'), (d2, 'B')):  # ordre de création volontairement mélangé
            DailyTeamAssignment.objects.create(node=self.node, work_date=d, team=team)
            s = ProductionSession.objects.create(
                node=self.node, team=team, date=d, declared_by=self.gerant, node_origin='K1')
            ProductionSessionLine.objects.create(session=s, bread_price=self.bp500, quantity=3)
            sessions.append(s)
        BreadStock.objects.create(node=self.node, bread_price=self.bp500, qty_produced=2, qty_disposed=5)  # -3
        neg = lambda: SystemNotification.objects.filter(severity='WARNING', title__startswith='Stock de pain').count()
        notes_before = neg()
        with _now(15, 0, d=J1):  # personne connecté depuis 3 jours
            seen = []
            for _ in range(3):
                r = self.g.get(SHIFT)
                self.assertTrue(r.data['auto_closed'], r.data)
                seen.append(r.data['work_date'])
            self.assertEqual(seen, [str(d1), str(d2), str(d3)])
            r = self.g.get(SHIFT)
            self.assertFalse(r.data['pending_validation'])
            self.assertNotIn('auto_closed', r.data)
            r = self.g.get(SHIFT)  # idempotence BUG-165
            self.assertFalse(r.data['pending_validation'])
        self.assertEqual(
            sorted(DailyBreadStockSnapshot.objects.filter(node=self.node).values_list('date', 'team', 'qty_at_close')),
            [(d1, 'A', -3), (d2, 'B', -3), (d3, 'A', -3)],
        )
        self.assertEqual(neg() - notes_before, 3, 'une notification WARNING par reste négatif, aucune duplication')
        self.assertTrue(all(ProductionSession.objects.get(pk=s.pk).is_closed for s in sessions))

    def test_stale_open_day_inside_grace_blocks_nothing_newer(self):
        self._rotation()
        DailyTeamAssignment.objects.create(node=self.node, work_date=J, team='A')
        s = ProductionSession.objects.create(node=self.node, team='A', date=J, declared_by=self.gerant, node_origin='K1')
        with _now(12, 15, d=J1):
            r = self.g.get(SHIFT)
        self.assertTrue(r.data['pending_validation'])
        self.assertEqual(r.data['session'], s.pk)
        s.refresh_from_db()
        self.assertFalse(s.is_closed)


class TwoNodesTests(_Base):
    """Scénario (5) : relèves 12:00 (K1) et 18:30 (K2), K3 sans rotation."""

    def test_independent_work_days(self):
        k2 = make_node(code='K2')
        k3 = make_node(code='K3')
        self._rotation()
        self._rotation(k2, handover=time(18, 30))
        g2 = make_user('GERANT', node=k2)
        g3 = make_user('GERANT', node=k3)
        a2, a3 = APIClient(), APIClient()
        a2.force_authenticate(g2)
        a3.force_authenticate(g3)
        for node, gerant in ((self.node, self.gerant), (k2, g2)):
            DailyTeamAssignment.objects.create(node=node, work_date=J, team='A')
            s_ = ProductionSession.objects.create(node=node, team='A', date=J, declared_by=gerant, node_origin=node.code)
            # BUG-247 : session créée dans la période de service en cours (1 h après sa relève).
            ProductionSession.objects.filter(pk=s_.pk).update(
                created_at=_at(J, 13) if node is self.node else _at(J, 19))
        with _now(12, 10, d=J1):
            r1, r2, r3 = self.g.get(SHIFT), a2.get(SHIFT), a3.get(SHIFT)
            self.assertTrue(r1.data['pending_validation'])
            self.assertEqual(r1.data['current_work_date'], '2026-11-13')
            self.assertFalse(r2.data['pending_validation'])
            self.assertEqual(r2.data['current_work_date'], '2026-11-13')  # BUG-247 : date calendaire commune
            self.assertEqual(r3.data, {'pending_validation': False})
            self.assertEqual(self.g.get(OPENING).data['date'], '2026-11-13')
            self.assertEqual(a2.get(OPENING).data['date'], '2026-11-13')  # date calendaire ; équipe de la période en cours
            self.assertEqual(a3.get(OPENING).data['date'], '2026-11-13')
        with _now(18, 45, d=J1):
            self.assertTrue(a2.get(SHIFT).data['pending_validation'])
            self.assertTrue(self.g.get(SHIFT).data['auto_closed'])  # K1 : 6 h après sa relève
        # K2 : la session du 12/11 a été clôturée au passage de minuit (reste du 12/11) ;
        # celle du 13/11 (même équipe) est ouverte, en grâce depuis sa relève de 18:30.
        self.assertTrue(ProductionSession.objects.get(node=k2, date=J).is_closed)
        self.assertFalse(ProductionSession.objects.get(node=k2, date=J1).is_closed)
        # La désignation d'un nœud ne remplit pas l'autre
        with _now(18, 40, d=J1):
            self.assertTrue(a2.get(OPENING).data['team_assignment_required'])
            self.assertEqual(self.g.get(OPENING).data['team_assignment_required'], True)

    def test_designation_does_not_leak_between_nodes(self):
        k2 = make_node(code='K2')
        self._rotation()
        self._rotation(k2)
        g2 = make_user('GERANT', node=k2)
        a2 = APIClient()
        a2.force_authenticate(g2)
        with _now(13, 0):
            self._assign('B')
            self.assertIsNone(a2.get(ASSIGN).data['team'])
            self.assertEqual(self.g.get(ASSIGN).data['team'], 'B')


class DesignationCorrectionDefectsTests(_Base):
    """Défauts trouvés par relecture croisée de B4/B5 (voir registre)."""

    def test_bug190_open_session_of_corrected_team_is_still_closed(self):
        """BUG-190 : la désignation est corrigée A -> B après une fournée de A : la session de A ne se clôture jamais."""
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            self._produce([(self.bp500, 10)])
        with _now(14, 0):
            self._assign('B')  # correction autorisée (sidebar « changer »)
        with _now(13, 0, d=J1):
            r = self.g.get(SHIFT)
        self.assertTrue(r.data.get('auto_closed') or r.data.get('pending_validation'), r.data)
        self.assertEqual(DailyBreadStockSnapshot.objects.filter(node=self.node, date=J).count(), 1)

    def test_bug191_designation_change_after_confirmation_double_counts_reste_du_hier(self):
        """BUG-191 : changer l'équipe désignée après la confirmation du départ double le reste_du_hier du rapport."""
        self._rotation()
        with _now(20, 0):  # BUG-297 : updated_at sur l'horloge simulée
            DailyBreadStockSnapshot.objects.create(
                node=self.node, bread_price=self.bp500, date=J, team='A', qty_at_close=10)
        with _now(13, 0, d=J1):
            self._assign('B')
            c = self.g.post(OPENING, {'lines': [{'bread_price': self.bp500.pk, 'qty': 10}]}, format='json')
            self.assertEqual(c.status_code, 200, c.data)
            self._assign('A')  # correction de la désignation
            rep = self.g.get(CLOSURE, {'date': str(J1)})
        row = self._rows(rep)[self.bp500.pk]
        self.assertEqual(sum(row['reste_du_hier'].values()), -10, row['reste_du_hier'])

    def test_bug192_session_for_non_designated_team_is_refused_in_rotation(self):
        """BUG-192 : en rotation, une fournée déclarée pour l'équipe non désignée est acceptée (201)."""
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            r = self.g.post(SESSIONS, {
                'team': 'B', 'flour_sacks_used': '1.00',
                'lines': [{'bread_price': self.bp500.pk, 'quantity': 5}],
            }, format='json')
        self.assertEqual(r.status_code, 400, r.data)


class ReportAttributionTests(_Base):
    """Rapport de clôture en rotation : mouvements entre minuit et la relève."""

    def _transfer_confirmed_at_0300(self):
        other = make_node(code='K2')
        g2 = make_user('GERANT', node=other)
        a2 = APIClient()
        a2.force_authenticate(g2)
        with _now(3, 0, d=J1):  # 03:00 locale : journée de travail J
            c = self.g.post('/api/production/transfers/', {
                'from_node': other.pk,
                'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 15}],
            }, format='json')
            self.assertEqual(c.status_code, 201, c.data)
            tid = c.data['id']
            r = a2.post(f'/api/production/transfers/{tid}/respond_to_request/', {
                'approved': True, 'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 15}],
            }, format='json')
            self.assertEqual(r.status_code, 200, r.data)
            r = self.g.post(f'/api/production/transfers/{tid}/confirm_reception/', {
                'lines': [{'bread_price': self.bp300.pk, 'quantity_received': 15}],
            }, format='json')
            self.assertEqual(r.status_code, 200, r.data)

    def test_bug193_transfer_confirmed_before_handover_belongs_to_the_work_day(self):
        """BUG-193 / BUG-247 : appro reçu à 03:00 compté sur la date CALENDAIRE J+1 (décision 2026-11-12)."""
        self._rotation()
        self._transfer_confirmed_at_0300()
        with _now(14, 0, d=J1):
            rj = self._rows(self.g.get(CLOSURE, {'date': str(J)}))[self.bp300.pk]
            rj1 = self._rows(self.g.get(CLOSURE, {'date': str(J1)}))[self.bp300.pk]
        self.assertEqual(rj['appro_recu']['quantity'], 0)
        self.assertEqual(rj1['appro_recu']['quantity'], 15)

    def test_without_rotation_transfer_follows_calendar_date(self):
        self._transfer_confirmed_at_0300()
        with _now(14, 0, d=J1):
            rj1 = self._rows(self.g.get(CLOSURE, {'date': str(J1)}))[self.bp300.pk]
        self.assertEqual(rj1['appro_recu']['quantity'], 15)


class StaleRestCharacterizationTests(_Base):
    """Scénario (9) : reste forcé = stock physique COURANT (réserve de dev-backend)."""

    def test_forced_rest_includes_later_day_movements(self):
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            self._produce([(self.bp500, 10)])
        with _now(12, 5, d=J1):
            # BUG-196 : l'API refuse désormais la désignation tant que la veille est ouverte ;
            # on simule l'état hérité (désignation déjà posée) pour garder la caractérisation.
            DailyTeamAssignment.objects.create(node=self.node, work_date=J1, team='B')
            self._invoice(self.bp500, 4)
        with _now(12, 31, d=J1):
            self.assertTrue(self.g.get(SHIFT).data['auto_closed'])
        snap = DailyBreadStockSnapshot.objects.get(node=self.node, date=J, bread_price=self.bp500)
        # Caractérisation : le reste de A (6) est amputé de la vente de B -> comptée deux fois
        self.assertEqual(snap.qty_at_close, 6)

    def test_designation_not_blocked_while_previous_day_open(self):
        """BUG-196 (décision coordinateur) : désignation REFUSÉE (400 PREVIOUS_WORKDAY_OPEN) tant que la journée précédente est ouverte."""
        self._rotation()
        with _now(13, 0):
            self._assign('A')
            self._produce([(self.bp500, 10)])
        with _now(12, 5, d=J1):
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'PREVIOUS_WORKDAY_OPEN')
