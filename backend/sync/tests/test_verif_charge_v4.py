"""
Testeur charge/resilience, ronde b4 (2026-11-22) : verification independante de
BUG-731, 780, 781, 782, 784 (corriges en d6) et recherche de nouveaux defauts
de synchronisation (curseur, portee de noeud, bordereaux). Donnees fictives.
Defaut confirme = `@expectedFailure` + ticket BUG-785+.
"""
import json
import logging
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from unittest import expectedFailure
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from commissions.models import ClientCommission
from core.models import Node
from core.testing import make_bread_price, make_client, make_node, make_user
from production.models import (
    BreadTransfer, BreadTransferLine, ConsumableCount, ConsumableInventory,
    ConsumableMovement, ConsumableStock,
)
from sales.models import Invoice, InvoiceLine
from sync import desktop_client
from sync.management.commands.sync_now import (
    apply_pull_response, apply_push_response, build_outbound_payload,
)
from sync.models import DebtMovement, NodeAuthToken
from treasury.models import CashbookEntry, DisbursementVoucher
from treasury.views import append_cashbook_entry

URL = '/api/sync/push/'
D = Decimal
LOG = logging.getLogger('verif_v4')
CLOUD = 'http://cloud.test'


def _api(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    api = APIClient(raise_request_exception=False)
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return api, raw


def _push(api, records):
    return api.post(URL, {'batch_id': str(uuid.uuid4()), 'records': records}, format='json')


def _bridge(api):
    """requests.get(...) -> APIClient (le Cloud simule dans la meme base)."""
    calls = []

    def fake_get(url, headers=None, timeout=None, params=None):
        calls.append(dict(params or {}))
        r = api.get('/api/sync/pull/', dict(params or {}))
        m = MagicMock(status_code=r.status_code)
        m.json.return_value = r.json() if r.status_code < 500 else {}
        m.text = r.content.decode()[:200]
        return m
    return fake_get, calls


# ------------------------------------------------------------ curseur (784)
class CurseurVerif(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.api, self.raw = _api(self.k1)
        self.tmp = tempfile.mkdtemp()
        desktop_client._PULL_CURSORS.clear()
        self.addCleanup(desktop_client._PULL_CURSORS.clear)
        make_client(self.k1)

    def _pull(self, data_dir=None, url=CLOUD, api=None, node_code=None):
        fake, calls = _bridge(api or self.api)
        with patch.object(desktop_client.requests, 'get', fake):
            desktop_client._pull_only(LOG, url, {}, data_dir or self.tmp, node_code)
        return calls

    def test_curseur_persiste_sur_disque_survit_au_redemarrage(self):
        self._pull()
        self.assertTrue((Path(self.tmp) / 'sync_pull_cursor.json').exists())
        desktop_client._PULL_CURSORS.clear()  # redemarrage du processus
        calls = self._pull()
        self.assertIn('since_client_debt', calls[0])

    def test_changement_d_url_cloud_repart_en_pull_complet(self):
        self._pull(url='http://cloud-a.test')
        desktop_client._PULL_CURSORS.clear()
        calls = self._pull(url='http://cloud-b.test')
        self.assertEqual(calls[0], {})

    def test_curseur_n_avance_pas_si_application_echoue(self):
        self._pull()
        before = desktop_client.load_pull_cursor(self.tmp, CLOUD)
        fake, _ = _bridge(self.api)
        with patch.object(desktop_client.requests, 'get', fake), \
                patch('sync.management.commands.sync_now.apply_pull_response', side_effect=RuntimeError('x')):
            with self.assertRaises(RuntimeError):
                desktop_client._pull_only(LOG, CLOUD, {}, self.tmp)
        self.assertEqual(desktop_client.load_pull_cursor(self.tmp, CLOUD), before)

    def test_curseur_n_avance_pas_sur_400_ni_503_ni_reseau(self):
        self._pull()
        before = desktop_client.load_pull_cursor(self.tmp, CLOUD)
        for code in (400, 403, 503):
            m = MagicMock(status_code=code)
            m.text = ''
            with patch.object(desktop_client.requests, 'get', return_value=m):
                desktop_client._pull_only(LOG, CLOUD, {}, self.tmp)
        with patch.object(desktop_client.requests, 'get',
                          side_effect=desktop_client.requests.ConnectionError('coupure')):
            desktop_client._pull_only(LOG, CLOUD, {}, self.tmp)
        self.assertEqual(desktop_client.load_pull_cursor(self.tmp, CLOUD), before)

    def test_fichier_curseur_illisible_ou_hostile_donne_pull_complet_sans_exception(self):
        path = Path(self.tmp) / 'sync_pull_cursor.json'
        for content in ('', '{', '[]', 'null', '{"cloud_url": 5}', '\x00\xff', json.dumps({'cloud_url': CLOUD, 'since_client_debt': 12})):
            desktop_client._PULL_CURSORS.clear()
            path.write_text(content, encoding='utf-8', errors='ignore') if content != '\x00\xff' else path.write_bytes(b'\x00\xff')
            self.assertEqual(desktop_client.load_pull_cursor(self.tmp, CLOUD), {}, repr(content))

    def test_repertoire_de_donnees_absent_pas_d_exception(self):
        desktop_client.save_pull_cursor('/chemin/inexistant/zz', CLOUD,
                                        {'since_client_debt': '2026-11-22T10:00:00+00:00'})
        self.assertIn('since_client_debt', desktop_client.load_pull_cursor('/chemin/inexistant/zz', CLOUD))

    # --- nouveaux defauts
    def test_curseur_garbage_dans_le_fichier_se_repare(self):
        """Valeur textuelle non date dans le fichier : le serveur repond 400 a chaque cycle, pour toujours."""
        Path(self.tmp, 'sync_pull_cursor.json').write_text(
            json.dumps({'cloud_url': CLOUD, 'since_client_debt': 'corrompu', 'since_config': 'corrompu'}),
            encoding='utf-8')
        self._pull()
        calls = self._pull()  # le 2e cycle devrait avoir reparti de zero
        self.assertNotEqual(calls[0].get('since_client_debt'), 'corrompu',
                            "curseur corrompu renvoye indefiniment (400 a chaque cycle)")

    def test_curseur_dans_le_futur_ne_masque_pas_les_clients(self):
        """Cloud restaure d'une sauvegarde ou horloge deregleee : curseur > horloge Cloud => 0 client a jamais."""
        r = self.api.get('/api/sync/pull/', {'since_client_debt': '2999-01-01T00:00:00+00:00'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()['clients']), 1, "client jamais livre : curseur futur accepte tel quel")

    def test_curseur_lie_au_noeud_pas_seulement_a_l_url(self):
        """Poste reconfigure pour une autre boulangerie, meme URL Cloud : curseur de K1 reutilise par K2."""
        self._pull(node_code='K1')  # curseur K1 enregistre
        self.assertIn('since_client_debt', self._pull(node_code='K1')[0])  # K1 le reutilise
        k2 = make_node(code='K2')
        api2, _ = _api(k2)
        make_client(k2)  # client K2 modifie AVANT le curseur K1
        Client.objects.filter(node=k2).update(updated_at='2020-01-01T00:00:00Z')
        calls = self._pull(api=api2, node_code='K2')
        self.assertEqual(calls[0], {}, "K2 envoie le curseur de K1 : ses clients anciens ne descendront jamais")


# ----------------------------------------------- 780/781 : application du pull
class PullApplyVerif(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')

    def test_780_seul_le_client_avec_mouvement_non_pousse_est_ignore(self):
        a = make_client(self.k1, current_debt=D('1500'))
        b = make_client(self.k1, current_debt=D('100'))
        DebtMovement.objects.create(client=a, amount=D('500'), kind='ORDER', node_origin='K1', is_synced=False)
        apply_pull_response({'clients': [
            {'id': str(a.pk), 'current_debt': '1000.00', 'category': a.category},
            {'id': str(b.pk), 'current_debt': '700.00', 'category': b.category}]})
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((a.current_debt, b.current_debt), (D('1500.00'), D('700.00')))

    def test_780_apres_synchronisation_du_mouvement_la_valeur_cloud_s_applique(self):
        a = make_client(self.k1, current_debt=D('1500'))
        mv = DebtMovement.objects.create(client=a, amount=D('500'), kind='ORDER', node_origin='K1', is_synced=False)
        DebtMovement.objects.filter(pk=mv.pk).update(is_synced=True)
        apply_pull_response({'clients': [{'id': str(a.pk), 'current_debt': '1500.00', 'category': a.category}]})
        a.refresh_from_db()
        self.assertEqual(a.current_debt, D('1500.00'))

    def test_781_formes_hostiles_aucune_exception_et_rien_ecrit(self):
        a = make_client(self.k1, current_debt=D('10'))
        bad = [None, 5, 'x', [], {}, {'clients': None}, {'clients': {'id': 1}}, {'clients': [[], 1, None, 'x']},
               {'clients': [{'id': str(a.pk), 'current_debt': True, 'category': a.category}]},
               {'clients': [{'id': str(a.pk), 'current_debt': None, 'category': a.category}]},
               {'clients': [{'id': str(a.pk), 'current_debt': 'Infinity', 'category': a.category}]},
               {'clients': [{'id': str(a.pk), 'current_debt': '1e999', 'category': a.category}]},
               {'clients': [{'id': str(a.pk), 'current_debt': '10', 'category': 'INCONNUE'}]},
               {'clients': [{'id': str(a.pk), 'current_debt': ['1'], 'category': a.category}]},
               {'clients': [{'id': str(a.pk), 'current_debt': {'x': 1}, 'category': a.category}]},
               {'clients': [{'id': str(a.pk), 'current_debt': '10', 'category': ['x']}]}]
        for payload in bad:
            try:
                apply_pull_response(payload)
            except Exception as exc:  # noqa: BLE001
                self.fail(f'{payload!r} -> {type(exc).__name__}: {exc}')
        a.refresh_from_db()
        self.assertEqual(a.current_debt, D('10.00'))

    def test_781_curseurs_hostiles_cote_serveur(self):
        api, _ = _api(self.k1)
        for bad in ('9999-99-99T00:00:00', '0000-00-00', '2026-11-22T25:61:61', 'x' * 65, '\x00', '-1', '1e9',
                    '9999-12-31T23:59:59.999999+99:99', '0001-01-01T00:00:00-23:59'):
            r = api.get('/api/sync/pull/', {'since_client_debt': bad})
            self.assertLess(r.status_code, 500, bad[:30])

    def test_pull_ne_fuit_pas_les_clients_d_une_autre_boulangerie(self):
        k2 = make_node(code='K2')
        other = make_client(k2)
        mine = make_client(self.k1)
        api, _ = _api(self.k1)
        ids = {c['id'] for c in api.get('/api/sync/pull/').json()['clients']}
        self.assertIn(str(mine.pk), ids)
        self.assertNotIn(str(other.pk), ids)

    def test_cloud_recalcul_de_dette_fait_avancer_updated_at(self):
        """Apres push d'un mouvement, le Cloud change `current_debt` : le curseur incremental doit le voir."""
        api, _ = _api(self.k1)
        c = make_client(self.k1)
        first = api.get('/api/sync/pull/').json()
        since = first['since_client_debt']
        mv = {'id': str(uuid.uuid4()), 'client': str(c.pk), 'amount': '700.00', 'kind': 'ORDER', 'node_origin': 'K1'}
        r = _push(api, {'sync.DebtMovement': [mv]})
        self.assertEqual(r.data['results']['sync.DebtMovement'][0]['status'], 'ACCEPTED')
        c.refresh_from_db()
        self.assertEqual(c.current_debt, D('700.00'))
        second = api.get('/api/sync/pull/', {'since_client_debt': since}).json()
        self.assertEqual([x['current_debt'] for x in second['clients']], ['700.00'],
                         "dette changee au Cloud mais updated_at inchange : jamais redescendue en incremental")


# ------------------------------------------------------------- 731 inventaire
class InventaireVerif(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.api, _ = _api(self.k1)
        self.iid = uuid.uuid4()
        ConsumableInventory.objects.create(id=self.iid, node=self.k1, node_origin='K1',
                                           inventory_date='2026-11-20', comment='x')

    def _cycle(self, **count_kw):
        kw = dict(node=self.k1, inventory_id=self.iid, consumable_type='FARINE', count_date='2026-11-20',
                  system_quantity=D('10'), physical_quantity=D('9'), gap=D('-1'))
        kw.update(count_kw)
        ConsumableCount.objects.create(**kw)
        payload = build_outbound_payload('K1')
        r = self.api.post(URL, payload, format='json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        apply_push_response(r.json())
        return r.json()['results']['production.ConsumableCount'][0]

    def test_rejet_preflight_notes_geantes_inventaire_reste_non_synchronise(self):
        res = self._cycle(notes='n' * 10_500)
        self.assertEqual(res['status'], 'REJECTED')
        self.assertEqual(res.get('inventory'), str(self.iid))
        self.assertFalse(ConsumableInventory.objects.get(pk=self.iid).is_synced)

    def test_rejet_gap_incoherent_inventaire_reste_non_synchronise(self):
        res = self._cycle(gap=D('5'))
        self.assertEqual(res['status'], 'REJECTED')
        self.assertFalse(ConsumableInventory.objects.get(pk=self.iid).is_synced)

    def test_ligne_acceptee_inventaire_synchronise(self):
        res = self._cycle()
        self.assertEqual(res['status'], 'ACCEPTED', res)
        self.assertTrue(ConsumableInventory.objects.get(pk=self.iid).is_synced)

    def test_inventory_non_uuid_dans_resultat_ne_leve_pas(self):
        apply_push_response({'results': {'production.ConsumableCount': [
            {'id': 'x', 'status': 'REJECTED', 'inventory': {'a': 1}},
            {'id': None, 'status': 'REJECTED', 'inventory': 12}, None, 'x'],
            'production.ConsumableInventory': [{'id': str(self.iid), 'status': 'ACCEPTED'}]}})
        self.assertTrue(ConsumableInventory.objects.get(pk=self.iid).is_synced)

    def test_reponse_push_tronquee_ne_marque_rien(self):
        for bad in (None, [], 'x', {}, {'results': None}, {'results': []}, {'results': {'clients.Client': 'x'}},
                    {'results': {'clients.Client': [{'status': 'ACCEPTED'}]}}):
            apply_push_response(bad)
        self.assertFalse(ConsumableInventory.objects.get(pk=self.iid).is_synced)


# --------------------------------------------------------- 782 : 3 en course
class RetenueTroisBoulangeriesVerif(TestCase):
    def setUp(self):
        self.ns = [make_node(code=c, social=D('1500'), card_fee=D('700')) for c in ('V1', 'V2', 'V3')]
        self.p = make_bread_price('GRAND', 'Pain 500 FC', 500)
        self.api = APIClient(raise_request_exception=True)
        self.api.force_authenticate(make_user('DIRECTION', node=None, team='', username='v4_hq'))
        self.c = make_client(self.ns[2], current_debt=D('10000'))
        for n in self.ns:
            inv = Invoice.objects.create(node=n, client=self.c, payment_type='CREDIT', status='DELIVERED',
                                         payment_amount=D('0'), invoice_date='2026-02-10', node_origin=n.code)
            InvoiceLine.objects.create(invoice=inv, bread_price=self.p, quantity=100)
            inv.compute_order_total()
            inv.save(update_fields=['order_total'])

    def gen(self, node):
        r = self.api.post('/api/commissions/periods/generate/', {'node': node.pk, 'month': 2, 'year': 2026},
                          format='json')
        self.assertEqual(r.status_code, 201)

    def test_imbrication_a_trois_une_seule_retenue(self):
        mgr_cls = type(ClientCommission.objects)
        real = mgr_cls.get_or_create
        done = set()

        def interleaved(mgr, *a, **kw):
            if mgr.model is ClientCommission and kw.get('period') is not None:
                node_id = kw['period'].node_id
                if node_id == self.ns[2].pk and 'a' not in done:
                    done.add('a')
                    self.gen(self.ns[0])
                elif node_id == self.ns[0].pk and 'b' not in done and 'a' in done:
                    done.add('b')
                    self.gen(self.ns[1])
            return real(mgr, *a, **kw)

        with patch.object(mgr_cls, 'get_or_create', interleaved):
            self.gen(self.ns[2])
        rows = ClientCommission.objects.filter(client=self.c)
        self.assertEqual(rows.count(), 3)
        self.assertEqual((sum(r.deduction_debt for r in rows), sum(r.deduction_social for r in rows)),
                         (D('10000.00'), D('1500.00')))


# ---------------------------------------------- portee de noeud (nouveaux tests)
class PorteeVerif(TestCase):
    def setUp(self):
        self.k1, self.k2, self.k3 = (make_node(code=c) for c in ('K1', 'K2', 'K3'))
        self.a1, _ = _api(self.k1)
        self.a2, _ = _api(self.k2)
        self.a3, _ = _api(self.k3)

    def test_mouvement_consommable_d_une_autre_boulangerie_rejete(self):
        mv = {'id': str(uuid.uuid4()), 'node': 'K2', 'consumable_type': 'FARINE', 'movement_type': 'ENTRY',
              'quantity': '50.000', 'unit_price': '1000', 'unit': 'sac', 'node_origin': 'K2'}
        r = _push(self.a1, {'production.ConsumableMovement': [mv]})  # jeton K1, stock K2
        self.assertEqual(r.data['results']['production.ConsumableMovement'][0]['status'], 'REJECTED')
        self.assertFalse(ConsumableMovement.objects.filter(pk=mv['id']).exists())
        self.assertFalse(ConsumableStock.objects.filter(node=self.k2).exists())

    def test_transfert_entre_deux_autres_boulangeries_rejete(self):
        bp = make_bread_price('GRAND', 'Pain 500 FC', 500)
        t = {'id': str(uuid.uuid4()), 'from_node': 'K2', 'to_node': 'K3', 'bread_price': bp.pk,
             'quantity_sent': 500, 'transfer_status': 'PENDING', 'node_origin': 'K2'}
        r = _push(self.a1, {'production.BreadTransfer': [t]})  # jeton K1 etranger au transfert
        self.assertEqual(r.data['results']['production.BreadTransfer'][0]['status'], 'REJECTED')
        self.assertFalse(BreadTransfer.objects.filter(pk=t['id']).exists())

    def test_ligne_de_transfert_existante_modifiee_par_un_noeud_tiers(self):
        bp = make_bread_price('GRAND', 'Pain 500 FC', 500)
        t = BreadTransfer.objects.create(from_node=self.k1, to_node=self.k2, bread_price=bp,
                                         quantity_sent=100, node_origin='K1')
        line = BreadTransferLine.objects.create(transfer=t, bread_price=bp, quantity_sent=100)
        r = _push(self.a3, {'production.BreadTransferLine': [
            {'id': str(line.pk), 'transfer': str(t.pk), 'bread_price': bp.pk, 'quantity_sent': 100,
             'quantity_received': 1}]})  # jeton K3, transfert K1->K2
        line.refresh_from_db()
        self.assertIsNone(line.quantity_received, f"modifie par K3 : {r.data}")

    def test_transfert_connu_modifie_par_un_tiers_rejete(self):
        bp = make_bread_price('GRAND', 'Pain 500 FC', 500)
        t = BreadTransfer.objects.create(from_node=self.k1, to_node=self.k2, bread_price=bp,
                                         quantity_sent=100, node_origin='K1')
        r = _push(self.a3, {'production.BreadTransfer': [{'id': str(t.pk), 'transfer_status': 'CANCELLED'}]})
        self.assertEqual(r.data['results']['production.BreadTransfer'][0]['status'], 'REJECTED')

    def _siege_funded(self, amount=D('500000')):
        siege = Node.objects.get(code='SIEGE')
        append_cashbook_entry(node=siege, date='2026-11-20', piece_number='TST-1', imputation='ENTREE',
                              label='Fonds fictifs', entry_amount=amount, node_origin='CLOUD')
        return siege

    def test_bordereau_de_versement_pousse_par_une_boulangerie_ne_debite_pas_le_livre_direction(self):
        self._siege_funded()
        before = CashbookEntry.objects.count()
        v = {'id': str(uuid.uuid4()), 'date': '2026-11-21', 'motif': 'Fictif', 'beneficiary': 'X',
             'bills_10000': 5, 'node_origin': 'CLOUD'}
        r = _push(self.a1, {'treasury.DisbursementVoucher': [v]})  # simple jeton de boulangerie K1
        st = r.data['results']['treasury.DisbursementVoucher'][0]['status']
        self.assertEqual((st, CashbookEntry.objects.count()), ('REJECTED', before),
                         "un poste boulangerie a ecrit une SORTIE au livre de caisse direction")

    def test_bordereau_rejeu_ne_double_pas_la_sortie(self):
        self._siege_funded()
        v = {'id': str(uuid.uuid4()), 'date': '2026-11-21', 'motif': 'Fictif', 'bills_10000': 5,
             'node_origin': 'CLOUD'}
        siege_api, _ = _api(Node.objects.get(code='SIEGE'))  # BUG-789 : bordereau reserve au siege
        for _ in range(3):
            _push(siege_api, {'treasury.DisbursementVoucher': [v]})
        self.assertEqual(CashbookEntry.objects.filter(source_bordereau_id=v['id']).count(), 1)
        self.assertEqual(DisbursementVoucher.objects.filter(pk=v['id']).count(), 1)

    def test_bordereau_superieur_au_solde_rejete(self):
        self._siege_funded(D('1000'))
        v = {'id': str(uuid.uuid4()), 'date': '2026-11-21', 'motif': 'Fictif', 'bills_10000': 5,
             'node_origin': 'CLOUD'}
        # Jeton SIEGE (sinon le rejet viendrait de BUG-789, pas du solde insuffisant).
        siege_api, _ = _api(Node.objects.get(code='SIEGE'))
        before = CashbookEntry.objects.count()
        r = _push(siege_api, {'treasury.DisbursementVoucher': [v]})
        res = r.data['results']['treasury.DisbursementVoucher'][0]
        self.assertEqual(res['status'], 'REJECTED', res)
        self.assertIn('solde', str(res).lower(), res)
        self.assertEqual(CashbookEntry.objects.count(), before)

    def test_bordereau_node_origin_d_un_autre_noeud_rejete(self):
        v = {'id': str(uuid.uuid4()), 'date': '2026-11-21', 'motif': 'Fictif', 'bills_10000': 1,
             'node_origin': 'K2'}
        r = _push(self.a1, {'treasury.DisbursementVoucher': [v]})
        self.assertEqual(r.data['results']['treasury.DisbursementVoucher'][0]['status'], 'REJECTED')
