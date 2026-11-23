"""
Testeur ventes (Dev A, cycle a4, 2026-11-22) : contre-attaque de la verification des corrections
BUG-640..650 (verrous, annulation nette, retentative sur verrou). Donnees fictives uniquement.

Les tests marques `@expectedFailure` portent un ticket BUG-66x ouvert.
"""
import threading
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.db import OperationalError, connection
from django.test import TransactionTestCase

from core.models import Config
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import BreadStock
from sales.models import Invoice
from sales.tests.test_ventes_a3_v2 import Base, INV, _api

D = Decimal


class AnnulationEtNonServiApresAjustement(Base):
    def _adjust(self, iid, sign, qty, payment=0):
        return _api(self.g1).post(f'{INV}{iid}/adjust/', {
            'adjustment_sign': sign, 'payment_amount': payment,
            'lines': [{'bread_price': self.bp3.pk, 'quantity': qty}]}, format='json')

    def test_annulation_apres_ajustement_positif_avec_versement(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}]).data['id']
        self.assertEqual(self._adjust(iid, 1, 1, payment=300).status_code, 201)
        self.assertEqual((self.debt(), self.sent()), (D(600), 3))
        r = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))

    def test_annulation_apres_deux_ajustements_opposes(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 4}]).data['id']
        self.assertEqual(self._adjust(iid, -1, 3).status_code, 201)
        self.assertEqual(self._adjust(iid, 1, 2).status_code, 201)
        self.assertEqual((self.debt(), self.sent()), (D(900), 3))
        r = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))

    def test_BUG_660_non_servi_apres_ajustement_negatif_double_restitution(self):
        """BUG-660 : mark-not-served apres un ajustement -1 restitue la quantite d'ORIGINE
        (comme BUG-648 pour cancel) : BP -300 et stock -1 au lieu de 0 / 0."""
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}]).data['id']
        self.assertEqual(self._adjust(iid, -1, 1).status_code, 201)
        self.assertEqual((self.debt(), self.sent()), (D(300), 1))
        r = _api(self.fa1).post(f'{INV}{iid}/mark-not-served/', {}, format='json')
        if r.status_code == 200:
            self.assertEqual((self.debt(), self.sent()), (D(0), 0),
                             'non servi apres ajustement : restitution double')

    def test_BUG_660_expiration_apres_ajustement_negatif_double_restitution(self):
        """BUG-660 (volet expiration 12 h : meme service `mark_not_served`)."""
        from datetime import timedelta
        from django.utils import timezone
        from sales.services import expire_pending_invoices
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}]).data['id']
        self.assertEqual(self._adjust(iid, -1, 1).status_code, 201)
        Invoice.objects.filter(pk=iid).update(created_at=timezone.now() - timedelta(hours=13))
        expire_pending_invoices()
        self.assertEqual((self.debt(), self.sent()), (D(0), 0), 'expiration : restitution double')

    def test_livraison_partielle_apres_ajustement_negatif_net_coherent(self):
        """Livraison partielle (1 sur 2) apres ajustement -1 : 2 commandes - 1 repris - 1 non servi
        = 0 pain net : BP 0 et stock 0 (verifie : coherent, pas un defaut)."""
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}]).data['id']
        self.assertEqual(self._adjust(iid, -1, 1).status_code, 201)
        lid = Invoice.objects.get(pk=iid).lines.first().pk
        r = _api(self.lv1).post(f'{INV}{iid}/deliver/', {'lines': [{'id': lid, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))

    def test_BUG_662_non_servi_apres_ajustement_positif_laisse_vente_fantome(self):
        """BUG-662 : mark-not-served d'une originale ayant un ajustement +1 : l'originale est
        annulee mais l'ajustement (vente de 1 pain, BP +300, stock -1) subsiste, alors que
        BUG-649 interdit d'ajuster une facture non servie. Attendu : refus (400/409) ou
        restitution nette (BP 0, stock 0)."""
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}]).data['id']
        self.assertEqual(self._adjust(iid, 1, 1).status_code, 201)
        r = _api(self.fa1).post(f'{INV}{iid}/mark-not-served/', {}, format='json')
        if r.status_code == 200:
            self.assertEqual((self.debt(), self.sent()), (D(0), 0), 'vente fantome (ajustement) conservee')


class _Sync:
    """Aide : met en pause la requete adjust juste apres ses controles et avant sa transaction
    (premier appel de `Config.get_instance` dans la vue), pour rejouer de facon deterministe
    une concurrence."""

    def __init__(self, parties=1):
        self.reached = threading.Semaphore(0)
        self.go = threading.Event()
        self.local = threading.local()
        self.orig = Config.get_instance.__func__

    def install(self):
        sync = self
        orig = self.orig

        def gi(cls, *a, **kw):
            if getattr(sync.local, 'pause', False):
                sync.local.pause = False
                sync.reached.release()
                sync.go.wait(20)
            return orig(cls, *a, **kw)
        return patch.object(Config, 'get_instance', classmethod(gi))


class AdjustSansVerrouFacture(TransactionTestCase):
    def setUp(self):
        self.n1 = make_node(code='AV4')
        self.fa = make_user('FACTURIER', node=self.n1, team='A', username='a4_fa')
        self.g = make_user('GERANT', node=self.n1, team='A', username='a4_g')
        self.bp = make_bread_price('A43', 'Pain 300', 300)
        self.cl = make_client(self.n1)
        r = _api(self.fa).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': 0,
                                     'lines': [{'bread_price': self.bp.pk, 'quantity': 2}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.iid = r.data['id']

    def _state(self):
        self.cl.refresh_from_db()
        st = BreadStock.objects.get(node=self.n1, bread_price=self.bp)
        return self.cl.current_debt, st.qty_sent

    def _adjust_paused(self, sync, out, key, sign=-1, qty=2):
        def run():
            sync.local.pause = True
            try:
                out[key] = _api(self.g).post(f'{INV}{self.iid}/adjust/', {
                    'adjustment_sign': sign, 'payment_amount': 0,
                    'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}, format='json').status_code
            finally:
                connection.close()
        t = threading.Thread(target=run)
        t.start()
        return t

    def test_BUG_661_ajustement_concurrent_a_une_annulation(self):
        """BUG-661 : `adjust` controle le statut et le net restant de l'originale HORS transaction
        et sans verrou : une annulation passee entre le controle et l'ecriture laisse un ajustement
        -2 sur une facture annulee (net restitue deux fois : BP -600, stock -... ) ."""
        sync = _Sync()
        out = {}
        with sync.install():
            t = self._adjust_paused(sync, out, 'adj', sign=-1, qty=1)
            self.assertTrue(sync.reached.acquire(timeout=20), "l'ajustement n'a pas atteint son point d'arret")
            rc = _api(self.fa).post(f'{INV}{self.iid}/cancel/', {}, format='json')
            self.assertEqual(rc.status_code, 200, rc.data)
            sync.go.set()
            t.join(30)
        self.assertEqual(self._state(), (D(0), 0), f'annulee puis ajustee : {out}')

    def test_BUG_663_deux_ajustements_simultanes_un_seul_500_sans_retentative(self):
        """BUG-663 (et racine BUG-661) : deux ajustements -2 simultanes sur une originale de
        2 pains passent tous deux le controle « net restant » (lu hors verrou) : 4 pains repris
        pour 2 vendus sur PostgreSQL ; sous SQLite le 2e appel echoue en 500 (`database table is locked`,
        `adjust` n'a PAS la retentative `_retry_on_lock` de deliver/cancel) au lieu de 400 propre."""
        sync = _Sync()
        out = {}
        with sync.install():
            t1 = self._adjust_paused(sync, out, 'a1')
            self.assertTrue(sync.reached.acquire(timeout=20))
            t2 = self._adjust_paused(sync, out, 'a2')
            self.assertTrue(sync.reached.acquire(timeout=20))
            sync.go.set()
            t1.join(30)
            t2.join(30)
        debt, sent = self._state()
        self.assertGreaterEqual(sent, 0, f'stock negatif : {out}')
        self.assertGreaterEqual(debt, 0, f'BP negative (credit fantome) : {out}')
        self.assertEqual(sorted(out.values()), [201, 400], out)


class RetentativeSurVerrou(Base):
    def test_erreur_metier_ou_sql_non_masquee_une_seule_tentative(self):
        from sales import views
        calls = []

        def boom():
            calls.append(1)
            raise OperationalError('no such table: sales_invoice')
        with patch.object(views.time, 'sleep'):
            with self.assertRaises(OperationalError):
                views._retry_on_lock(boom)
        self.assertEqual(len(calls), 1)

    def test_verrou_retente_puis_reussit_et_epuise_au_bout_de_100(self):
        from sales import views
        n = {'c': 0}

        def flaky():
            n['c'] += 1
            if n['c'] < 4:
                raise OperationalError('database table is locked')
            return 'ok'
        with patch.object(views.time, 'sleep'):
            self.assertEqual(views._retry_on_lock(flaky), 'ok')
            n['c'] = -10 ** 6
            with self.assertRaises(OperationalError):
                views._retry_on_lock(flaky)

    def test_deliver_sur_erreur_non_verrou_donne_500_sans_effet(self):
        """Une OperationalError qui n'est pas un verrou n'est pas masquee en succes et ne laisse
        aucun effet partiel (stock, BP, statut)."""
        iid = self.post().data['id']
        with patch('sales.views.deliver_invoice', side_effect=OperationalError('disk I/O error')):
            r = _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        self.assertEqual(r.status_code, 500)
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')
        self.assertEqual((self.debt(), self.sent()), (D(3000), 10))


class FiltresNouveauxAngles(Base):
    def test_search_caracteres_speciaux_sans_500(self):
        a = _api(self.fa1)
        self.assertIn(a.get(INV, {'search': '\x00'}).status_code, (200, 400))
        for s in ('%', '_', '\\', "'; DROP TABLE x;--", 'é' * 500, '"' * 50, ' '.join(['a'] * 50)):
            r = a.get(INV, {'search': s})
            self.assertEqual(r.status_code, 200, (s[:20], r.status_code))

    def test_search_borne_trouve_toujours_par_code_client(self):
        self.post()
        r = _api(self.fa1).get(INV, {'search': self.cl.code})
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data['results'] if isinstance(r.data, dict) else r.data), 1)

    def test_filtres_entiers_geants_sans_500(self):
        a = _api(self.fa1)
        for params in ({'node': '9' * 30}, {'status': 'X' * 5000}, {'client': 'z' * 500},
                       {'adjusts': '9' * 30}, {'invoice_date': '9999-99-99'}, {'ordering': 'x' * 5000},
                       {'page': '9' * 30}):
            r = a.get(INV, params)
            self.assertIn(r.status_code, (200, 400, 404), (list(params), r.status_code))
