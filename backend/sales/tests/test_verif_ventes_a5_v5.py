"""
Testeur ventes (cycle a5, 2026-11-22) : verification independante des tickets
BUG-610/611/613/640 a 650 (+ BUG-824 sur factures en attente) et nouveaux angles.
Donnees fictives uniquement. Aucun code applicatif modifie.

Sections :
  V  verifications independantes des corrections (verrous, atomicite, retentative, bornes)
  N  nouveaux defauts (BUG-664 et suivants), `@expectedFailure` portant la reference du ticket
"""
import threading
from datetime import timedelta
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.db import connection
from django.db.models.query import QuerySet
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from clients.models import Client
from core.models import Config
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import BreadStock
from sales import views as sales_views
from sales.models import Invoice
from sales.tests.test_ventes_a3_v2 import Base, INV, _api

D = Decimal


class _Spy:
    """Journal ordonne des verrous (select_for_update) et des ecritures de facture."""

    def __init__(self):
        self.events = []

    def __enter__(self):
        spy = self
        orig_sfu = QuerySet.select_for_update
        orig_save = Invoice.save

        def sfu(qs, *a, **kw):
            spy.events.append(('lock', qs.model.__name__, kw.get('of')))
            return orig_sfu(qs, *a, **kw)

        def save(inv, *a, **kw):
            spy.events.append(('save', 'Invoice', None))
            return orig_save(inv, *a, **kw)

        self.patches = [patch.object(QuerySet, 'select_for_update', sfu), patch.object(Invoice, 'save', save)]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()

    def first(self, kind, model):
        for i, e in enumerate(self.events):
            if e[0] == kind and e[1] == model:
                return i
        return None

    def locks(self, model):
        return [e for e in self.events if e[0] == 'lock' and e[1] == model]


# =============================================================================== V
class VerrousOrdreEtPortee(Base):
    """BUG-640/641/642 : le verrou du client precede toute ecriture de facture ; la facture est
    verrouillee `of=('self',)` (pas de FOR UPDATE sur la jointure externe)."""

    def _delivered(self):
        iid = self.post().data['id']
        _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        return iid

    def _assert_client_locked_before_write(self, spy):
        lock, write = spy.first('lock', 'Client'), spy.first('save', 'Invoice')
        self.assertIsNotNone(lock, spy.events)
        self.assertIsNotNone(write, spy.events)
        self.assertLess(lock, write, f'ecriture de facture avant le verrou client : {spy.events}')

    def test_vente_verrou_client_avant_ecriture(self):
        with _Spy() as spy:
            self.assertEqual(self.post(payment_amount=100).status_code, 201)
        self._assert_client_locked_before_write(spy)

    def test_remboursement_verrou_client_avant_ecriture(self):
        with _Spy() as spy:
            self.assertEqual(self.post(lines=[], payment_amount=100, is_debt_repayment=True).status_code, 201)
        self._assert_client_locked_before_write(spy)

    def test_paiement_negatif_verrou_client_avant_ecriture(self):
        with _Spy() as spy:
            r = self.post(lines=[], payment_amount=-100, is_debt_repayment=True)
        self.assertEqual(r.status_code, 201, r.data)
        self._assert_client_locked_before_write(spy)

    def test_ajustement_verrou_client_avant_ecriture(self):
        iid = self._delivered()
        body = {'adjustment_sign': 1, 'payment_amount': 0, 'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}
        with _Spy() as spy:
            self.assertEqual(_api(self.g1).post(f'{INV}{iid}/adjust/', body, format='json').status_code, 201)
        self._assert_client_locked_before_write(spy)

    def test_annulation_verrouille_facture_of_self_et_client(self):
        iid = self.post().data['id']
        with _Spy() as spy:
            self.assertEqual(_api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json').status_code, 200)
        self.assertTrue(any(e[2] == ('self',) for e in spy.locks('Invoice')), spy.events)
        self.assertTrue(spy.locks('Client'), spy.events)
        self.assertLess(spy.first('lock', 'Invoice'), spy.first('save', 'Invoice'))

    def test_livraison_non_servi_expiration_verrou_facture_of_self(self):
        a, b, c = (self.post().data['id'] for _ in range(3))
        with _Spy() as spy:
            self.assertEqual(_api(self.lv1).post(f'{INV}{a}/deliver/', {}, format='json').status_code, 200)
        self.assertTrue(spy.locks('Invoice') and all(e[2] == ('self',) for e in spy.locks('Invoice')), spy.events)
        with _Spy() as spy:
            self.assertEqual(_api(self.fa1).post(f'{INV}{b}/mark-not-served/', {}, format='json').status_code, 200)
        self.assertTrue(spy.locks('Invoice') and all(e[2] == ('self',) for e in spy.locks('Invoice')), spy.events)
        Invoice.objects.filter(pk=c).update(created_at=timezone.now() - timedelta(hours=13))
        from sales.services import expire_pending_invoices
        with _Spy() as spy:
            self.assertEqual(expire_pending_invoices(), 1)
        self.assertTrue(spy.locks('Invoice') and all(e[2] == ('self',) for e in spy.locks('Invoice')), spy.events)

    def test_numero_de_recu_verrouille_le_noeud(self):
        with _Spy() as spy:
            self.post()
        self.assertTrue(spy.locks('Node'), spy.events)


class AtomiciteDesActions(Base):
    """BUG-642/650 : une erreur au milieu d'une action ne laisse aucun effet partiel."""

    def test_annulation_echec_stock_aucun_effet_partiel(self):
        iid = self.post().data['id']
        with patch('sales.views._adjust_bread_stock', side_effect=RuntimeError('panne')):
            r = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 500)
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')
        self.assertEqual((self.debt(), self.sent()), (D(3000), 10))

    def test_annulation_echec_journal_aucun_effet_partiel(self):
        iid = self.post().data['id']
        with patch('sales.views.log_activity', side_effect=RuntimeError('panne')):
            r = _api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 500)
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')
        self.assertEqual((self.debt(), self.sent()), (D(3000), 10))

    def test_non_servi_echec_journal_aucun_effet_partiel(self):
        iid = self.post().data['id']
        with patch('sales.services.log_activity', side_effect=RuntimeError('panne')):
            r = _api(self.fa1).post(f'{INV}{iid}/mark-not-served/', {}, format='json')
        self.assertEqual(r.status_code, 500)
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')
        self.assertEqual((self.debt(), self.sent()), (D(3000), 10))

    def test_livraison_partielle_echec_journal_aucun_effet_partiel(self):
        r = self.post()
        iid, lid = r.data['id'], r.data['lines'][0]['id']
        with patch('sales.services.log_activity', side_effect=RuntimeError('panne')):
            r = _api(self.lv1).post(f'{INV}{iid}/deliver/', {'lines': [{'id': lid, 'quantity': 4}]}, format='json')
        self.assertEqual(r.status_code, 500)
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')
        self.assertEqual((self.debt(), self.sent()), (D(3000), 10))
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 0)

    def test_creation_echec_en_cours_aucun_effet_partiel(self):
        with patch('sales.views._adjust_bread_stock', side_effect=RuntimeError('panne')):
            r = self.post()
        self.assertEqual(r.status_code, 500)
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(self.debt(), 0)

    def test_annulations_successives_jamais_de_double_restitution(self):
        iid = self.post().data['id']
        codes = [_api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json').status_code for _ in range(4)]
        self.assertEqual(codes, [200, 400, 400, 400])
        self.assertEqual((self.debt(), self.sent()), (D(0), 0))


class BornesEtRecherche(Base):
    """BUG-610/611/613/645 : angles complementaires."""

    def test_recherche_termes_et_longueur_bornes(self):
        f = sales_views.BoundedSearchFilter()
        req = APIRequestFactory().get(INV, {'search': ' '.join(f't{i}' for i in range(40))})
        from rest_framework.request import Request
        terms = f.get_search_terms(Request(req))
        self.assertLessEqual(len(terms), 5)
        req = APIRequestFactory().get(INV, {'search': 'x' * 100000})
        terms = f.get_search_terms(Request(req))
        self.assertTrue(all(len(t) <= 100 for t in terms))

    def test_recherche_longue_200_et_trouve_toujours_le_code_client(self):
        self.post()
        a = _api(self.fa1)
        self.assertEqual(a.get(INV, {'search': 'z' * 100000}).status_code, 200)
        r = a.get(INV, {'search': self.cl.code})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['count'], 1)

    def test_deliver_ligne_chiffres_pleine_chasse_ou_unicode_refuses(self):
        r = self.post()
        iid, lid = r.data['id'], r.data['lines'][0]['id']
        for qty in ('３', '٣', '1e1', '+1', '0x2', '1.5', '', ' ', None, [], {}, '-0'):
            rr = _api(self.lv1).post(f'{INV}{iid}/deliver/', {'lines': [{'id': lid, 'quantity': qty}]}, format='json')
            self.assertEqual(rr.status_code, 400, (qty, rr.status_code, getattr(rr, 'data', '')))
        self.assertEqual(Invoice.objects.get(pk=iid).status, 'PENDING')
        self.assertEqual((self.debt(), self.sent()), (D(3000), 10))

    def test_adjust_valeurs_limites_refusees_sans_effet(self):
        iid = self.post().data['id']
        _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        bad = [{'bread_price': self.bp3.pk, 'quantity': q} for q in (0, -1, '٣', '3.0', 3.0, True, None, 100001)]
        bad += [{'bread_price': b, 'quantity': 1} for b in (0, -1, '٣', 2 ** 31, 1.0, None, '')]
        bad += [{'quantity': 1}, {'bread_price': self.bp3.pk}, {}]
        for line in bad:
            r = _api(self.g1).post(f'{INV}{iid}/adjust/', {'adjustment_sign': 1, 'payment_amount': 0,
                                                            'lines': [line]}, format='json')
            self.assertEqual(r.status_code, 400, (line, r.status_code, getattr(r, 'data', '')))
        self.assertEqual(Invoice.objects.filter(is_adjustment=True).count(), 0)
        self.assertEqual((self.debt(), self.sent()), (D(3000), 10))

    def test_bread_summary_node_hq(self):
        a = _api(self.adm)
        for bad in ('１', '٣', '1_0', ' ', '0x1', '1e1', '+1'):
            self.assertEqual(a.get(f'{INV}bread_summary/', {'node': bad}).status_code, 400, bad)
        self.assertEqual(a.get(f'{INV}bread_summary/', {'node': self.n1.pk}).status_code, 200)


class Compteur824PourFacturesEnAttente(Base):
    """BUG-824 verifie sur facture livree ; ici la facture n'est PAS encore livree."""

    def _adj(self, iid, sign, qty):
        return _api(self.g1).post(f'{INV}{iid}/adjust/', {
            'adjustment_sign': sign, 'payment_amount': 0,
            'lines': [{'bread_price': self.bp3.pk, 'quantity': qty}]}, format='json')

    def test_livree_puis_ajustee_compteur_signe(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 10}]).data['id']
        _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        self.assertEqual(self._adj(iid, -1, 3).status_code, 201)
        self.assertEqual(self._adj(iid, 1, 5).status_code, 201)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 12)

    def test_ajustement_pendant_attente_puis_livraison_compteur_net(self):
        """Compteur initial 10 : en attente 4, ajustement -1 (9), livraison +4 -> 13 attendu (10 + 4 - 1)."""
        Client.objects.filter(pk=self.cl.pk).update(total_breads_received=10)
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 4}]).data['id']
        self.assertEqual(self._adj(iid, -1, 1).status_code, 201)
        _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 13)


# =============================================================================== V (concurrence)
class ConcurrenceSqlite(TransactionTestCase):
    """BUG-650 et verrous : N requetes simultanees (SQLite : serialisation + retentative)."""

    def setUp(self):
        self.n1 = make_node(code='EV5')
        self.fa = make_user('FACTURIER', node=self.n1, team='A', username='ev5_fa')
        self.lv = make_user('LIVREUR', node=self.n1, team='A', username='ev5_lv')
        self.g = make_user('GERANT', node=self.n1, team='A', username='ev5_g')
        self.bp = make_bread_price('EV53', 'Pain 300', 300)
        self.cl = make_client(self.n1)

    def _new(self, qty=10, payment=0):
        r = _api(self.fa).post(INV, {'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': payment,
                                     'lines': [{'bread_price': self.bp.pk, 'quantity': qty}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def _race(self, jobs):
        """jobs : liste de (cle, callable renvoyant un status_code)."""
        res, errs = {}, []
        barrier = threading.Barrier(len(jobs))

        def run(key, fn):
            try:
                barrier.wait()
                res[key] = fn()
            except Exception as exc:     # pragma: no cover
                errs.append(f'{key}: {type(exc).__name__}: {exc}'[:150])
                res[key] = 500
            finally:
                connection.close()

        ts = [threading.Thread(target=run, args=j) for j in jobs]
        [t.start() for t in ts]
        [t.join(120) for t in ts]
        return res, errs

    def _state(self):
        self.cl.refresh_from_db()
        st = BreadStock.objects.filter(node=self.n1, bread_price=self.bp).first()
        return self.cl.current_debt, (st.qty_sent if st else 0)

    def _post(self, who, path, body=None):
        """Comme un utilisateur qui reclique : une lecture `get_object()` placee hors de `_retry_on_lock`
        peut lever « table is locked » sur la base SQLite en memoire a cache partage des tests
        (inexistant en WAL sur le poste reel) ; on rejoue la requete, jamais une autre erreur."""
        import random
        import time
        from django.db import OperationalError
        a = _api(who)
        a.raise_request_exception = True
        for _ in range(60):
            try:
                return a.post(f'{INV}{path}', body or {}, format='json').status_code
            except OperationalError as exc:
                if 'locked' not in str(exc).lower():
                    raise
                time.sleep(random.uniform(0.02, 0.15))
        return 500

    def test_quatre_annulations_simultanees_une_seule_restitution(self):
        iid = self._new()
        res, errs = self._race([(i, lambda: self._post(self.fa, f'{iid}/cancel/')) for i in range(4)])
        self.assertEqual(sorted(res.values()), [200, 400, 400, 400], (res, errs))
        self.assertEqual(self._state(), (D(0), 0))

    def test_livraison_et_non_servi_simultanes_etat_coherent(self):
        iid = self._new()
        res, errs = self._race([
            ('d', lambda: self._post(self.lv, f'{iid}/deliver/')),
            ('n', lambda: self._post(self.fa, f'{iid}/mark-not-served/')),
        ])
        self.assertNotIn(500, res.values(), (res, errs))
        inv = Invoice.objects.get(pk=iid)
        if inv.status == 'DELIVERED':
            self.assertEqual(self._state(), (D(3000), 10), res)
            self.assertEqual(res['n'], 409, res)
        else:
            self.assertEqual(inv.status, 'NOT_SERVED')
            self.assertEqual(self._state(), (D(0), 0), res)

    def test_annulation_et_non_servi_simultanes_une_seule_restitution(self):
        iid = self._new()
        res, errs = self._race([
            ('c', lambda: self._post(self.fa, f'{iid}/cancel/')),
            ('n', lambda: self._post(self.fa, f'{iid}/mark-not-served/')),
        ])
        self.assertNotIn(500, res.values(), (res, errs))
        self.assertEqual(self._state(), (D(0), 0), res)

    def test_ventes_simultanees_meme_client_bp_exacte(self):
        n = 6
        res, errs = self._race([
            (i, lambda: self._post(self.fa, '', {
                'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': 0,
                'lines': [{'bread_price': self.bp.pk, 'quantity': 2}]})) for i in range(n)
        ])
        ok = sum(1 for v in res.values() if v == 201)
        self.assertEqual(ok, n, (res, errs))
        self.assertEqual(self._state(), (D(600) * n, 2 * n))
        nums = list(Invoice.objects.values_list('receipt_number', flat=True))
        self.assertEqual(len(set(nums)), n, nums)
        dbs = sorted(Invoice.objects.values_list('debt_before', flat=True))
        self.assertEqual(dbs, [D(600) * i for i in range(n)], 'debt_before doit etre une suite sans doublon')

    def test_plafond_ventes_simultanees_une_seule_passe(self):
        """BP 49 999 (sous le plafond) : deux ventes a credit simultanees. La 1re passe (BP > plafond),
        la 2e doit etre refusee 403 : jamais deux ventes servies avec BP_avant < plafond."""
        Client.objects.filter(pk=self.cl.pk).update(current_debt=D('49999'))
        res, errs = self._race([
            (i, lambda: self._post(self.fa, '', {
                'client': str(self.cl.pk), 'payment_type': 'CREDIT', 'payment_amount': 0,
                'lines': [{'bread_price': self.bp.pk, 'quantity': 1}]})) for i in range(2)
        ])
        self.assertEqual(sorted(res.values()), [201, 403], (res, errs))
        self.assertEqual(self._state(), (D(49999 + 300), 1))


# =============================================================================== N
class Nouveaux(Base):
    """Nouveaux defauts : voir REGISTRE_BUGS.md BUG-664 et suivants."""

    # ------------------------------------------------------------ bread_summary et ajustements
    @expectedFailure
    def test_BUG_664_bread_summary_ajustement_negatif_soustrait(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 10}]).data['id']
        _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        _api(self.g1).post(f'{INV}{iid}/adjust/', {
            'adjustment_sign': -1, 'payment_amount': 0,
            'lines': [{'bread_price': self.bp3.pk, 'quantity': 4}]}, format='json')
        r = _api(self.fa1).get(f'{INV}bread_summary/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['grand_total_qty'], r.data['grand_total_fc']), (6, 1800), r.data)

    # ------------------------------------------------------------ cancel : categorie client
    @expectedFailure
    def test_BUG_665_annulation_rafraichit_la_categorie_client(self):
        Client.objects.filter(pk=self.cl.pk).update(current_debt=D('49000'))
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 10}]).data['id']   # BP 52 000
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.category, 'RISK')
        self.assertEqual(_api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json').status_code, 200)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.current_debt, D('49000'))
        self.assertEqual(self.cl.category, 'NORMAL', 'client reste A RISQUE alors que BP < plafond')

    # ------------------------------------------------------------ compteur de pains
    @expectedFailure
    def test_BUG_666_annulation_apres_ajustement_plus_laisse_le_compteur_incremente(self):
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 2}]).data['id']
        _api(self.g1).post(f'{INV}{iid}/adjust/', {
            'adjustment_sign': 1, 'payment_amount': 0,
            'lines': [{'bread_price': self.bp3.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(_api(self.fa1).post(f'{INV}{iid}/cancel/', {}, format='json').status_code, 200)
        self.cl.refresh_from_db()
        self.assertEqual((self.cl.current_debt, self.sent()), (D(0), 0))
        self.assertEqual(self.cl.total_breads_received, 0, 'aucun pain livre : compteur doit rester a 0')

    @expectedFailure
    def test_BUG_667_livraison_ne_perd_pas_un_increment_concurrent_du_compteur(self):
        """Lecture-modification-ecriture : `Invoice.deliver` fait `client.total_breads_received += n` sur
        l'objet client charge par `_lock` ; une mise a jour validee entre-temps (autre livraison du meme
        client, ajustement) est ecrasee. Simule par une mise a jour inseree apres le chargement."""
        from sales import services
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 4}]).data['id']
        orig_lock = services._lock

        def lock_then_concurrent_commit(pk):
            inv = orig_lock(pk)
            Client.objects.filter(pk=inv.client_id).update(total_breads_received=100)
            return inv

        with patch.object(services, '_lock', lock_then_concurrent_commit):
            r = _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.cl.refresh_from_db()
        self.assertEqual(self.cl.total_breads_received, 104, 'incrementation concurrente ecrasee')

    # ------------------------------------------------------------ dates
    @expectedFailure
    def test_BUG_668_livraison_ne_peut_pas_preceder_la_facture(self):
        cfg = Config.get_instance()
        cfg.allow_backdated_sales = True
        cfg.save()
        iid = self.post().data['id']
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        r = _api(self.lv1).post(f'{INV}{iid}/deliver/', {'delivered_at': yesterday}, format='json')
        inv = Invoice.objects.get(pk=iid)
        self.assertTrue(r.status_code == 400 or timezone.localtime(inv.delivered_at).date() >= inv.invoice_date,
                        f'livree le {inv.delivered_at} pour une facture du {inv.invoice_date}')

    # ------------------------------------------------------------ vente sans client
    @expectedFailure
    def test_BUG_669_vente_sans_client_paiement_superieur_a_la_commande(self):
        r = self.post(client=False, payment_type='CASH', payment_amount=1000000)
        if r.status_code == 201:
            self.assertEqual(r.data['payment_amount'], '3000.00', 'encaissement superieur a la valeur de la commande')
        else:
            self.assertEqual(r.status_code, 400)

    # ------------------------------------------------------------ versement conserve d'une facture Non servi
    @expectedFailure
    def test_BUG_670_daily_summary_compte_le_versement_conserve_non_servi(self):
        iid = self.post(payment_amount=1000).data['id']
        self.assertEqual(_api(self.fa1).post(f'{INV}{iid}/mark-not-served/', {}, format='json').status_code, 200)
        self.assertEqual(Invoice.objects.get(pk=iid).payment_amount, D(1000))
        rows = _api(self.fa1).get(f'{INV}daily_summary/', {'date': timezone.localdate().isoformat()}).data
        cash = sum(D(str(x['total'])) for x in rows if x['payment_type'] == 'CASH')
        self.assertEqual(cash, D(1000), rows)

    @expectedFailure
    def test_BUG_671_deficit_net_du_mois_compte_le_versement_conserve_non_servi(self):
        """BP -100 000 (epargne) ; 70 000 FC commandes puis livres (deficit 70 000 - 17 500 = 52 500 >= plafond,
        BP = -30 000 < plafond). Un versement de 10 000 conserve sur une facture Non servi ramene le deficit
        a 42 500 : une nouvelle commande reglee a credit ne doit plus etre bloquee par le deficit."""
        Client.objects.filter(pk=self.cl.pk).update(current_debt=D('-100000'))
        big = self.post(lines=[{'bread_price': self.bp5.pk, 'quantity': 140}]).data['id']   # 70 000
        _api(self.lv1).post(f'{INV}{big}/deliver/', {}, format='json')
        blocked = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 1}])
        self.assertEqual(blocked.status_code, 403, 'precondition : deficit >= plafond')
        paid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 1}], payment_amount=10000, payment_type='CASH')
        self.assertEqual(paid.status_code, 201, paid.data)
        self.assertEqual(_api(self.fa1).post(f'{INV}{paid.data["id"]}/mark-not-served/', {}, format='json').status_code, 200)
        again = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 1}])
        self.assertEqual(again.status_code, 201, getattr(again, 'data', ''))

    # ------------------------------------------------------------ PATCH commission_exempt et periode close
    @expectedFailure
    def test_BUG_672_patch_commission_exempt_periode_close_avertit(self):
        from commissions.models import CommissionPeriod
        from core.models import SystemNotification
        iid = self.post(lines=[{'bread_price': self.bp3.pk, 'quantity': 10}], payment_amount=3000, payment_type='CASH').data['id']
        _api(self.lv1).post(f'{INV}{iid}/deliver/', {}, format='json')
        today = timezone.localdate()
        CommissionPeriod.objects.create(node=self.n1, month=today.month, year=today.year, is_closed=True,
                                        closed_at=timezone.now())
        before = SystemNotification.objects.count()
        r = _api(self.g1).patch(f'{INV}{iid}/', {'commission_exempt': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertGreater(SystemNotification.objects.count(), before,
                           'periode de commission close modifiee sans avertissement')

    # ------------------------------------------------------------ remboursement et code special
    @expectedFailure
    def test_BUG_673_remboursement_code_special_ne_change_pas_le_resume_du_jour(self):
        """Un remboursement BP n'est ni NS ni RG : un `special_code` envoye ne doit ni etre stocke ni
        modifier la ventilation CASH / CREDIT de daily_summary."""
        def summary():
            rows = _api(self.fa1).get(f'{INV}daily_summary/', {'date': timezone.localdate().isoformat()}).data
            return {x['payment_type']: D(str(x['total'])) for x in rows}
        r = self.post(lines=[], payment_amount=1000, is_debt_repayment=True)
        self.assertEqual(r.status_code, 201, r.data)
        plain = summary()
        Invoice.objects.all().delete()
        r = self.post(lines=[], payment_amount=1000, is_debt_repayment=True, special_code='RG')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(summary(), plain, 'remboursement classe RG : ventilation du jour differente')
