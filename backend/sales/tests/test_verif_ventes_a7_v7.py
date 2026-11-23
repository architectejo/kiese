"""
Testeur ventes (Dev A, cycle a5, 2026-11-23) : contre-attaque de BUG-660 a 663 (restitution nette
« Non servi », verrou de l'originale dans adjust, retentative). Donnees fictives uniquement.
"""
import threading
from datetime import timedelta
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.db import OperationalError, connection
from django.test import TransactionTestCase
from django.utils import timezone

from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import BreadStock
from sales.models import Invoice
from sales.services import expire_pending_invoices
from sales.tests.test_ventes_a3_v2 import Base, INV, _api

D = Decimal


class NonServiEtAjustements(Base):
    def _adj(self, iid, sign, qty, payment=0, bp=None):
        return _api(self.g1).post(f'{INV}{iid}/adjust/', {
            'adjustment_sign': sign, 'payment_amount': payment,
            'lines': [{'bread_price': (bp or self.bp3).pk, 'quantity': qty}]}, format='json')

    def _ns(self, iid, user=None):
        return _api(user or self.fa1).post(f'{INV}{iid}/mark-not-served/', {}, format='json')

    def _expire(self, iid):
        Invoice.objects.filter(pk=iid).update(created_at=timezone.now() - timedelta(hours=13))
        return expire_pending_invoices()

    def _orig(self, qty=3, **extra):
        r = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': qty}], **extra)
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def test_multiples_ajustements_mixtes_non_servi_manuel(self):
        iid = self._orig(3)
        for s, q in ((1, 2), (-1, 1), (1, 4), (-1, 5)):
            self.assertEqual(self._adj(iid, s, q).status_code, 201)
        self.assertEqual(self.sent(), 3 + 2 - 1 + 4 - 5)
        r = self._ns(iid)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))
        self.assertEqual(Invoice.objects.filter(adjusts_id=iid).exclude(status='CANCELLED').count(), 0)

    def test_multiples_ajustements_mixtes_expiration(self):
        iid = self._orig(3)
        for s, q in ((1, 2), (-1, 3), (1, 1)):
            self.assertEqual(self._adj(iid, s, q).status_code, 201)
        self.assertEqual(self._expire(iid), 1)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))
        self.assertEqual(self._expire(iid), 0)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))

    def test_versement_original_conserve_et_ajustement_neutralise(self):
        iid = self._orig(2, payment_amount=500)
        self.assertEqual(self._adj(iid, 1, 1, payment=300).status_code, 201)
        self.assertEqual(self._ns(iid).status_code, 200)
        self.assertEqual(self.debt(), D(-500))
        self.assertEqual(self.sent(), 0)

    def test_ajustement_negatif_avec_remboursement_puis_non_servi(self):
        iid = self._orig(2, payment_amount=600)
        self.assertEqual(self._adj(iid, -1, 1, payment=100).status_code, 201)
        self.assertEqual(self._ns(iid).status_code, 200)
        self.assertEqual((self.debt(), self.sent()), (D(-600), 0))

    def test_ajustement_apres_non_servi_et_apres_annulation_refuse(self):
        a = self._orig(2)
        b = self._orig(2)
        self.assertEqual(self._ns(a).status_code, 200)
        _api(self.fa1).post(f'{INV}{b}/cancel/', {}, format='json')
        for iid in (a, b):
            for s in (1, -1):
                self.assertEqual(self._adj(iid, s, 1).status_code, 400)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))

    def test_non_servi_deux_fois_et_apres_annulation(self):
        iid = self._orig(2)
        self._adj(iid, 1, 1)
        self.assertEqual(self._ns(iid).status_code, 200)
        self.assertEqual(self._ns(iid).status_code, 409)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))
        c = self._orig(2)
        self._adj(c, -1, 1)
        _api(self.fa1).post(f'{INV}{c}/cancel/', {}, format='json')
        self.assertEqual(self._ns(c).status_code, 409)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))

    def test_aucun_negatif_fantome_ajustement_total_puis_non_servi(self):
        iid = self._orig(2)
        self.assertEqual(self._adj(iid, -1, 2).status_code, 201)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))
        self.assertEqual(self._ns(iid).status_code, 200)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))
        self.assertGreaterEqual(BreadStock.objects.get(node=self.n1, bread_price=self.bp3).qty_sent, 0)

    def test_vente_sans_client_ajustements_non_servi(self):
        iid = self.post(client=False, payment_type='CASH', payment_amount=600,
                        lines=[{'bread_price': self.bp3.pk, 'quantity': 2}]).data['id']
        r = self._adj(iid, 1, 1, payment=300)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self._ns(iid).status_code, 200)
        self.assertEqual(self.sent(), 0)

    def test_vente_solde_ajustement_non_servi(self):
        iid = self._orig(4, is_soldee=True, payment_amount=900)
        self.assertEqual(self._adj(iid, 1, 2).status_code, 201)
        self.assertEqual(self._ns(iid).status_code, 200)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))

    def test_ajustement_sur_livraison_partielle(self):
        iid = self._orig(4)
        lid = Invoice.objects.get(pk=iid).lines.first().pk
        r = _api(self.lv1).post(f'{INV}{iid}/deliver/', {'lines': [{'id': lid, 'quantity': 3}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((self.debt(), self.sent()), (D(900), 3))
        self.assertEqual(self._ns(iid).status_code, 409)
        self.assertEqual(self._adj(iid, -1, 4).status_code, 400)       # 3 net seulement
        self.assertEqual(self._adj(iid, -1, 3).status_code, 201)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))

    def test_plafond_libere_apres_non_servi(self):
        iid = self._orig(1)
        self.cl.refresh_from_db()
        self.cl.current_debt = D(49700)
        self.cl.save()
        self.assertEqual(self._adj(iid, 1, 1).status_code, 201)            # BP 50000
        self.assertEqual(self.post().status_code, 403)                      # plafond atteint
        self.assertEqual(self._ns(iid).status_code, 200)
        self.assertEqual(self.debt(), D(49400))     # 50000 - 300 (originale) - 300 (ajustement)
        self.assertEqual(self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 1}]).status_code, 201)

    def test_prix_fige_non_recalcule_apres_changement_catalogue(self):
        iid = self._orig(2)
        self.assertEqual(self._adj(iid, 1, 1).status_code, 201)
        self.bp3.unit_price = 450
        self.bp3.save()
        self.assertEqual(self._ns(iid).status_code, 200)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))

    def test_journal_non_servi_avec_ajustements(self):
        from core.models import ActivityLog
        iid = self._orig(2)
        self._adj(iid, 1, 1)
        self._ns(iid)
        self.assertTrue(ActivityLog.objects.filter(action='Facture Non Servi').exists())


class ConcurrenceAjustements(TransactionTestCase):
    def setUp(self):
        self.n1 = make_node(code='AV7')
        self.fa = make_user('FACTURIER', node=self.n1, team='A', username='a7_fa')
        self.g = make_user('GERANT', node=self.n1, team='A', username='a7_g')
        self.bp = make_bread_price('A73', 'Pain 300', 300)
        self.cl = make_client(self.n1)
        r = _api(self.fa).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': 0,
                                     'lines': [{'bread_price': self.bp.pk, 'quantity': 2}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.iid = r.data['id']
        import logging, traceback
        self.errs = []
        errs = self.errs

        class H(logging.Handler):
            def emit(self, rec):
                if rec.exc_info:
                    errs.append(' | '.join(l.strip() for l in traceback.format_exception(*rec.exc_info) if 'kiesse' in l or 'locked' in l)[-900:])
        self._h = H()
        logging.getLogger('django.request').addHandler(self._h)
        self.addCleanup(logging.getLogger('django.request').removeHandler, self._h)

    def _state(self):
        self.cl.refresh_from_db()
        return self.cl.current_debt, BreadStock.objects.get(node=self.n1, bread_price=self.bp).qty_sent

    def _run(self, fns):
        out = [None] * len(fns)
        barrier = threading.Barrier(len(fns))

        def wrap(i, f):
            try:
                barrier.wait(10)
                out[i] = f()
            except Exception as exc:  # noqa
                out[i] = repr(exc)
            finally:
                connection.close()
        ts = [threading.Thread(target=wrap, args=(i, f)) for i, f in enumerate(fns)]
        [t.start() for t in ts]
        [t.join(120) for t in ts]
        self.assertFalse(any(t.is_alive() for t in ts), 'blocage (verrous) : thread encore vivant')
        if self.errs:
            out = out + self.errs[:1]
        return out

    def _adj(self, sign, qty):
        return lambda: _api(self.g).post(f'{INV}{self.iid}/adjust/', {
            'adjustment_sign': sign, 'payment_amount': 0,
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}, format='json').status_code

    def _ns(self):
        return lambda: _api(self.fa).post(f'{INV}{self.iid}/mark-not-served/', {}, format='json').status_code

    def _cancel(self):
        return lambda: _api(self.fa).post(f'{INV}{self.iid}/cancel/', {}, format='json').status_code

    def test_trois_ajustements_negatifs_simultanes_bornes(self):
        out = self._run([self._adj(-1, 1)] * 3)
        self.assertTrue(all(c in (201, 400) for c in out), out)
        self.assertEqual(out.count(201), 2, out)
        self.assertEqual(self._state(), (D(0), 0), out)

    def test_ajustement_positif_et_negatif_simultanes(self):
        out = self._run([self._adj(1, 2), self._adj(-1, 2)])
        self.assertTrue(all(c in (201, 400) for c in out), out)
        debt, sent = self._state()
        self.assertEqual(debt, D(300) * sent, out)
        self.assertGreaterEqual(sent, 0)

    def test_non_servi_et_ajustement_simultanes(self):
        out = self._run([self._ns(), self._adj(1, 1)])
        # Le 500 intermittent de `adjust` (get_object hors retentative) est suivi par BUG-1001
        # (test deterministe) ; ici seule la coherence de l'etat est controlee.
        self.assertIn(out[0], (200, 409, 500), out)
        self.assertIn(out[1], (201, 400, 500), out)
        if out[0] == 200:
            self.assertEqual(self._state(), (D(0), 0), out)

    def test_non_servi_annulation_ajustement_sans_blocage(self):
        out = self._run([self._ns(), self._cancel(), self._adj(-1, 1)])
        self.assertTrue(all(isinstance(c, int) for c in out[:3]), out)   # BUG-1001 : 500 possibles
        self.assertEqual(self._state(), (D(0), 0), out)

    def test_deux_non_servi_simultanes(self):
        out = self._run([self._ns(), self._ns()])
        self.assertEqual(sorted(out), [200, 409], out)
        self.assertEqual(self._state(), (D(0), 0))

    def test_expiration_et_ajustement_simultanes(self):
        Invoice.objects.filter(pk=self.iid).update(created_at=timezone.now() - timedelta(hours=13))
        out = self._run([lambda: expire_pending_invoices(), self._adj(1, 1)])
        self.assertIsInstance(out[0], int, out)
        if Invoice.objects.get(pk=self.iid).status == 'NOT_SERVED':
            self.assertEqual(self._state(), (D(0), 0), out)


class RetentativeGetObject(Base):
    """BUG-1001 : `get_object()` est appele AVANT `_retry_on_lock` dans adjust / mark-not-served /
    cancel / deliver : un verrou SQLite (`database table is locked`) a cet endroit donne un 500."""

    _adj = NonServiEtAjustements._adj
    _ns = NonServiEtAjustements._ns
    _orig = NonServiEtAjustements._orig

    def _flaky_get_object(self):
        from sales.views import InvoiceViewSet
        real = InvoiceViewSet.get_object
        n = {'c': 0}

        def flaky(view):
            n['c'] += 1
            if n['c'] == 1:
                raise OperationalError('database table is locked')
            return real(view)
        return patch.object(InvoiceViewSet, 'get_object', flaky)

    def test_BUG_1001_adjust_verrou_sur_get_object_non_retente(self):
        iid = self._orig(2)
        with self._flaky_get_object():
            r = self._adj(iid, -1, 1)
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))

    def test_BUG_1001_mark_not_served_verrou_sur_get_object_non_retente(self):
        iid = self._orig(2)
        with self._flaky_get_object():
            r = self._ns(iid)
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))

    def test_BUG_1001_cancel_verrou_sur_get_object_non_retente(self):
        iid = self._orig(2)
        with self._flaky_get_object():
            r = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
