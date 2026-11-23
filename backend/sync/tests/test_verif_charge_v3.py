"""
Testeur charge/resilience, ronde b3 (2026-11-22) : verification independante des
corrections BUG-720 a 736 (sync, commissions) et recherche de nouveaux defauts
(rejeu de lots, lots partiels, ordre, retenue BUG-737 sous regeneration,
fonction SQL KIESE_FOLD, pull).

SQLite : `select_for_update()` sans effet ; la concurrence est SIMULEE de facon
deterministe. Defaut confirme = `@expectedFailure` + ticket BUG-78x.
Donnees fictives uniquement.
"""
import threading
import time
import uuid
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.db import connection, connections
from django.db.models.query import QuerySet
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from clients.models import Client
from clients.search import fold
from commissions.models import ClientCommission, CommissionPeriod
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import ConsumableCount, ConsumableInventory
from sales.models import Invoice, InvoiceLine
from sync.management.commands.sync_now import (
    apply_pull_response, apply_push_response, build_outbound_payload,
)
from sync.models import DebtMovement, NodeAuthToken, SyncBatchLog, SyncConflictLog
from treasury.models import CashbookEntry

URL = '/api/sync/push/'
INV = 'production.ConsumableInventory'
CNT = 'production.ConsumableCount'
D = Decimal


def _api(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    api = APIClient(raise_request_exception=False)
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return api


def _push(api, records, batch_id=None):
    return api.post(URL, {'batch_id': batch_id or str(uuid.uuid4()), 'records': records}, format='json')


def _cl(node='K1', **extra):
    rec = {'id': str(uuid.uuid4()), 'node': node, 'first_name': 'Fictif', 'last_name': 'Client',
           'node_origin': node}
    rec.update(extra)
    return rec


def _st(resp, label, idx=0):
    return resp.data['results'][label][idx]['status']


# ---------------------------------------------------------------- idempotence
class BatchIdempotenceVerif(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.a1, self.a2 = _api(self.k1), _api(self.k2)

    def test_rejeu_identique_replayed_et_zero_doublon(self):
        bid = str(uuid.uuid4())
        recs = {'clients.Client': [_cl()]}
        r1 = _push(self.a1, recs, bid)
        r2 = _push(self.a1, recs, bid)
        self.assertFalse(r1.data['replayed'])
        self.assertTrue(r2.data['replayed'])
        self.assertEqual(r1.data['results'], r2.data['results'])
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(SyncBatchLog.objects.count(), 1)

    def test_empreinte_independante_de_l_ordre_des_cles(self):
        bid = str(uuid.uuid4())
        rec = _cl()
        _push(self.a1, {'clients.Client': [rec]}, bid)
        reordered = dict(reversed(list(rec.items())))
        r = _push(self.a1, {'clients.Client': [reordered]}, bid)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['replayed'])

    def test_meme_batch_id_contenu_different_409_et_rien_applique(self):
        bid = str(uuid.uuid4())
        _push(self.a1, {'clients.Client': [_cl()]}, bid)
        r = _push(self.a1, {'clients.Client': [_cl()]}, bid)
        self.assertEqual(r.status_code, 409)
        self.assertIn('detail', r.json())
        self.assertEqual(Client.objects.count(), 1)

    def test_batch_id_d_un_autre_noeud_ni_fuite_ni_blocage(self):
        bid = str(uuid.uuid4())
        _push(self.a1, {'clients.Client': [_cl('K1')]}, bid)
        r = _push(self.a2, {'clients.Client': [_cl('K2')]}, bid)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['replayed'])
        self.assertEqual(Client.objects.filter(node=self.k2).count(), 1)
        self.assertEqual(SyncBatchLog.objects.count(), 2)

    def test_lot_vide_rejoue_puis_lot_non_vide_meme_id_409(self):
        bid = str(uuid.uuid4())
        self.assertEqual(_push(self.a1, {}, bid).status_code, 200)
        self.assertEqual(_push(self.a1, {'clients.Client': [_cl()]}, bid).status_code, 409)
        self.assertEqual(Client.objects.count(), 0)

    def test_lot_partiel_rejeu_ne_retraite_pas_les_rejets(self):
        # une dependance manquante rejetee est figee dans le lot archive ;
        # un NOUVEAU batch_id (sync_now) la rattrape.
        cid = str(uuid.uuid4())
        inv = {'id': str(uuid.uuid4()), 'node': 'K1', 'client': cid, 'status': 'PENDING',
               'payment_type': 'CASH', 'order_total': '100', 'payment_amount': '100',
               'node_origin': 'K1'}
        bid = str(uuid.uuid4())
        r1 = _push(self.a1, {'sales.Invoice': [inv]}, bid)
        self.assertEqual(_st(r1, 'sales.Invoice'), 'REJECTED')
        _push(self.a1, {'clients.Client': [_cl(id=cid)]})
        r2 = _push(self.a1, {'sales.Invoice': [inv]}, bid)
        self.assertTrue(r2.data['replayed'])
        self.assertEqual(_st(r2, 'sales.Invoice'), 'REJECTED')
        r3 = _push(self.a1, {'sales.Invoice': [inv]})
        self.assertEqual(_st(r3, 'sales.Invoice'), 'ACCEPTED')


class ScopeAndBoundsVerif(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.a1 = _api(self.k1)

    def test_cloture_k2_par_jeton_k1_rejetee_sans_ecriture_livre(self):
        rec = {'id': str(uuid.uuid4()), 'node': 'K2', 'date': '2026-11-20', 'total_entries': '1000',
               'total_expenses': '0', 'is_validated': True, 'node_origin': 'K1'}
        r = _push(self.a1, {'treasury.CashClosure': [rec]})
        self.assertEqual(_st(r, 'treasury.CashClosure'), 'REJECTED')
        self.assertEqual(CashbookEntry.objects.count(), 0)

    def test_node_origin_forge_et_node_absent(self):
        r = _push(self.a1, {'clients.Client': [_cl('K1', node_origin='K2')]})
        self.assertEqual(_st(r, 'clients.Client'), 'REJECTED')
        r = _push(self.a1, {'clients.Client': [dict(_cl('K1'), node=['K2'])]})
        self.assertEqual(_st(r, 'clients.Client'), 'REJECTED')

    def test_dette_hors_plage_rejetee_et_liste_clients_200(self):
        cl = make_client(self.k1)
        for bad in ('9' * 40, '1000000000000', '-1000000000000'):
            r = _push(self.a1, {'sync.DebtMovement': [
                {'id': str(uuid.uuid4()), 'client': str(cl.pk), 'amount': bad, 'kind': 'ORDER'}]})
            self.assertEqual(_st(r, 'sync.DebtMovement'), 'REJECTED', bad)
        api = APIClient(raise_request_exception=False)
        api.force_authenticate(make_user('DIRECTION', node=None, username='v3_dir'))
        self.assertEqual(api.get('/api/clients/clients/').status_code, 200)

    def test_cumul_de_mouvements_ne_depasse_pas_la_borne(self):
        cl = make_client(self.k1)
        ok = _push(self.a1, {'sync.DebtMovement': [
            {'id': str(uuid.uuid4()), 'client': str(cl.pk), 'amount': '999999999999', 'kind': 'ORDER'}]})
        self.assertEqual(_st(ok, 'sync.DebtMovement'), 'ACCEPTED')
        over = _push(self.a1, {'sync.DebtMovement': [
            {'id': str(uuid.uuid4()), 'client': str(cl.pk), 'amount': '999999999999', 'kind': 'ORDER'}]})
        self.assertEqual(_st(over, 'sync.DebtMovement'), 'REJECTED')
        api = APIClient(raise_request_exception=False)
        api.force_authenticate(make_user('DIRECTION', node=None, username='v3_dir2'))
        self.assertEqual(api.get('/api/clients/clients/').status_code, 200)

    def test_lot_hostile_sans_500(self):
        for bad in ('abc', {'a': 1}, 12, True, [None], [1], ['x'], [[1]]):
            r = _push(self.a1, {'clients.Client': bad})
            self.assertLess(r.status_code, 500, repr(bad))

    def test_occurrences_conflit_dedoublonne(self):
        k2 = make_node(code='K2b')
        foreign = make_client(k2)
        for _ in range(5):
            _push(self.a1, {'clients.Client': [_cl('K1', id=str(foreign.pk))]})
        qs = SyncConflictLog.objects.filter(node=self.k1, object_id=str(foreign.pk))
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().occurrences, 5)

    def test_dette_ouverture_conservee(self):
        cl = make_client(self.k1, current_debt=D('20000'))
        _push(self.a1, {'sync.DebtMovement': [
            {'id': str(uuid.uuid4()), 'client': str(cl.pk), 'amount': '1000', 'kind': 'ORDER'}]})
        cl.refresh_from_db()
        self.assertEqual(cl.current_debt, D('21000.00'))

    def test_mouvement_rejoue_montant_different_rejete(self):
        cl = make_client(self.k1)
        mid = str(uuid.uuid4())
        _push(self.a1, {'sync.DebtMovement': [{'id': mid, 'client': str(cl.pk), 'amount': '500', 'kind': 'ORDER'}]})
        r = _push(self.a1, {'sync.DebtMovement': [{'id': mid, 'client': str(cl.pk), 'amount': '900', 'kind': 'ORDER'}]})
        self.assertEqual(_st(r, 'sync.DebtMovement'), 'REJECTED')
        cl.refresh_from_db()
        self.assertEqual(cl.current_debt, D('500.00'))


# --------------------------------------------------------- inventaire consommables
class ConsumableInventoryVerif(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.api = _api(self.k1)
        self.iid = str(uuid.uuid4())
        self.inv = {'id': self.iid, 'node': 'K1', 'inventory_date': '2026-11-20', 'comment': 'RAS', 'node_origin': 'K1'}

    def _line(self, **kw):
        rec = {'node': 'K1', 'inventory': self.iid, 'consumable_type': 'FARINE', 'count_date': '2026-11-20',
               'system_quantity': '10.000', 'physical_quantity': '9.500', 'gap': '-0.500', 'notes': ''}
        rec.update(kw)
        return rec

    def test_inventaire_et_ligne_acceptes_rejeu_sans_doublon(self):
        recs = {INV: [self.inv], CNT: [self._line()]}
        _push(self.api, recs)
        _push(self.api, recs)
        self.assertEqual(ConsumableInventory.objects.count(), 1)
        self.assertEqual(ConsumableCount.objects.count(), 1)

    def test_deux_valeurs_meme_type_rejet_et_conflit(self):
        _push(self.api, {INV: [self.inv], CNT: [self._line()]})
        r = _push(self.api, {CNT: [self._line(physical_quantity='1.000', gap='-9.000')]})
        self.assertEqual(_st(r, CNT), 'REJECTED')
        self.assertEqual(ConsumableCount.objects.count(), 1)

    def test_ligne_rejetee_par_le_handler_porte_inventory(self):
        _push(self.api, {INV: [self.inv]})
        r = _push(self.api, {CNT: [self._line(gap='5.000')]})
        res = r.data['results'][CNT][0]
        self.assertEqual(res['status'], 'REJECTED')
        self.assertEqual(res.get('inventory'), self.iid)

    def test_cycle_sortant_ligne_rejetee_garde_inventaire_non_synchronise(self):
        # Cycle complet via le lot sortant reel : ligne a ecart incoherent.
        ConsumableInventory.objects.create(id=self.iid, node=self.k1, node_origin='K1',
                                           inventory_date='2026-11-20', comment='x')
        ConsumableCount.objects.create(node=self.k1, inventory_id=self.iid, consumable_type='FARINE',
                                       count_date='2026-11-20', system_quantity=D('10'),
                                       physical_quantity=D('9'), gap=D('-1'))
        payload = build_outbound_payload('K1')
        r = self.api.post(URL, payload, format='json')
        apply_push_response(r.json())
        self.assertTrue(ConsumableInventory.objects.get(pk=self.iid).is_synced)  # tout accepte

    # BUG-731 (reouvert) : corrige (dev-backend d6), marque retiree
    def test_ligne_rejetee_avant_handler_ne_perd_pas_l_inventaire(self):
        """Rejet au controle commun (preflight) : la ligne doit encore bloquer l'inventaire."""
        ConsumableInventory.objects.create(id=self.iid, node=self.k1, node_origin='K1',
                                           inventory_date='2026-11-20', comment='x')
        ConsumableCount.objects.create(node=self.k1, inventory_id=self.iid, consumable_type='FARINE',
                                       count_date='2026-11-20', system_quantity=D('10'),
                                       physical_quantity=D('9'), gap=D('-1'),
                                       notes='n' * 10_500)  # TextField local non borne
        payload = build_outbound_payload('K1')
        r = self.api.post(URL, payload, format='json')
        res = r.json()['results'][CNT][0]
        self.assertEqual(res['status'], 'REJECTED', res)
        apply_push_response(r.json())
        self.assertFalse(ConsumableInventory.objects.get(pk=self.iid).is_synced,
                         f"inventaire marque synchronise malgre ligne rejetee : {res}")


# ---------------------------------------------------------------- pull / reponses
class PullVerif(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.api = _api(self.k1)

    # BUG-781 : corrige (dev-backend d6), marque retiree
    def test_apply_pull_response_malforme_ne_leve_pas(self):
        for bad in ({'clients': [{'status': 'x'}]}, {'clients': 'abc'}, {'clients': [None]},
                    {'clients': [{'id': 'pas-uuid', 'current_debt': '1', 'category': 'x'}]},
                    {'clients': [{'id': str(uuid.uuid4()), 'current_debt': 'NaN', 'category': 'x'}]}):
            try:
                apply_pull_response(bad)
            except Exception as exc:  # noqa: BLE001
                self.fail(f"apply_pull_response({bad!r}) a leve {type(exc).__name__}")

    # BUG-780 : corrige (dev-backend d6), marque retiree
    def test_pull_ecrase_dette_locale_non_poussee(self):
        """Mouvement local pas encore pousse : la valeur Cloud (sans lui) ecrase la dette locale."""
        cl = make_client(self.k1, current_debt=D('1000'))
        payload = {'clients': [{'id': str(cl.pk), 'current_debt': '1000.00', 'category': cl.category}]}
        # facturation locale pendant le cycle : +500 (mouvement non synchronise)
        Client.objects.filter(pk=cl.pk).update(current_debt=D('1500'))
        DebtMovement.objects.create(client=cl, amount=D('500'), kind='ORDER', node_origin='K1', is_synced=False)
        apply_pull_response(payload)
        cl.refresh_from_db()
        self.assertEqual(cl.current_debt, D('1500.00'), "dette locale en attente de push ecrasee par le pull")

    def test_pull_volumetrie_5000_clients(self):
        Client.objects.bulk_create([Client(code=f'K1-V{i:05d}', first_name=f'P{i}', last_name='N',
                                           node=self.k1, node_origin='K1') for i in range(5000)], batch_size=500)
        with CaptureQueriesContext(connection) as ctx:
            t0 = time.perf_counter()
            r = self.api.get('/api/sync/pull/')
            dt = (time.perf_counter() - t0) * 1000
        self.assertEqual(r.status_code, 200)
        print(f"PERF pull 5000 clients: {len(ctx)} requetes, {dt:.0f} ms, {len(r.content) / 1024:.0f} Ko")
        self.assertLessEqual(len(ctx), 20)
        # curseur : second pull incremental vide
        since = r.json()['since_client_debt']
        r2 = self.api.get('/api/sync/pull/', {'since_client_debt': since})
        self.assertEqual(len(r2.json()['clients']), 0)

    # BUG-781 : corrige (dev-backend d6), marque retiree
    def test_pull_curseur_hostile_sans_500(self):
        for bad in ('abc', '2026-13-45', 'x' * 5000, '9999-99-99T00:00:00'):
            r = self.api.get('/api/sync/pull/', {'since_client_debt': bad, 'since_config': bad})
            self.assertLess(r.status_code, 500, bad[:20])


# ----------------------------------------------------------- commissions (737/735/736)
class CommissionsVerif(TestCase):
    def setUp(self):
        self.n1 = make_node(code='V1', social=D('1000'), card_fee=D('1000'))
        self.n3 = make_node(code='V3', social=D('1500'), card_fee=D('700'))
        self.p500 = make_bread_price('GRAND', 'Pain 500 FC', 500)
        self.hq = make_user('DIRECTION', node=None, team='', username='v3_hq')
        self.api = APIClient(raise_request_exception=True)
        self.api.force_authenticate(self.hq)
        self.c = make_client(self.n3, current_debt=D('10000'))
        for n in (self.n3, self.n1):
            inv = Invoice.objects.create(node=n, client=self.c, payment_type='CREDIT', status='DELIVERED',
                                         payment_amount=D('0'), invoice_date='2026-02-10', node_origin=n.code)
            InvoiceLine.objects.create(invoice=inv, bread_price=self.p500, quantity=100)
            inv.compute_order_total()
            inv.save(update_fields=['order_total'])

    def gen(self, node):
        r = self.api.post('/api/commissions/periods/generate/',
                          {'node': node.pk, 'month': 2, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'content', b'')[:200])

    def totals(self):
        rows = ClientCommission.objects.filter(client=self.c)
        return (sum(r.deduction_debt for r in rows), sum(r.deduction_social for r in rows))

    def test_regenerations_repetees_dans_les_deux_ordres_gardent_une_seule_retenue(self):
        for order in ((self.n3, self.n1), (self.n1, self.n3)):
            ClientCommission.objects.all().delete()
            CommissionPeriod.objects.all().delete()
            for _ in range(3):
                for n in order:
                    self.gen(n)
            self.assertEqual(self.totals(), (D('10000.00'), D('1500.00')), [n.code for n in order])

    def test_retenue_tombe_sur_la_premiere_generee_meme_si_non_rattachement(self):
        self.gen(self.n1)
        self.gen(self.n3)
        row1 = ClientCommission.objects.get(period__node=self.n1, client=self.c)
        self.assertEqual(row1.deduction_debt, D('10000.00'))

    def test_suppression_de_la_ligne_retenante_puis_regeneration(self):
        self.gen(self.n3)
        self.gen(self.n1)
        ClientCommission.objects.get(period__node=self.n3, client=self.c).delete()
        self.gen(self.n3)  # n1 existe : retenue 0 sur n3, la dette n'est plus retenue nulle part ?
        self.gen(self.n1)
        self.assertEqual(self.totals()[0], D('10000.00'),
                         "apres suppression de la ligne retenante, la dette n'est plus retenue du tout")

    # BUG-782 : corrige (dev-backend d6), marque retiree
    def test_course_generate_deux_boulangeries_double_retenue(self):
        """Interleaving : la generation V1 s'execute entre le controle deja_retenu et la creation de V3."""
        mgr_cls = type(ClientCommission.objects)
        real = mgr_cls.get_or_create
        state = {'nested': False}

        def interleaved(mgr, *a, **kw):
            if (mgr.model is ClientCommission and not state['nested'] and kw.get('period') is not None
                    and kw['period'].node_id == self.n3.pk):
                state['nested'] = True
                self.gen(self.n1)
            return real(mgr, *a, **kw)

        with patch.object(mgr_cls, 'get_or_create', interleaved):
            self.gen(self.n3)
        self.assertEqual(self.totals(), (D('10000.00'), D('1500.00')))

    def test_mark_paid_double_et_set_manuel_apres_paiement(self):
        self.gen(self.n3)
        cm = ClientCommission.objects.get(period__node=self.n3)
        url = f'/api/commissions/commissions/{cm.pk}'
        self.assertEqual(self.api.post(url + '/mark_paid/', {}, format='json').status_code, 200)
        self.assertEqual(self.api.post(url + '/mark_paid/', {}, format='json').status_code, 400)
        r = self.api.patch(url + '/set_manuel/', {'manuel_adjustment': '5'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_mark_paid_emet_un_verrou(self):
        self.gen(self.n3)
        cm = ClientCommission.objects.get(period__node=self.n3)
        calls = []
        orig = QuerySet.select_for_update

        def spy(qs, *a, **kw):
            calls.append(qs.model.__name__)
            return orig(qs, *a, **kw)

        with patch.object(QuerySet, 'select_for_update', spy):
            self.api.post(f'/api/commissions/commissions/{cm.pk}/mark_paid/', {}, format='json')
        self.assertIn('ClientCommission', calls)

    def test_generate_parametres_invalides_400(self):
        for body in ({'node': self.n1.pk, 'month': 13, 'year': 2026}, {'node': self.n1.pk, 'month': 'x', 'year': 2026},
                     {'node': [1], 'month': 2, 'year': 2026}, {'node': self.n1.pk, 'month': True, 'year': 2026},
                     {'node': self.n1.pk, 'month': 2.5, 'year': 2026}, {'node': self.n1.pk, 'month': 2, 'year': 1e9},
                     {'node': 10**30, 'month': 2, 'year': 2026}, {'node': self.n1.pk, 'month': '1e1', 'year': 2026}):
            r = self.api.post('/api/commissions/periods/generate/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code))


# ----------------------------------------------------------------- KIESE_FOLD
class FoldVerif(TestCase):
    def test_fold_cas_limites(self):
        self.assertEqual(fold('ÉLODIE'), 'elodie')
        self.assertEqual(fold('Élodie'), fold('Élodie'))  # NFC = NFD
        self.assertIsNone(fold(None))
        self.assertEqual(fold(''), '')
        self.assertEqual(fold('Straße'), 'strasse')
        fold('İstanbul')
        fold('\x00')
        fold('x' * 100_000)

    def test_fonction_sql_sur_null_et_types_non_texte(self):
        with connection.cursor() as cur:
            cur.execute("SELECT KIESE_FOLD(NULL), KIESE_FOLD(12), KIESE_FOLD(x'41')")
            row = cur.fetchone()
        self.assertIsNone(row[0])
        self.assertEqual(row[1], '12')

    def test_recherche_5000_clients_accents_nombre_requetes_et_temps(self):
        k1 = make_node(code='K1')
        Client.objects.bulk_create([Client(code=f'K1-F{i:05d}', first_name='Élodie' if i % 50 == 0 else f'P{i}',
                                           last_name=f'N{i % 40}', node=k1, node_origin='K1')
                                    for i in range(5000)], batch_size=500)
        api = APIClient(raise_request_exception=False)
        api.force_authenticate(make_user('FACTURIER', node=k1, username='v3_fac'))
        api.get('/api/clients/clients/', {'search': 'elodie'})
        times = []
        for term in ('ELODIE', 'élodie', 'Élodie', 'elo', 'N7'):
            with CaptureQueriesContext(connection) as ctx:
                t0 = time.perf_counter()
                r = api.get('/api/clients/clients/', {'search': term})
                times.append((time.perf_counter() - t0) * 1000)
            self.assertEqual(r.status_code, 200, term)
            self.assertLessEqual(len(ctx), 5, term)
            if term in ('ELODIE', 'élodie', 'Élodie'):
                self.assertEqual(r.json()['count'], 100, term)
        print('PERF recherche 5000 clients (ms): ' + ', '.join(f'{t:.0f}' for t in times))
        self.assertLess(sorted(times)[-1], 1500)


class FoldThreadVerif(TransactionTestCase):
    def test_connexion_de_thread_a_la_fonction_enregistree(self):
        out = {}

        def work():
            try:
                with connection.cursor() as cur:
                    cur.execute("SELECT KIESE_FOLD('ÉÀ')")
                    out['v'] = cur.fetchone()[0]
            except Exception as exc:  # noqa: BLE001
                out['err'] = repr(exc)
            finally:
                connections.close_all()

        t = threading.Thread(target=work)
        t.start()
        t.join(20)
        self.assertEqual(out.get('v'), 'ea', out)


class PullCursorUsageVerif(TestCase):
    # BUG-784 : corrige (dev-backend d6), marque retiree
    def test_le_poste_desktop_envoie_le_curseur_au_pull_suivant(self):
        import logging
        from unittest.mock import MagicMock
        from sync import desktop_client

        resp = MagicMock(status_code=200)
        resp.json.return_value = {'clients': [], 'since_client_debt': '2026-11-22T10:00:00+00:00',
                                  'since_config': '2026-11-22T10:00:00+00:00'}
        with patch.object(desktop_client.requests, 'get', return_value=resp) as g:
            desktop_client._pull_only(logging.getLogger('t'), 'http://cloud', {})
            desktop_client._pull_only(logging.getLogger('t'), 'http://cloud', {})
        second = g.call_args_list[1]
        self.assertIn('since_client_debt', (second.kwargs.get('params') or {}),
                      "le 2e pull redemande TOUS les clients (curseur jamais envoye)")
