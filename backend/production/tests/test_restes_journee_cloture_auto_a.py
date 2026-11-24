"""
BUG-1073 / BUG-1074 (remarque.md l.464, 485, 516, plan A-4). Donnees fictives.

- Restes d'hier / du jour = valeurs de JOURNEE par boulangerie et categorie, independantes
  de l'equipe (decision client 2026-11-24) : le meme chiffre alimente FACTURE MVM INTERNE
  et le produit derive.
- Le reste du jour devient le stock de depart propose le lendemain ; le modifier ne change
  pas la cloture deja faite (l.464).
- Cloture automatique de la fournee a l'heure de cloture (`services.auto_close_day`).
- Reconciliation (NV, declasses, sorties gratuites) visible dans `daily-closure`.
"""
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import ActivityLog, SystemNotification
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import (
    BreadDisposal, BreadStock, DailyBreadStockSnapshot, ProductionSession, _adjust_bread_stock,
)
from production.services import auto_close_day
from sales.models import Invoice

D = date(2026, 11, 12)
PREV = D - timedelta(days=1)
INV = '/api/sales/invoices/'
CLOSURE = '/api/production/daily-closure/'
OPENING = '/api/production/opening-confirmation/'
SHIFT = '/api/production/sessions/shift-end-status/'


def _at(d, h, m=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m), timezone.get_current_timezone())


def _now(h, m=0, d=D):
    return patch('django.utils.timezone.now', return_value=_at(d, h, m).astimezone(dt_timezone.utc))


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.gerant = make_user('GERANT', node=self.node, team='A')
        self.facturier = make_user('FACTURIER', node=self.node, team='A')
        self.client_obj = make_client(self.node)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        self.fapi = APIClient()
        self.fapi.force_authenticate(self.facturier)

    def _snap(self, d, team, qty, bp=None):
        return DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=bp or self.bp, date=d, team=team, qty_at_close=qty,
        )

    def _sale(self, qty=10, d=D, hour=10):
        """Vente livree le jour `d` (statut et horodatage poses directement)."""
        with _now(hour, 0, d):
            r = self.fapi.post(INV, {
                'client': str(self.client_obj.pk), 'payment_type': 'CASH', 'payment_amount': 500 * qty,
                'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
            }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        Invoice.objects.filter(pk=r.data['id']).update(
            status=Invoice.Status.DELIVERED, delivered_at=_at(d, hour, 5), invoice_date=d,
        )

    def _session(self, team='A', sacks='1.00', closed=False, auto=True, d=D):
        s = ProductionSession.objects.create(
            node=self.node, team=team, date=d, flour_sacks_used=Decimal(sacks),
            auto_track=auto, is_closed=closed, declared_by=self.gerant, node_origin='K1',
        )
        ProductionSession.objects.filter(pk=s.pk).update(created_at=_at(d, 6))
        s.refresh_from_db()
        return s

    def _row(self, d=D, bp=None):
        r = self.api.get(CLOSURE, {'date': str(d)})
        self.assertEqual(r.status_code, 200, r.data)
        return next(c for c in r.data['categories'] if c['bread_price'] == (bp or self.bp).pk), r.data


class RestesDeJourneeTests(_Base):
    """Mission 1 : un seul reste par journee, meme valeur pour MVM INTERNE et produit derive."""

    def test_meme_valeur_pour_mvm_interne_et_produit_derive(self):
        self._snap(PREV, 'A', 10)
        self._snap(PREV, 'B', 3)    # B cloture en dernier la veille : reste d'hier de la journee = 3
        self._session('A', closed=True)
        self._session('B', closed=True)
        self._snap(D, 'A', 12)
        self._snap(D, 'B', 8)       # B cloture en dernier aujourd'hui : reste du jour = 8
        self._sale(40)
        row, _ = self._row()
        self.assertEqual(row['reste_du_jour_jour'], 8)
        self.assertEqual(row['reste_du_hier_jour'], -3)
        # produit derive = vendus 40 + reste du jour 8 - reste d'hier 3 = 45 (une seule valeur de reste)
        self.assertEqual(row['produit']['quantity'], 45)
        # MVM INTERNE = (8 - 3) x 500 : meme valeur de journee, pas de somme par equipe (A12+B8, A10+B3)
        self.assertEqual(Decimal(row['facture_mvm_interne']['fc']), Decimal('2500.00'))
        # le detail par equipe reste expose
        self.assertEqual(row['reste_du_jour'], {'A': 12, 'B': 8})

    def test_le_dernier_saisi_de_la_journee_gagne_quelle_que_soit_l_equipe(self):
        self._session('A', closed=True)
        self._session('B', closed=True)
        self._snap(D, 'B', 8)
        self._snap(D, 'A', 12)      # A saisit en dernier cette fois
        row, _ = self._row()
        self.assertEqual(row['reste_du_jour_jour'], 12)
        self.assertEqual(Decimal(row['facture_mvm_interne']['fc']), Decimal('6000.00'))


class RestePropose_Lendemain_Tests(_Base):
    """Mission 2 : le reste du jour est le stock de depart propose le lendemain, modifiable sans toucher la cloture."""

    def _proposed(self, d):
        r = self.api.get(OPENING, {'node': 'K1', 'date': str(d)})
        self.assertEqual(r.status_code, 200, r.data)
        return next(c for c in r.data['categories'] if c['bread_price'] == self.bp.pk)['qty_proposed']

    def test_proposition_vient_du_dernier_reste_de_la_veille_quelle_que_soit_l_equipe(self):
        self._snap(PREV, 'B', 3)
        self._snap(PREV, 'A', 10)
        self.assertEqual(self._proposed(D), 10)
        DailyBreadStockSnapshot.objects.filter(node=self.node, date=PREV).delete()
        self._snap(PREV, 'A', 10)
        self._snap(PREV, 'B', 3)
        self.assertEqual(self._proposed(D), 3)

    def test_modifier_le_stock_de_depart_ne_change_pas_la_cloture_de_la_veille(self):
        self._session('A', closed=True, d=PREV)
        self._snap(PREV, 'A', 10)
        self._sale(5, d=PREV)
        before_row, before = self._row(PREV)
        self.assertEqual(self._proposed(D), 10)
        with _now(8, 0):
            r = self.api.post(OPENING, {
                'team': 'A', 'date': str(D), 'lines': [{'bread_price': self.bp.pk, 'qty': 7}],
            }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        after_row, after = self._row(PREV)
        for d in (before, after):
            d.pop('server_now')   # horodatage de la reponse, seul champ variable
        self.assertEqual(before, after)                       # cloture de la veille inchangee
        self.assertEqual(DailyBreadStockSnapshot.objects.get(node=self.node, date=PREV).qty_at_close, 10)
        today_row, _ = self._row(D)
        self.assertEqual(today_row['reste_du_hier_jour'], -7)  # le jour courant part de la valeur modifiee


class ClotureAutomatiqueTests(_Base):
    """Mission 3 : `auto_close_day`."""

    def setUp(self):
        super().setUp()
        self.node.block_sales_after_closure = True
        self.node.handover_time = time(18, 0)
        self.node.save()
        _adjust_bread_stock(self.node, self.bp, produced=100)

    def test_pas_avant_l_heure_de_cloture_plus_delai_de_grace(self):
        s = self._session()
        self._sale()
        res = auto_close_day(self.node, D, now=_at(D, 18, 10))
        self.assertFalse(res['due'])
        s.refresh_from_db()
        self.assertFalse(s.is_closed)

    def test_cloture_apres_l_heure_journalisee_notifiee_et_idempotente(self):
        s = self._session()
        self._sale()
        res = auto_close_day(self.node, D, now=_at(D, 19, 0))
        self.assertEqual(res['closed'], [s.pk])
        s.refresh_from_db()
        self.assertTrue(s.is_closed)
        snap = DailyBreadStockSnapshot.objects.get(node=self.node, date=D, team='A')
        self.assertEqual(snap.qty_at_close, 90)  # stock physique (100 - 10 vendus), aucun prix invente
        self.assertTrue(ActivityLog.objects.filter(action="Clôture automatique de la fournée").exists())
        notifs = SystemNotification.objects.filter(title__startswith="Fournée clôturée automatiquement")
        self.assertEqual(notifs.count(), 1)
        self.assertIn("réconciliation", notifs.first().message)  # NV / declasses / gratuits non renseignes
        logs = ActivityLog.objects.count()
        again = auto_close_day(self.node, D, now=_at(D, 19, 5))
        self.assertEqual(again['closed'], [])
        self.assertEqual(ActivityLog.objects.count(), logs)
        self.assertEqual(
            SystemNotification.objects.filter(title__startswith="Fournée clôturée automatiquement").count(), 1)

    def test_interrupteur_de_la_boulangerie_requis(self):
        self.node.block_sales_after_closure = False
        self.node.save()
        s = self._session()
        self._sale()
        self.assertFalse(auto_close_day(self.node, D, now=_at(D, 20, 0))['due'])
        s.refresh_from_db()
        self.assertFalse(s.is_closed)
        self.assertEqual(auto_close_day(self.node, D, now=_at(D, 20, 0), require_switch=False)['closed'], [s.pk])

    def test_ne_pas_ecraser_le_reste_saisi_par_le_gerant(self):
        s = self._session()
        self._sale()
        BreadDisposal.objects.create(
            node=self.node, session=s, bread_price=self.bp,
            disposal_type=BreadDisposal.DisposalType.REMAINING, quantity=7,
        )
        auto_close_day(self.node, D, now=_at(D, 19, 0))
        self.assertEqual(DailyBreadStockSnapshot.objects.get(node=self.node, date=D, team='A').qty_at_close, 7)
        self.assertEqual(
            BreadDisposal.objects.get(session=s, disposal_type='REMAINING').quantity, 7)

    def test_ne_pas_ecraser_le_reste_deja_declare_par_l_autre_equipe(self):
        self._session('B', closed=True)
        self._snap(D, 'B', 5)                       # B a cloture manuellement avec un reste de 5
        sa = self._session('A')
        self._sale()
        res = auto_close_day(self.node, D, now=_at(D, 19, 0))
        self.assertEqual(res['closed'], [sa.pk])
        self.assertFalse(DailyBreadStockSnapshot.objects.filter(node=self.node, date=D, team='A').exists())
        row, _ = self._row()
        self.assertEqual(row['reste_du_jour_jour'], 5)

    def test_fournee_sans_livraison_ou_a_zero_sac_laissee_ouverte_et_signalee(self):
        s = self._session()
        res = auto_close_day(self.node, D, now=_at(D, 19, 0))      # aucune livraison ce jour
        self.assertEqual(res['closed'], [])
        self.assertEqual(res['skipped'][0]['reason'], "aucune livraison ce jour")
        s.refresh_from_db()
        self.assertFalse(s.is_closed)
        self.assertTrue(SystemNotification.objects.filter(title__startswith="Fournée non clôturée").exists())
        self._sale()
        z = self._session('B', sacks='0.00')
        res = auto_close_day(self.node, D, now=_at(D, 19, 0))
        self.assertEqual(res['closed'], [s.pk])
        self.assertEqual([x['reason'] for x in res['skipped']], ["fournée à zéro sac"])
        z.refresh_from_db()
        self.assertFalse(z.is_closed)

    def test_jour_courant_ignore_la_fournee_creee_apres_l_heure_de_cloture(self):
        s = self._session()
        ProductionSession.objects.filter(pk=s.pk).update(created_at=_at(D, 18, 30))
        self._sale()
        self.assertEqual(auto_close_day(self.node, D, now=_at(D, 19, 0))['closed'], [])
        # le lendemain, la journee D est terminee : elle est close
        self.assertEqual(auto_close_day(self.node, D, now=_at(D + timedelta(days=1), 9, 0))['closed'], [s.pk])

    def test_declenchee_paresseusement_par_shift_end_status(self):
        s = self._session()
        self._sale()
        with _now(19, 0):
            r = self.api.get(SHIFT, {'node': 'K1'})
        self.assertEqual(r.status_code, 200, r.data)
        s.refresh_from_db()
        self.assertTrue(s.is_closed)

    def test_commande_de_gestion(self):
        s = self._session()
        self._sale()
        with _now(19, 0):
            out = StringIO()
            call_command('auto_close_sessions', stdout=out)
        s.refresh_from_db()
        self.assertTrue(s.is_closed)
        self.assertIn("1 fournée(s) clôturée(s)", out.getvalue())


class ReconciliationDansLaClotureTests(_Base):
    """Mission 4 : NV, declasses, sorties gratuites saisis par categorie apparaissent dans daily-closure."""

    def test_non_vendu_declasses_gratuits_par_categorie(self):
        s = self._session(closed=True)
        for t, q, p in (('UNSOLD', 3, 400), ('DECLASSED', 2, 200), ('FREE_DIST', 4, 0)):
            BreadDisposal.objects.create(
                node=self.node, session=s, bread_price=self.bp, disposal_type=t, quantity=q, unit_price_sold=p,
            )
        row, _ = self._row()
        self.assertEqual(row['non_vendu_nv']['quantity'], 3)
        self.assertEqual(row['declasses']['quantity'], 2)
        self.assertEqual(row['sorties_gratuites']['quantity'], 4)
        # une autre boulangerie ne voit rien de ces valeurs
        other = make_node(code='K2')
        g2 = make_user('GERANT', node=other)
        c2 = APIClient()
        c2.force_authenticate(g2)
        r = c2.get(CLOSURE, {'date': str(D)})
        self.assertEqual(r.status_code, 200, r.data)
        for c in r.data['categories']:
            self.assertEqual(c['non_vendu_nv']['quantity'], 0)
            self.assertEqual(c['sorties_gratuites']['quantity'], 0)
