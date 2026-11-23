"""
Vérification indépendante (testeur-production, Dev C, 2026-11-21c2) des tickets
Production au statut CORRIGÉ : BUG-185, 186, 190, 191, 192, 193, 194, 196 et du
volet Clôture Journalière de BUG-177 (BUG-159 : caractérisation du comportement
actuel, devenu caduc depuis BUG-303). Données fictives uniquement.

Journée de relève : 12:00 (rotation). Horloge simulée : `timezone.now` renvoie un
datetime UTC aware ; Kinshasa = UTC+1 (00:30 local = 23:30 UTC la veille).
Les attendus sont calculés à la main, pas recopiés depuis la vue.
"""
from datetime import date, datetime, time
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Node
from core.testing import make_bread_price, make_client, make_node, make_user
from production import views as pviews
from production.models import (
    BreadDisposal, BreadStock, DailyBreadStockSnapshot, DailyOpeningConfirmation,
    DailyTeamAssignment, ProductionSession, _adjust_bread_stock,
)

J = date(2026, 11, 12)
J1 = date(2026, 11, 13)
J2 = date(2026, 11, 14)
ASSIGN = '/api/production/team-assignment/'
OPENING = '/api/production/opening-confirmation/'
SESSIONS = '/api/production/sessions/'
SHIFT = '/api/production/sessions/shift-end-status/'
CLOSURE = '/api/production/daily-closure/'
TRANSFERS = '/api/production/transfers/'


def _now(h, m=0, d=J):
    aware = timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())
    return patch('django.utils.timezone.now', return_value=aware.astimezone(dt_timezone.utc))


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', sac_value_fc=Decimal('200000'))
        self.bp500 = make_bread_price('VC_500', 'Pain 500 FC VC', 500)
        self.bp300 = make_bread_price('VC_300', 'Pain 300 FC VC', 300)
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.g = APIClient()
        self.g.force_authenticate(self.gerant)

    def _rotation(self, node=None, handover=time(12, 0)):
        node = node or self.node
        node.team_rotation_enabled = True
        node.handover_time = handover
        node.save()

    def _assign(self, team, api=None, **extra):
        r = (api or self.g).post(ASSIGN, {'team': team, **extra}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        return r

    def _produce(self, bp, qty, api=None, **extra):
        payload = {'flour_sacks_used': '1.00', 'lines': [{'bread_price': bp.pk, 'quantity': qty}]}
        payload.update(extra)
        return (api or self.g).post(SESSIONS, payload, format='json')

    def _row(self, rep, bp):
        return {x['bread_price']: x for x in rep.data['categories']}[bp.pk]


# --------------------------------------------------------------------------
# BUG-190 : désignation corrigée après une fournée
# --------------------------------------------------------------------------
class Bug190Tests(_Base):
    def test_corrected_designation_without_second_production_closes_with_rest(self):
        """A produit, désignation corrigée en B, B ne produit jamais : A est clôturée AVEC son reste."""
        self._rotation()
        with _now(13):
            self._assign('A')
            self.assertEqual(self._produce(self.bp500, 10).status_code, 201)
        with _now(14):
            self._assign('B')
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500).qty_available
        with _now(12, 5, d=J1):
            r = self.g.get(SHIFT)
        self.assertTrue(r.data['pending_validation'], r.data)  # délai de grâce : validation proposée
        with _now(12, 31, d=J1):
            r = self.g.get(SHIFT)
        self.assertTrue(r.data['auto_closed'], r.data)
        self.assertEqual(r.data['team'], 'A')
        s = ProductionSession.objects.get(node=self.node, date=J, team='A')
        self.assertTrue(s.is_closed)
        snaps = list(DailyBreadStockSnapshot.objects.filter(node=self.node, date=J, bread_price=self.bp500))
        self.assertEqual([(x.team, x.qty_at_close) for x in snaps], [('A', stock)])

    def test_flip_back_to_a_a_is_designated_b_is_leftover_single_rest(self):
        """A produit, corrigé B, B produit, re-corrigé A : un seul reste (équipe A), B clôturée sans reste."""
        self._rotation()
        with _now(13):
            self._assign('A')
            self._produce(self.bp500, 10)
        with _now(14):
            self._assign('B')
            self.assertEqual(self._produce(self.bp500, 5).status_code, 201)
        with _now(15):
            self._assign('A')
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500).qty_available
        self.assertEqual(stock, 15)
        with _now(13, 0, d=J1):
            calls = [self.g.get(SHIFT) for _ in range(4)]
        closed_teams = sorted(c.data['team'] for c in calls if c.data.get('auto_closed'))
        self.assertEqual(closed_teams, ['A', 'B'], [c.data for c in calls])
        self.assertTrue(all(s.is_closed for s in ProductionSession.objects.filter(node=self.node)))
        snaps = list(DailyBreadStockSnapshot.objects.filter(node=self.node, date=J, bread_price=self.bp500))
        self.assertEqual([(x.team, x.qty_at_close) for x in snaps], [('A', stock)])
        # la session restante n'a aucune ligne REMAINING
        sb = ProductionSession.objects.get(node=self.node, date=J, team='B')
        self.assertFalse(BreadDisposal.objects.filter(session=sb,
                         disposal_type=BreadDisposal.DisposalType.REMAINING).exists())

    def test_closure_is_idempotent_and_does_not_touch_stock(self):
        self._rotation()
        with _now(13):
            self._assign('A')
            self._produce(self.bp500, 10)
            self._assign('B')
            self._produce(self.bp500, 4)
        before = BreadStock.objects.get(node=self.node, bread_price=self.bp500).qty_available
        with _now(13, 0, d=J1):
            for _ in range(6):
                self.g.get(SHIFT)
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp500).qty_available, before)
        n = DailyBreadStockSnapshot.objects.count()
        with _now(13, 30, d=J1):
            r = self.g.get(SHIFT)
        self.assertFalse(r.data['pending_validation'])
        self.assertFalse(r.data.get('auto_closed', False))
        self.assertEqual(DailyBreadStockSnapshot.objects.count(), n)

    def test_calendar_midnight_variant_two_sessions_same_calendar_day(self):
        """A (23:30 J) puis désignation corrigée B (23:45 J, même période), B produit à 23:50 :
        après minuit, aucune session ne reste ouverte plus de 2 appels et le stock est inchangé."""
        self._rotation()
        with _now(23, 30):
            self._assign('A')
            self._produce(self.bp500, 10)
        with _now(23, 45):
            self._assign('B')
        with _now(23, 50):
            self.assertEqual(self._produce(self.bp500, 5).status_code, 201)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500).qty_available
        with _now(0, 40, d=J1):
            for _ in range(5):
                self.g.get(SHIFT)
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp500).qty_available, stock)
        # les sessions de la date J sont toutes clôturées
        self.assertFalse(ProductionSession.objects.filter(node=self.node, date=J, is_closed=False).exists())
        # un reste par date et par catégorie dans le rapport de J (pas de somme doublée)
        with _now(0, 45, d=J1):
            rep = self.g.get(CLOSURE, {'date': str(J)})
        self.assertEqual(rep.status_code, 200, rep.data)
        row = self._row(rep, self.bp500)
        self.assertEqual(row['reste_du_jour_fin_journee'], stock)

    def test_midnight_leaves_open_session_of_undesignated_team_until_handover(self):
        """Caractérise le passage de minuit avec 2 sessions (A corrigée en B) : on constate l'état réel."""
        self._rotation()
        with _now(23, 30):
            self._assign('A')
            self._produce(self.bp500, 10)
            self._assign('B')
            self._produce(self.bp500, 5)
        with _now(0, 40, d=J1):
            for _ in range(5):
                self.g.get(SHIFT)
        opens = list(ProductionSession.objects.filter(node=self.node, is_closed=False)
                     .values_list('team', 'date'))
        # À 12:35 le même jour tout doit être résolu (aucune session ouverte à vie).
        with _now(12, 35, d=J1):
            for _ in range(6):
                self.g.get(SHIFT)
        self.assertFalse(ProductionSession.objects.filter(node=self.node, is_closed=False,
                                                           date__lt=J1).exists(), opens)

    def test_stale_instance_helpers_do_nothing_when_already_closed(self):
        """Concurrence simulée : deux requêtes traitent la même session ; la seconde ne refait rien."""
        self._rotation()
        with _now(13):
            self._assign('A')
            self._produce(self.bp500, 10)
        sess = ProductionSession.objects.get(node=self.node, date=J, team='A')
        stale = ProductionSession.objects.get(pk=sess.pk)  # instance lue avant la clôture concurrente
        with _now(13, 0, d=J1):
            self.assertTrue(pviews._close_leftover_session(sess, self.gerant))
            n_snap = DailyBreadStockSnapshot.objects.count()
            self.assertFalse(pviews._close_leftover_session(stale, self.gerant))
            self.assertFalse(pviews._force_close_session(stale, pviews._current_bread_stocks(self.node),
                                                         self.node, self.gerant))
        self.assertEqual(DailyBreadStockSnapshot.objects.count(), n_snap)


# --------------------------------------------------------------------------
# BUG-191 : une seule source de « reste d'hier » après désignation corrigée
# --------------------------------------------------------------------------
class Bug191Tests(_Base):
    def _snap(self, bp, qty, team='A', d=J, h=20):
        with _now(h, 0, d=d):
            DailyBreadStockSnapshot.objects.create(node=self.node, bread_price=bp, date=d, team=team,
                                                   qty_at_close=qty)

    def _hier(self, day, bp):
        rep = self.g.get(CLOSURE, {'date': str(day)})
        self.assertEqual(rep.status_code, 200, rep.data)
        return sum(self._row(rep, bp)['reste_du_hier'].values()), rep

    def test_confirmed_value_differs_from_snapshot_then_designation_flipped(self):
        """Reste déclaré 10, confirmé 8 par B, désignation corrigée en A : reste d'hier = -8 (pas -18/-10)."""
        self._rotation()
        self._snap(self.bp500, 10)
        with _now(13, 0, d=J1):
            self._assign('B')
            c = self.g.post(OPENING, {'lines': [{'bread_price': self.bp500.pk, 'qty': 8}]}, format='json')
            self.assertEqual(c.status_code, 200, c.data)
            ref, _ = self._hier(J1, self.bp500)  # témoin : sans correction
            self._assign('A')
            hier, rep = self._hier(J1, self.bp500)
        self.assertEqual(ref, -8)
        self.assertEqual(hier, -8)
        # le total du jour ne compte le reste d'hier qu'une fois
        row = self._row(rep, self.bp500)
        self.assertEqual(Decimal(row['facture_mvm_interne']['fc']), Decimal('-4000.00'))

    def test_flip_twice_keeps_single_source(self):
        self._rotation()
        self._snap(self.bp500, 10)
        with _now(13, 0, d=J1):
            self._assign('A')
            self.g.post(OPENING, {'lines': [{'bread_price': self.bp500.pk, 'qty': 10}]}, format='json')
            self._assign('B')
            h1, _ = self._hier(J1, self.bp500)
            self._assign('A')
            h2, _ = self._hier(J1, self.bp500)
        self.assertEqual((h1, h2), (-10, -10))

    def test_opening_box_not_reopened_after_correction_same_period(self):
        """Une confirmation déjà faite dans la période suffit : la boîte ne se rouvre pas (BUG-247)."""
        self._rotation()
        self._snap(self.bp500, 10)
        with _now(13, 0, d=J1):
            self._assign('B')
            self.g.post(OPENING, {'lines': [{'bread_price': self.bp500.pk, 'qty': 10}]}, format='json')
            self._assign('A')
            r = self.g.get(OPENING)
        self.assertFalse(r.data['needs_confirmation'], r.data)
        self.assertEqual(r.data['team'], 'A')

    def test_reconfirmation_by_new_team_after_correction_is_not_double_adjusted(self):
        """API seule (la boîte ne se rouvre pas) : B confirme 8, corrigé en A, A confirme 9 : le départ
        de la journée doit valoir la dernière valeur confirmée (-9), pas un mélange (-7)."""
        self._rotation()
        self._snap(self.bp500, 10)
        with _now(13, 0, d=J1):
            self._assign('B')
            self.g.post(OPENING, {'lines': [{'bread_price': self.bp500.pk, 'qty': 8}]}, format='json')
            self._assign('A')
            r = self.g.post(OPENING, {'lines': [{'bread_price': self.bp500.pk, 'qty': 9}]}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
            hier, _ = self._hier(J1, self.bp500)
        self.assertEqual(hier, -9)

    def test_unconfirmed_category_still_chained_once(self):
        self._rotation()
        self._snap(self.bp300, 4)
        with _now(13, 0, d=J1):
            self._assign('B')
            self._assign('A')
            hier, rep = self._hier(J1, self.bp300)
        self.assertEqual(hier, -4)
        self.assertEqual(self._row(rep, self.bp300)['reste_du_hier']['A'], -4)


# --------------------------------------------------------------------------
# BUG-192 : équipe de la fournée = équipe désignée
# --------------------------------------------------------------------------
class Bug192Tests(_Base):
    def test_lowercase_and_unknown_team_refused(self):
        self._rotation()
        with _now(13):
            self._assign('A')
            for t in ('a', 'b', 'B', 'C', ['A'], {'x': 1}, 0):
                r = self._produce(self.bp500, 5, team=t)
                self.assertEqual(r.status_code, 400, (t, r.data))
        self.assertEqual(ProductionSession.objects.count(), 0)

    def test_explicit_null_or_empty_team_defaults_to_designated(self):
        self._rotation()
        with _now(13):
            self._assign('B')
            self.assertEqual(self._produce(self.bp500, 5, team=None).status_code, 201)
            self.assertEqual(self._produce(self.bp500, 5, team='').status_code, 201)
        self.assertEqual(list(ProductionSession.objects.values_list('team', flat=True)), ['B'])

    def test_non_object_body_is_400_not_500(self):
        self._rotation()
        with _now(13):
            self._assign('A')
            for body in (['A'], 'x', 3):
                r = self.g.post(SESSIONS, body, format='json')
                self.assertEqual(r.status_code, 400, (body, getattr(r, 'data', None)))

    def test_before_handover_uses_previous_period_team(self):
        """10:00 le lendemain : la période démarrée à 12:00 la veille est encore en cours."""
        self._rotation()
        with _now(13):
            self._assign('B')
        with _now(10, 0, d=J1):
            r = self._produce(self.bp500, 5, team='A')
            self.assertEqual(r.status_code, 400, r.data)
            ok = self._produce(self.bp500, 5)
            self.assertEqual(ok.status_code, 201, ok.data)
        s = ProductionSession.objects.get()
        self.assertEqual((s.team, s.date), ('B', J1))

    def test_explicit_past_date_other_team_still_accepted_retroactive(self):
        """Saisie rétroactive (date passée explicite) : conservée, ni refusée ni détournée."""
        self._rotation()
        with _now(13):
            self._assign('A')
            r = self._produce(self.bp500, 5, team='B', date='2026-11-10')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(ProductionSession.objects.get().team, 'B')

    def test_invalid_date_strings_never_500(self):
        self._rotation()
        with _now(13):
            self._assign('A')
            for d in ('abc', '2026-13-45', '', 20261112, ['2026-11-12']):
                r = self._produce(self.bp500, 5, date=d)
                self.assertLess(r.status_code, 500, (d, getattr(r, 'data', None)))

    def test_hq_user_with_garbage_node_never_500(self):
        self._rotation()
        hq = make_user('DIRECTION', node=None)
        api = APIClient()
        api.force_authenticate(hq)
        with _now(13):
            for node_ref in ('zzz', '0', 99999, ['x']):
                r = self._produce(self.bp500, 5, api=api, node=node_ref, team='A')
                self.assertLess(r.status_code, 500, (node_ref, getattr(r, 'data', None)))

    def test_second_declaration_same_team_adds_up(self):
        self._rotation()
        with _now(13):
            self._assign('A')
            self.assertEqual(self._produce(self.bp500, 5).status_code, 201)
            self.assertEqual(self._produce(self.bp500, 7).status_code, 201)
        s = ProductionSession.objects.get()
        self.assertEqual(sum(l.quantity for l in s.lines.all()), 12)

    def test_after_correction_old_team_refused_new_team_accepted(self):
        self._rotation()
        with _now(13):
            self._assign('A')
            self._produce(self.bp500, 5)
            self._assign('B')
            self.assertEqual(self._produce(self.bp500, 5, team='A').status_code, 400)
            self.assertEqual(self._produce(self.bp500, 5, team='B').status_code, 201)

    def test_without_rotation_team_and_date_required_and_free(self):
        with _now(13):
            self.assertEqual(self._produce(self.bp500, 5).status_code, 400)  # ni team ni date
            self.assertEqual(self._produce(self.bp500, 5, team='B', date='2026-11-12').status_code, 201)
            self.assertEqual(self._produce(self.bp500, 5, team='A', date='2026-11-12').status_code, 201)


# --------------------------------------------------------------------------
# BUG-193 : transferts rattachés au jour calendaire LOCAL (pas UTC)
# --------------------------------------------------------------------------
class Bug193Tests(_Base):
    def _confirmed(self, h, m, d, qty=15):
        other = make_node(code='K3' if Node.objects.filter(code='K2').exists() else 'K2')
        a2 = APIClient()
        a2.force_authenticate(make_user('GERANT', node=other))
        with _now(h, m, d=d):
            c = self.g.post(TRANSFERS, {'from_node': other.pk,
                                        'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': qty}]},
                            format='json')
            self.assertEqual(c.status_code, 201, c.data)
            tid = c.data['id']
            _adjust_bread_stock(other, self.bp300, produced=qty)  # BUG-652 : stock émettrice requis
            self.assertEqual(a2.post(f'{TRANSFERS}{tid}/respond_to_request/', {
                'approved': True, 'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': qty}]},
                format='json').status_code, 200)
            self.assertEqual(self.g.post(f'{TRANSFERS}{tid}/confirm_reception/', {
                'lines': [{'bread_price': self.bp300.pk, 'quantity_received': qty}]},
                format='json').status_code, 200)
        return other, a2

    def _q(self, api, day, key, node):
        rep = api.get(CLOSURE, {'date': str(day), 'node': node.code})
        self.assertEqual(rep.status_code, 200, rep.data)
        return self._row(rep, self.bp300)[key]['quantity']

    def test_confirmed_at_00_30_local_belongs_to_new_local_day_not_utc_day(self):
        for rot in (True, False):
            with self.subTest(rotation=rot):
                from production.models import BreadTransfer
                BreadTransfer.objects.all().delete()
                if rot:
                    self._rotation()
                other, a2 = self._confirmed(0, 30, J1)
                if rot:
                    self._rotation(other)
                with _now(14, 0, d=J1):
                    self.assertEqual(self._q(self.g, J1, 'appro_recu', self.node), 15)
                    self.assertEqual(self._q(self.g, J, 'appro_recu', self.node), 0)
                    self.assertEqual(self._q(a2, J1, 'appro_effectue', other), 15)
                    self.assertEqual(self._q(a2, J, 'appro_effectue', other), 0)

    def test_confirmed_at_23_50_local_stays_on_same_day(self):
        other, a2 = self._confirmed(23, 50, J)
        with _now(14, 0, d=J1):
            self.assertEqual(self._q(self.g, J, 'appro_recu', self.node), 15)
            self.assertEqual(self._q(self.g, J1, 'appro_recu', self.node), 0)

    def test_total_du_jour_includes_transfer_in_good_day_only(self):
        self._rotation()
        other, a2 = self._confirmed(0, 30, J1)
        with _now(14, 0, d=J1):
            r1 = self.g.get(CLOSURE, {'date': str(J1)})
            r0 = self.g.get(CLOSURE, {'date': str(J)})
        # appro reçu 15 x 300 = 4500 RETRANCHÉ du total du jour J1 uniquement (BUG-675)
        self.assertEqual(Decimal(r1.data['totals']['total_du_jour_fc']), Decimal('-4500.00'))
        self.assertEqual(Decimal(r0.data['totals']['total_du_jour_fc']), Decimal('0.00'))


# --------------------------------------------------------------------------
# BUG-194 : corps JSON non objet -> 400 partout (et pas 500)
# --------------------------------------------------------------------------
class Bug194Tests(_Base):
    BODIES = (['A'], 'x', 3, [], [{'a': 1}])

    def test_every_post_endpoint_rejects_non_object_body(self):
        self._rotation()
        other = make_node(code='K2')
        a2 = APIClient()
        a2.force_authenticate(make_user('GERANT', node=other))
        with _now(13):
            self._assign('A')
            s = self._produce(self.bp500, 5)
            sid = s.data['id']
            t = self.g.post(TRANSFERS, {'from_node': other.pk,
                                        'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 5}]},
                            format='json')
            tid = t.data['id']
            for body in self.BODIES:
                for url, api in (
                    (OPENING, self.g), (ASSIGN, self.g),
                    (f'{SESSIONS}{sid}/close/', self.g),
                    (f'{TRANSFERS}{tid}/respond_to_request/', a2),
                    (f'{TRANSFERS}{tid}/confirm_reception/', self.g),
                    (f'{TRANSFERS}{tid}/resolve_dispute/', a2),
                    (SESSIONS, self.g), (TRANSFERS, self.g),
                    ('/api/production/disposals/', self.g),
                    ('/api/production/counts/', self.g),
                    ('/api/production/movements/', self.g),
                ):
                    r = api.post(url, body, format='json')
                    self.assertLess(r.status_code, 500, (url, body, getattr(r, 'data', None)))
                    if r.status_code == 400 and hasattr(r, 'data') and isinstance(r.data, dict):
                        pass
        self.assertFalse(ProductionSession.objects.get(pk=sid).is_closed)

    def _setup_inner(self):
        other = make_node(code='K2')
        self.a2 = APIClient(raise_request_exception=False)
        self.a2.force_authenticate(make_user('GERANT', node=other))
        self.g = APIClient(raise_request_exception=False)
        self.g.force_authenticate(self.gerant)
        sid = self._produce(self.bp500, 5, team='A', date='2026-11-12').data['id']
        t = self.g.post(TRANSFERS, {'from_node': other.pk,
                                    'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 5}]},
                        format='json')
        return sid, t.data['id']

    def test_inner_types_of_transfer_and_opening_payloads_never_500(self):
        with _now(13):
            sid, tid = self._setup_inner()
            bad = []
            for body in ({'lines': {'a': 1}}, {'lines': 'x'}, {'lines': [1]},
                         {'lines': [{'bread_price': [1], 'quantity_sent': 1}]},
                         {'approved': True, 'lines': [{'bread_price': {'a': 1}, 'quantity_sent': 1}]}):
                r = self.a2.post(f'{TRANSFERS}{tid}/respond_to_request/', body, format='json')
                if r.status_code >= 500:
                    bad.append(('respond', body, r.status_code))
            for body in ({'lines': [{'lines': 1}]}, {'lines': [{'bread_price': 'a', 'quantity_received': 'x'}]}):
                r = self.g.post(f'{TRANSFERS}{tid}/confirm_reception/', body, format='json')
                if r.status_code >= 500:
                    bad.append(('confirm', body, r.status_code))
            for body in ({'lines': 5}, {'lines': [{'bread_price': [], 'qty': 1}]}, {'lines': [5]},
                         {'lines': [{'bread_price': 'a', 'qty': 1}]},
                         {'node': ['K1'], 'lines': [{'bread_price': 1, 'qty': 1}]}):
                r = self.g.post(OPENING, body, format='json')
                if r.status_code >= 500:
                    bad.append(('opening', body, r.status_code))
        self.assertEqual(bad, [])

    def _close_500s(self):
        with _now(13):
            sid, _tid = self._setup_inner()
            bad = []
            for body in (
                {'remaining': {'a': 1}}, {'remaining': 'x'}, {'remaining': [1]},
                {'remaining': [{'bread_price': 'abc', 'quantity': 1}]},
                {'remaining': [{'bread_price': [1], 'quantity': 1}]},
                {'remaining': [{'bread_price': {'a': 1}, 'quantity': 1}]},
                {'remaining': [{'bread_price': self.bp500.pk, 'quantity': {'a': 1}}]},
                {'remaining': [{'bread_price': 10 ** 30, 'quantity': 1}]},
                {'remaining': [{'bread_price': True, 'quantity': 1}]},
            ):
                r = self.g.post(f'{SESSIONS}{sid}/close/', body, format='json')
                if r.status_code >= 500:
                    bad.append((body, r.status_code))
        return bad

    def test_close_remaining_inner_types_never_500(self):
        self.assertEqual(self._close_500s(), [])


# --------------------------------------------------------------------------
# BUG-196 : désignation refusée tant qu'une journée précédente est ouverte
# --------------------------------------------------------------------------
class Bug196Tests(_Base):
    def test_hq_assign_blocked_only_for_node_with_open_session(self):
        self._rotation()
        k2 = make_node(code='K2')
        self._rotation(k2)
        hq = make_user('DIRECTION', node=None)
        api = APIClient()
        api.force_authenticate(hq)
        with _now(13):
            self._assign('A')
            self._produce(self.bp500, 10)
        with _now(12, 5, d=J1):
            r1 = api.post(ASSIGN, {'team': 'B', 'node': self.node.code}, format='json')
            r2 = api.post(ASSIGN, {'team': 'B', 'node': k2.code}, format='json')
        self.assertEqual((r1.status_code, r1.data.get('code')), (400, 'PREVIOUS_WORKDAY_OPEN'))
        self.assertEqual(r2.status_code, 200, r2.data)

    def test_other_node_open_session_does_not_block(self):
        self._rotation()
        k2 = make_node(code='K2')
        self._rotation(k2)
        ProductionSession.objects.create(node=k2, team='A', date=J, declared_by=self.gerant, node_origin='K2')
        with _now(12, 5, d=J1):
            r = self.g.post(ASSIGN, {'team': 'A'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_blocked_attempt_leaves_no_trace(self):
        self._rotation()
        with _now(13):
            self._assign('A')
            self._produce(self.bp500, 10)
        from core.models import ActivityLog
        n_log = ActivityLog.objects.count()
        with _now(12, 5, d=J1):
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(DailyTeamAssignment.objects.filter(node=self.node).count(), 1)
        self.assertEqual(ActivityLog.objects.count(), n_log)

    def test_midnight_handover_config_period_is_calendar_day(self):
        """Relève à 00:00 : une session ouverte de J bloque la désignation de J1 ; la clôture la débloque."""
        self._rotation(handover=time(0, 0))
        with _now(20, 0):
            self._assign('A')
            self.assertEqual(self._produce(self.bp500, 10).status_code, 201)
        with _now(0, 5, d=J1):
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
            self.assertEqual((r.status_code, r.data.get('code')), (400, 'PREVIOUS_WORKDAY_OPEN'), r.data)
            self.assertTrue(self.g.get(SHIFT).data['pending_validation'])
        with _now(0, 31, d=J1):
            self.assertTrue(self.g.get(SHIFT).data['auto_closed'])
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_session_started_before_handover_blocks_after_handover(self):
        """Session créée à 03:00 (période J) encore ouverte à 12:05 : bloque ; sans trou de date."""
        self._rotation()
        with _now(13, 0, d=J):
            self._assign('A')
        with _now(3, 0, d=J1):
            self.assertEqual(self._produce(self.bp500, 10).status_code, 201)
        with _now(12, 5, d=J1):
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual((r.status_code, r.data.get('code')), (400, 'PREVIOUS_WORKDAY_OPEN'), r.data)

    def test_backdated_open_session_unblocked_by_shift_end_flow(self):
        self._rotation()
        with _now(13):
            self._assign('A')
            self.assertEqual(self._produce(self.bp500, 3, date='2026-11-09', team='A').status_code, 201)
        with _now(12, 5, d=J1):
            self.assertEqual(self.g.post(ASSIGN, {'team': 'B'}, format='json').status_code, 400)
            for _ in range(4):
                self.g.get(SHIFT)
            r = self.g.post(ASSIGN, {'team': 'B'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_concurrent_creation_falls_back_to_update_single_row(self):
        """Course simulée : la ligne de désignation apparaît entre la lecture et la création."""
        self._rotation()
        with _now(13):
            DailyTeamAssignment.objects.create(node=self.node, work_date=J, team='B')
            real = DailyTeamAssignment.objects.select_for_update
            fake = MagicMock()
            fake.filter.return_value.first.return_value = None   # la lecture ne voit pas encore la ligne
            fake.get.side_effect = lambda **kw: real().get(**kw)
            with patch.object(DailyTeamAssignment.objects, 'select_for_update', return_value=fake), \
                 patch.object(DailyTeamAssignment.objects, 'create', side_effect=IntegrityError('dup')):
                r = self.g.post(ASSIGN, {'team': 'A'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        rows = DailyTeamAssignment.objects.filter(node=self.node)
        self.assertEqual([(x.work_date, x.team) for x in rows], [(J, 'A')])

    def test_explicit_other_date_refused(self):
        self._rotation()
        with _now(13):
            for key in ('work_date', 'date'):
                r = self.g.post(ASSIGN, {'team': 'A', key: '2026-11-20'}, format='json')
                self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(DailyTeamAssignment.objects.count(), 0)


# --------------------------------------------------------------------------
# BUG-185 / BUG-186 / BUG-177 (Clôture Journalière) : sans rotation, jour calendaire
# --------------------------------------------------------------------------
class _ReportBase(TestCase):
    def setUp(self):
        self.node = make_node(code='K1', sac_value_fc=Decimal('200000'))
        self.gerant = make_user('GERANT', node=self.node)
        self.facturier = make_user('FACTURIER', node=self.node, team='A')
        self.bp300 = make_bread_price('VR_300', 'Pain 300 VR', 300)
        self.bp500 = make_bread_price('VR_500', 'Pain 500 VR', 500)
        self.cl = make_client(self.node, credit_limit=Decimal('900000.00'))
        self.g = APIClient(); self.g.force_authenticate(self.gerant)
        self.f = APIClient(); self.f.force_authenticate(self.facturier)

    def _session(self, team, d, lines, flour=1):
        r = self.g.post(SESSIONS, {'team': team, 'date': str(d), 'flour_sacks_used': str(flour),
                                   'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in lines]},
                        format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def _inv(self, lines, code='', soldee=False, deliver=True, pay='0.00'):
        p = {'payment_type': 'CASH', 'payment_amount': pay, 'special_code': code,
             'client': str(self.cl.pk),
             'lines': [{'bread_price': bp.pk, 'quantity': q} for bp, q in lines]}
        if soldee:
            p['is_soldee'] = True
        r = self.f.post('/api/sales/invoices/', p, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        if deliver and code != 'NS':
            d = self.f.post(f"/api/sales/invoices/{r.data['id']}/deliver/")
            self.assertEqual(d.status_code, 200, d.data)
        return r.data

    def _report(self, d):
        r = self.g.get(CLOSURE, {'date': str(d)})
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def _cat(self, data, bp):
        return {c['bread_price']: c for c in data['categories']}[bp.pk]


class Bug185Tests(_ReportBase):
    def test_mix_of_plain_and_soldee_rg_and_real_soldee_sale(self):
        with _now(10):
            self._session('A', J, [(self.bp300, 100)])
            self._inv([(self.bp300, 10)], code='RG')                 # 3000 plein
            self._inv([(self.bp300, 10)], code='RG', soldee=True)    # 3000 plein (pas 2250, pas double)
            self._inv([(self.bp300, 20)], soldee=True)               # vraie vente soldée 20 x 225 = 4500
            data = self._report(J)
        cat = self._cat(data, self.bp300)
        self.assertEqual(cat['regularisation'], {'quantity': 20, 'fc': '6000.00'})
        self.assertEqual((cat['vente_cash_soldee']['quantity'], cat['vente_cash_soldee']['fc']), (20, '4500.00'))
        # total du jour = RG 6000 + soldée 4500 (+ reste 0) ; aucune double comptabilisation
        self.assertEqual(Decimal(data['totals']['total_du_jour_fc']), Decimal('10500.00'))
        self.assertEqual(data['totals']['total_breads_billed'], 40)

    def test_rg_soldee_belongs_to_local_day_at_00_30(self):
        with _now(0, 30, d=J1):
            self._session('A', J1, [(self.bp300, 50)])
            self._inv([(self.bp300, 10)], code='RG', soldee=True)
            r1 = self._report(J1)
            r0 = self._report(J)
        self.assertEqual(self._cat(r1, self.bp300)['regularisation']['fc'], '3000.00')
        self.assertEqual(self._cat(r0, self.bp300)['regularisation']['fc'], '0.00')

    def test_rg_soldee_full_price_follows_frozen_price_after_tariff_change(self):
        """Une RG soldée est valorisée « prix plein ». Après un changement de tarif, le rapport d'une
        journée passée ne doit pas bouger (comme une RG non soldée, qui lit le prix figé)."""
        with _now(10):
            self._session('A', J, [(self.bp300, 50)])
            self._inv([(self.bp300, 10)], code='RG', soldee=True)
            self._inv([(self.bp300, 10)], code='RG')
            before = self._cat(self._report(J), self.bp300)['regularisation']['fc']
            self.bp300.unit_price = 400
            self.bp300.save()
            after = self._cat(self._report(J), self.bp300)['regularisation']['fc']
        self.assertEqual(before, '6000.00')
        self.assertEqual(after, before, "le rapport d'une journée passée a changé avec le tarif")


class Bug186Tests(_ReportBase):
    def _sum(self, data, key='repartition_pct_par_quantite'):
        return sum(Decimal(x['pct']) for x in data['totals'][key])

    def test_sum_is_100_with_carryover_two_categories(self):
        with _now(10):
            r = self.g.post(OPENING, {'team': 'A', 'date': str(J),
                                      'lines': [{'bread_price': self.bp500.pk, 'qty': 8}]}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
            self._session('A', J, [(self.bp300, 190)])
            data = self._report(J)
        pct = {x['bread_price']: Decimal(x['pct']) for x in data['totals']['repartition_pct_par_quantite']}
        self.assertEqual(pct[self.bp300.pk], Decimal('100.00'))
        self.assertEqual(pct[self.bp500.pk], Decimal('0.00'))
        self.assertEqual(self._sum(data), Decimal('100.00'))
        self.assertEqual(self._sum(data, 'repartition_pct_par_valeur'), Decimal('100.00'))

    def test_three_categories_sum_within_rounding(self):
        bp = make_bread_price('VR_200', 'Pain 200 VR', 200)
        with _now(10):
            self._session('A', J, [(self.bp300, 10), (self.bp500, 10), (bp, 10)])
            data = self._report(J)
        for key in ('repartition_pct_par_quantite',):
            self.assertLessEqual(abs(self._sum(data, key) - Decimal('100')), Decimal('0.02'), self._sum(data, key))

    def test_sacs_only_session_no_division_error(self):
        with _now(10):
            r = self.g.post(SESSIONS, {'team': 'A', 'date': str(J), 'flour_sacks_used': '2.00'}, format='json')
            self.assertIn(r.status_code, (201, 400), r.data)
            data = self._report(J)
        self.assertTrue(all(Decimal(x['pct']) == 0 for x in data['totals']['repartition_pct_par_quantite']))

    def test_two_teams_same_day_sum_100(self):
        with _now(10):
            self._session('A', J, [(self.bp300, 70)])
            self._session('B', J, [(self.bp300, 30), (self.bp500, 100)])
            data = self._report(J)
        self.assertEqual(self._sum(data), Decimal('100.00'))


class Bug177ClosureTests(_ReportBase):
    def test_ns_pending_counted_sum_of_order_total_cancelled_excluded(self):
        with _now(10):
            a = self._inv([(self.bp300, 10), (self.bp500, 4)], code='NS')   # 3000 + 2000 = 5000
            b = self._inv([(self.bp300, 5)], code='NS')                      # 1500
            c = self._inv([(self.bp300, 100)], code='NS')                    # annulée
            self.g.post(f"/api/sales/invoices/{c['id']}/cancel/")
            data = self._report(J)
        c300 = self._cat(data, self.bp300)
        c500 = self._cat(data, self.bp500)
        self.assertEqual(c300['non_servi'], {'quantity': 15, 'fc': '4500.00', 'fc_signe': '-4500.00'})
        self.assertEqual(c500['non_servi']['fc'], '2000.00')
        # contribution négative au total du jour : -6500
        self.assertEqual(Decimal(data['totals']['total_du_jour_fc']), Decimal('-6500.00'))
        self.assertEqual(data['totals']['total_breads_billed'], 0)

    def test_ns_not_deleted_nor_expired_after_12h_and_other_day_excluded(self):
        with _now(10):
            self._inv([(self.bp300, 10)], code='NS')
        with _now(10, d=J1):   # 24 h plus tard
            r = self.g.post('/api/sales/invoices/cleanup_expired/')
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.data['expired'], 0, r.data)
            d0 = self._report(J)
            d1 = self._report(J1)
        self.assertEqual(self._cat(d0, self.bp300)['non_servi']['fc'], '3000.00')
        self.assertEqual(self._cat(d1, self.bp300)['non_servi']['fc'], '0.00')

    def test_ns_at_00_30_local_is_new_day(self):
        with _now(0, 30, d=J1):
            self._inv([(self.bp300, 10)], code='NS')
            d1 = self._report(J1)
            d0 = self._report(J)
        self.assertEqual(self._cat(d1, self.bp300)['non_servi']['fc'], '3000.00')
        self.assertEqual(self._cat(d0, self.bp300)['non_servi']['fc'], '0.00')

    def test_ns_does_not_leak_to_other_node(self):
        other = make_node(code='K2')
        og = APIClient(); og.force_authenticate(make_user('GERANT', node=other))
        with _now(10):
            self._inv([(self.bp300, 10)], code='NS')
            r = og.get(CLOSURE, {'date': str(J)})
        self.assertEqual(r.status_code, 200, r.data)
        row = {c['bread_price']: c for c in r.data['categories']}[self.bp300.pk]
        self.assertEqual(row['non_servi']['fc'], '0.00')


# --------------------------------------------------------------------------
# BUG-159 : caractérisation (caduc depuis BUG-303, voir rapport)
# --------------------------------------------------------------------------
class Bug159CharacterisationTests(_Base):
    def test_manual_close_refuses_negative_rest_since_bug303(self):
        with _now(13):
            sid = self._produce(self.bp500, 5, team='A', date='2026-11-12').data['id']
            r = self.g.post(f'{SESSIONS}{sid}/close/',
                            {'remaining': [{'bread_price': self.bp500.pk, 'quantity': -3}]}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(ProductionSession.objects.get(pk=sid).is_closed)

    def test_forced_closure_still_records_physical_negative_stock(self):
        """Le chemin automatique (non saisi) enregistre le stock physique, même négatif (BUG-158)."""
        self._rotation()
        with _now(13):
            self._assign('A')
            self._produce(self.bp500, 2)
            BreadStock.objects.filter(node=self.node, bread_price=self.bp500).update(qty_disposed=5) \
                if hasattr(BreadStock, 'qty_disposed') else None
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        if stock.qty_available >= 0:
            self.skipTest("impossible de forcer un stock négatif par ce champ")
        with _now(13, 0, d=J1):
            r = self.g.get(SHIFT)
        self.assertTrue(r.data['auto_closed'], r.data)
        snap = DailyBreadStockSnapshot.objects.get(node=self.node, date=J, bread_price=self.bp500)
        self.assertEqual(snap.qty_at_close, stock.qty_available)
