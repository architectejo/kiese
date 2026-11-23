"""
Ronde b17 (testeur clients/commissions, 2026-11-23) : verification independante de BUG-998 (pull de tous
les clients actifs des autres boulangeries, pagination `has_more` + curseur composite, boucle de pull
bornee a 200 pages, bulk_update, conflit de code). Donnees FICTIVES uniquement. Code applicatif non modifie.

Defauts confirmes = `@expectedFailure` + ticket (voir docs/qa/REGISTRE_BUGS.md).
"""
import json
import logging
import tempfile
import time
import tracemalloc
import uuid
from datetime import timedelta
from decimal import Decimal as D
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.utils import timezone

import sync.views as sync_views
from clients.models import Client, SocialContribution
from clients.tests.test_clients_v2 import Base, api
from clients.tests.test_clients_v6 import node_api
from clients.tests.test_clients_v12 import cloud_rows
from commissions.models import ClientCommission, CommissionPeriod
from sales.models import Invoice
from sync import desktop_client
from sync.management.commands.sync_now import apply_pull_response
from sync.models import DebtMovement, SyncConflictLog

LOG = logging.getLogger('b17')
CLOUD = 'http://cloud.test'
ROW_KEYS = {
    'id', 'code', 'current_debt', 'credit_limit', 'category', 'first_name', 'last_name', 'phone', 'address',
    'updated_at', 'node', 'node_origin', 'commission_rate', 'cotisation_sociale', 'client_type', 'notes',
    'total_breads_received', 'is_active',
}
TOP_KEYS = {
    'server_time', 'config', 'since_config', 'bread_prices', 'since_breadprice', 'clients', 'since_client_debt',
    'client_after_id', 'has_more', 'closures', 'transfers', 'transfer_lines', 'mirrors', 'node_code',
    'node_settings',  # BUG-1030 : parametres propres au noeud du jeton uniquement
}


def bridge(client_api):
    """requests.get -> APIClient (le « cloud » est la meme base de test)."""
    calls = []

    def fake_get(url, headers=None, timeout=None, params=None):
        calls.append(dict(params or {}))
        r = client_api.get('/api/sync/pull/', dict(params or {}))
        m = MagicMock(status_code=r.status_code)
        m.json.return_value = r.json() if r.status_code < 500 else {}
        m.text = r.content.decode()[:200]
        return m
    return fake_get, calls


class PageBase(Base):
    PAGE = 3

    def setUp(self):
        super().setUp()
        p = patch.object(sync_views, 'PULL_CLIENT_PAGE_SIZE', self.PAGE)
        p.start()
        self.addCleanup(p.stop)
        desktop_client._PULL_CURSORS.clear()
        self.addCleanup(desktop_client._PULL_CURSORS.clear)
        self.tmp = tempfile.mkdtemp()

    def get(self, node, **params):
        return node_api(node).get('/api/sync/pull/', params).json()

    def walk(self, node, first=None, limit=30, between=None):
        """Suit has_more jusqu'au bout. Renvoie (pages, ids vus dans l'ordre)."""
        params, pages, seen = dict(first or {}), [], []
        for i in range(limit):
            data = self.get(node, **params)
            pages.append(data)
            seen += [x['id'] for x in data['clients']]
            if between:
                between(i, data)
            if not data['has_more']:
                return pages, seen
            params = {'since_client_debt': data['since_client_debt'], 'client_after_id': data['client_after_id']}
        self.fail('pagination sans fin')

    def mk_many(self, n, node=None, same_ts=True):
        ids = [str(self.mk(node or self.k1, f'P{i}', f'Page{i}').id) for i in range(n)]
        if same_ts:
            Client.objects.update(updated_at=timezone.now() - timedelta(minutes=5))
        return ids


# ---------------------------------------------------------------------------
# 1. Pagination sans perte (ex-aequo d'updated_at), rejeu, frontieres
# ---------------------------------------------------------------------------
class Pagination(PageBase):
    def test_trois_pages_ex_aequo_sans_perte_ni_doublon(self):
        ids = self.mk_many(8)
        pages, seen = self.walk(self.k1)
        self.assertEqual(len(pages), 3)
        self.assertEqual([len(p['clients']) for p in pages], [3, 3, 2])
        self.assertEqual([p['has_more'] for p in pages], [True, True, False])
        self.assertEqual(sorted(seen), sorted(ids))
        self.assertEqual(len(seen), len(set(seen)))

    def test_ordre_stable_updated_at_puis_id(self):
        self.mk_many(8)
        _, seen = self.walk(self.k1)
        _, seen2 = self.walk(self.k1)
        self.assertEqual(seen, seen2)
        self.assertEqual(seen, sorted(seen))  # tous au meme updated_at : tri par UUID

    def test_frontiere_exacte_taille_de_page_pas_de_page_vide_inutile(self):
        self.mk_many(self.PAGE * 2)
        pages, seen = self.walk(self.k1)
        self.assertEqual(len(pages), 2)
        self.assertFalse(pages[-1]['has_more'])
        self.assertEqual(len(seen), self.PAGE * 2)

    def test_taille_de_page_plus_un_donne_une_page_de_un(self):
        self.mk_many(self.PAGE + 1)
        pages, seen = self.walk(self.k1)
        self.assertEqual([len(p['clients']) for p in pages], [self.PAGE, 1])
        self.assertEqual(len(seen), self.PAGE + 1)

    def test_rejeu_de_la_meme_requete_renvoie_la_meme_page(self):
        self.mk_many(8)
        first = self.get(self.k1)
        cur = {'since_client_debt': first['since_client_debt'], 'client_after_id': first['client_after_id']}
        a, b = self.get(self.k1, **cur), self.get(self.k1, **cur)
        self.assertEqual([x['id'] for x in a['clients']], [x['id'] for x in b['clients']])
        self.assertEqual((a['since_client_debt'], a['client_after_id']), (b['since_client_debt'], b['client_after_id']))
        self.assertTrue(set(x['id'] for x in a['clients']).isdisjoint(x['id'] for x in first['clients']))

    def test_rejeu_de_toutes_les_pages_au_poste_est_idempotent(self):
        self.mk_many(8)
        pages, _ = self.walk(self.k1)
        before = list(Client.objects.order_by('id').values_list('id', 'current_debt', 'credit_limit', 'category', 'is_synced', 'updated_at'))
        for _ in range(3):
            for p in pages:
                apply_pull_response(p)
        after = list(Client.objects.order_by('id').values_list('id', 'current_debt', 'credit_limit', 'category', 'is_synced', 'updated_at'))
        self.assertEqual(before, after)
        self.assertEqual(DebtMovement.objects.count(), 0)

    def test_modification_et_creation_entre_deux_pages_rien_perdu(self):
        ids = self.mk_many(8)
        created = {}

        def between(i, data):
            if i == 0:
                # un client deja livre est modifie, un nouveau est cree pendant la pagination
                Client.objects.get(pk=data['clients'][0]['id']).save()
                created['id'] = str(self.mk(self.k3, 'Nouveau', 'Pendant').id)

        pages, seen = self.walk(self.k1, between=between)
        self.assertTrue(set(ids) <= set(seen))
        self.assertIn(created['id'], seen)
        self.assertEqual(seen.count(pages[0]['clients'][0]['id']), 2)  # redescendu apres sa modification (voulu)
        # le curseur final ne redonne plus rien
        self.assertEqual(self.get(self.k1, since_client_debt=pages[-1]['since_client_debt'])['clients'], [])

    def test_client_after_id_sans_since_est_ignore_pull_complet(self):
        ids = self.mk_many(5)
        data = self.get(self.k1, client_after_id=str(uuid.uuid4()))
        self.assertEqual(len(data['clients']), 3)
        self.assertTrue(set(x['id'] for x in data['clients']) <= set(ids))

    def test_curseur_dans_le_futur_avec_after_id_repart_de_zero_sans_400(self):
        self.mk_many(5)
        fut = (timezone.now() + timedelta(days=3)).isoformat()
        r = node_api(self.k1).get('/api/sync/pull/', {'since_client_debt': fut, 'client_after_id': str(uuid.uuid4())})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()['clients']), 3)

    def test_after_id_hostile_ne_plante_pas(self):
        for bad in ('x' * 500, "'; DROP TABLE clients_client;--", '00000000-0000-0000-0000-00000000000g', '٣' * 36):
            r = node_api(self.k1).get('/api/sync/pull/', {'since_client_debt': timezone.now().isoformat(), 'client_after_id': bad})
            self.assertIn(r.status_code, (200, 400), bad[:20])
        self.assertTrue(Client.objects.model._meta.db_table)

    def test_ancien_poste_qui_ignore_has_more_limite_connue_ex_aequo_a_la_frontiere(self):
        # Documente la limite annoncee par le dev (d47) : un poste ANCIEN n'envoie jamais client_after_id,
        # donc les ex-aequo apres la frontiere de page (updated_at identique) ne sont jamais rattrapes.
        self.mk_many(8)
        seen, params = [], {}
        for _ in range(10):
            data = self.get(self.k1, **params)
            seen += [x['id'] for x in data['clients']]
            params = {'since_client_debt': data['since_client_debt']}  # curseur « ancien » : sans after_id
            if not data['has_more']:
                break
        self.assertEqual(len(seen), 3)  # 5 clients ex-aequo jamais recus par l'ancien poste (limite documentee)

    def test_ancien_poste_converge_quand_les_updated_at_sont_distincts(self):
        ids = self.mk_many(8, same_ts=False)
        base = timezone.now() - timedelta(minutes=30)
        for i, cid in enumerate(ids):  # horodatages DISTINCTS (l'horloge Windows a ~15 ms de granularite)
            Client.objects.filter(pk=cid).update(updated_at=base + timedelta(seconds=i))
        seen, params = [], {}
        for _ in range(10):
            data = self.get(self.k1, **params)
            seen += [x['id'] for x in data['clients']]
            params = {'since_client_debt': data['since_client_debt']}
            if not data['has_more'] and not data['clients']:
                break
        self.assertEqual(sorted(set(seen)), sorted(ids))


# ---------------------------------------------------------------------------
# 2. Boucle de pull : 200 pages max, curseur qui n'avance pas, reprise
# ---------------------------------------------------------------------------
def stuck_response():
    m = MagicMock(status_code=200)
    m.json.return_value = {
        'clients': [], 'has_more': True, 'since_client_debt': (timezone.now() - timedelta(hours=1)).isoformat(),
        'client_after_id': str(uuid.uuid4()),
    }
    return m


class BouclePull(PageBase):
    def test_desktop_boucle_bornee_a_200_pages_avec_un_cloud_qui_repond_toujours_has_more(self):
        with patch.object(desktop_client.requests, 'get', side_effect=lambda *a, **k: stuck_response()) as g:
            desktop_client._pull_only(LOG, CLOUD, {}, self.tmp)
        self.assertEqual(g.call_count, 200)

    def test_desktop_curseur_qui_n_avance_pas_reste_borne(self):
        same = stuck_response()
        with patch.object(desktop_client.requests, 'get', return_value=same) as g:
            desktop_client._pull_only(LOG, CLOUD, {}, self.tmp)
        self.assertLessEqual(g.call_count, 200)

    def test_sync_now_boucle_bornee_a_200_pages(self):
        push = MagicMock(status_code=200)
        push.json.return_value = {'batch_id': str(uuid.uuid4()), 'results': {}}
        out = StringIO()
        with patch('requests.post', return_value=push), \
                patch('requests.get', side_effect=lambda *a, **k: stuck_response()) as g:
            call_command('sync_now', node_code='K1', cloud_url=CLOUD, node_token='t', stdout=out)
        self.assertEqual(g.call_count, 200)
        self.assertIn('Synchronisation terminée', out.getvalue())

    def test_desktop_pages_reelles_curseur_after_id_envoye_puis_efface_a_la_fin(self):
        ids = self.mk_many(8)
        fake, calls = bridge(node_api(self.k1))
        with patch.object(desktop_client.requests, 'get', fake):
            desktop_client._pull_only(LOG, CLOUD, {}, self.tmp, 'K1')
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0], {})
        self.assertIn('client_after_id', calls[1])
        self.assertIn('client_after_id', calls[2])
        cur = desktop_client.load_pull_cursor(self.tmp, CLOUD, 'K1')
        self.assertIn('since_client_debt', cur)
        self.assertNotIn('client_after_id', cur)
        self.assertEqual(Client.objects.count(), len(ids))

    def test_reprise_apres_503_a_la_page_2_repart_du_curseur_de_la_page_1(self):
        self.mk_many(8)
        real, calls = bridge(node_api(self.k1))
        n = {'i': 0}

        def flaky(url, headers=None, timeout=None, params=None):
            n['i'] += 1
            if n['i'] == 2:
                m = MagicMock(status_code=503)
                m.text = ''
                return m
            return real(url, headers=headers, timeout=timeout, params=params)

        with patch.object(desktop_client.requests, 'get', flaky):
            desktop_client._pull_only(LOG, CLOUD, {}, self.tmp, 'K1')
        cur = desktop_client.load_pull_cursor(self.tmp, CLOUD, 'K1')
        self.assertIn('client_after_id', cur)  # interrompu : le curseur de la page 1 est conserve
        desktop_client._PULL_CURSORS.clear()  # redemarrage du poste
        with patch.object(desktop_client.requests, 'get', real):
            desktop_client._pull_only(LOG, CLOUD, {}, self.tmp, 'K1')
        self.assertEqual(calls[-2].get('client_after_id'), cur['client_after_id'])
        self.assertNotIn('client_after_id', desktop_client.load_pull_cursor(self.tmp, CLOUD, 'K1'))

    def test_curseur_after_id_sur_disque_corrompu_ou_orphelin_ecarte(self):
        desktop_client.save_pull_cursor(self.tmp, CLOUD, {
            'since_client_debt': (timezone.now() - timedelta(hours=1)).isoformat(),
            'client_after_id': 'pas-un-uuid'}, 'K1')
        desktop_client._PULL_CURSORS.clear()
        cur = desktop_client.load_pull_cursor(self.tmp, CLOUD, 'K1')
        self.assertNotIn('client_after_id', cur)
        path = f'{self.tmp}/sync_pull_cursor.json'
        json.dump({'cloud_url': CLOUD, 'node_code': 'K1', 'client_after_id': str(uuid.uuid4())}, open(path, 'w'))
        desktop_client._PULL_CURSORS.clear()
        self.assertEqual(desktop_client.load_pull_cursor(self.tmp, CLOUD, 'K1'), {})

    def test_400_sur_le_curseur_oublie_le_curseur_et_arrete_la_boucle(self):
        self.mk_many(4)
        desktop_client.save_pull_cursor(self.tmp, CLOUD, {
            'since_client_debt': (timezone.now() - timedelta(hours=1)).isoformat(),
            'client_after_id': str(uuid.uuid4())}, 'K1')
        m = MagicMock(status_code=400)
        m.text = 'Paramètre « client_after_id » invalide'
        with patch.object(desktop_client.requests, 'get', return_value=m) as g:
            desktop_client._pull_only(LOG, CLOUD, {}, self.tmp, 'K1')
        self.assertEqual(g.call_count, 1)
        self.assertEqual(desktop_client.load_pull_cursor(self.tmp, CLOUD, 'K1'), {})


# ---------------------------------------------------------------------------
# 3. Confidentialite
# ---------------------------------------------------------------------------
class Confidentialite(PageBase):
    PAGE = 5000

    def setUp(self):
        super().setUp()
        self.c3 = self.mk(self.k3, 'Autre', 'Boulangerie')
        Client.objects.filter(pk=self.c3.pk).update(current_debt=D('12345.00'), notes='note interne K3', phone='0990000001')
        inv = Invoice.objects.create(node=self.k3, client=self.c3, payment_type='CREDIT', status='DELIVERED',
                                     payment_amount=D('0.00'), node_origin='K3', team='A')
        self.inv3 = inv
        self.mv3 = DebtMovement.objects.create(client=self.c3, amount=D('500.00'), kind='ORDER', node_origin='K3')
        per = CommissionPeriod.objects.create(node=self.k3, month=1, year=2026)
        self.com3 = ClientCommission.objects.create(period=per, client=self.c3)
        self.soc3 = SocialContribution.objects.create(client=self.c3, node=self.k3, month=1, year=2026, amount=D('2000.00'))

    def test_aucune_facture_mouvement_commission_cotisation_d_un_autre_noeud(self):
        r = node_api(self.k1).get('/api/sync/pull/')
        body = r.content.decode()
        self.assertTrue(set(r.json()) <= TOP_KEYS, set(r.json()) - TOP_KEYS)
        for secret in (str(self.inv3.id), str(self.mv3.id), str(self.com3.id), str(self.soc3.id)):
            self.assertNotIn(secret, body)
        self.assertNotIn('receipt_number', body)

    def test_colonnes_client_strictement_celles_de_la_liste_blanche(self):
        rows = {x['id']: x for x in node_api(self.k1).get('/api/sync/pull/').json()['clients']}
        self.assertEqual(set(rows[str(self.c3.id)]), ROW_KEYS)

    def test_le_poste_recoit_telephone_et_dette_des_clients_d_autres_boulangeries_comme_en_rest(self):
        # NOTE conformite : remarque.md l.10 + CLAUDE.md 5.1 autorisent le facturier a VOIR (rechercher/facturer)
        # les clients des autres boulangeries ; l'API REST expose deja a FACTURIER/LIVREUR phone, current_debt,
        # notes, cotisation_sociale, commission_rate de ces clients (ClientSerializer). Le pull n'ajoute aucune
        # colonne par rapport a la REST : conforme. Reserve : au poste, ces colonnes sont lisibles aussi par le
        # compte local d'un autre role (SQLite local) - a documenter, pas un ecart de la regle.
        row = {x['id']: x for x in node_api(self.k1).get('/api/sync/pull/').json()['clients']}[str(self.c3.id)]
        self.assertEqual((row['phone'], row['current_debt']), ('0990000001', '12345.00'))
        rest = api(self.f1).get('/api/clients/clients/', {'search': 'Boulangerie'}).json()
        rest = rest['results'] if isinstance(rest, dict) else rest
        rest_row = [x for x in rest if x['id'] == str(self.c3.id)][0]
        self.assertEqual((rest_row['phone'], rest_row['current_debt']), (row['phone'], row['current_debt']))
        self.assertTrue(set(row) - {'id', 'node', 'updated_at'} <= set(rest_row) | {'node_origin'})

    def test_aucun_client_inactif_d_un_autre_noeud_ni_ses_donnees(self):
        Client.objects.filter(pk=self.c3.pk).update(is_active=False)
        r = node_api(self.k1).get('/api/sync/pull/')
        self.assertNotIn(str(self.c3.id), r.content.decode())
        self.assertNotIn('0990000001', r.content.decode())

    def test_siege_ne_recoit_pas_le_catalogue(self):
        from core.models import Node
        siege = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege'})[0]
        body = node_api(siege).get('/api/sync/pull/').content.decode()
        self.assertNotIn(str(self.c3.id), body)

    def test_jeton_d_un_poste_ne_passe_pas_les_clients_d_un_autre_poste_par_parametre(self):
        r = node_api(self.k1).get('/api/sync/pull/', {'node': 'K3', 'node_code': 'K3'})
        self.assertEqual(r.json()['node_code'], 'K1')


# ---------------------------------------------------------------------------
# 4. Statuts (inactif / supprime) et deplacement de boulangerie
# ---------------------------------------------------------------------------
class StatutsEtDeplacement(PageBase):
    PAGE = 5000

    def test_BUG_999_client_inactif_d_un_autre_noeud_disparait_au_poste(self):
        # Le poste K1 a deja la copie ACTIVE du client K3 ; K3 le desactive. Le pull incrementiel doit le
        # signaler au poste (ligne `is_active: false`) : sinon le facturier K1 hors ligne continue de facturer.
        c3 = self.mk(self.k3, 'Va', 'Etre Desactive')
        first = self.get(self.k1)
        self.assertIn(str(c3.id), {x['id'] for x in first['clients']})
        client_api = api(self.direction)
        r = client_api.patch(f'/api/clients/clients/{c3.pk}/', {'is_active': False}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        second = self.get(self.k1, since_client_debt=first['since_client_debt'])
        rows = {x['id']: x for x in second['clients']}
        self.assertIn(str(c3.id), rows, "desactivation jamais redescendue : le poste garde le client actif")
        self.assertIs(rows[str(c3.id)].get('is_active'), False)

    def test_BUG_999_client_inactif_du_poste_recree_actif_sur_poste_neuf(self):
        mine = self.mk(self.k1, 'Mien', 'Inactif')
        Client.objects.filter(pk=mine.pk).update(is_active=False)
        payload = self.get(self.k1)
        Client.objects.all().delete()  # poste neuf
        apply_pull_response(payload)
        self.assertFalse(Client.objects.get(pk=mine.pk).is_active,
                         "client inactif recree ACTIF au poste neuf (is_active absent du pull)")

    def test_client_supprime_au_cloud_reste_au_poste_limite_documentee(self):
        # Pas de pierre tombale : documente (voir BUG-999 pour la desactivation). Le cloud ne peut de toute
        # facon supprimer que les clients sans facture/commission/distribution (PROTECT).
        c = self.mk(self.k3, 'A', 'Supprimer')
        first = self.get(self.k1)
        Client.objects.filter(pk=c.pk).delete()
        second = self.get(self.k1, since_client_debt=first['since_client_debt'])
        self.assertNotIn(str(c.id), {x['id'] for x in second['clients']})

    def test_BUG_1004_client_deplace_de_boulangerie_redescend_avec_nouveau_noeud_et_code(self):
        c = self.mk(self.k3, 'Va', 'Demenager')
        old_code = c.code
        k2 = __import__('core.models', fromlist=['Node']).Node.objects.get_or_create(code='K2', defaults={'name': 'K2'})[0]
        first = self.get(k2)
        self.assertEqual({x['id']: x for x in first['clients']}[str(c.id)]['code'], old_code)
        r = api(self.direction).post('/api/clients/clients/bulk_move/',
                                      {'ids': [str(c.id)], 'node': self.k1.pk}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        c.refresh_from_db()
        self.assertEqual(c.node_id, self.k1.pk)
        second = self.get(k2, since_client_debt=first['since_client_debt'])
        rows = {x['id']: x for x in second['clients']}
        self.assertIn(str(c.id), rows, "client deplace : updated_at inchange, jamais redescendu aux autres postes")
        self.assertEqual((rows[str(c.id)]['node'], rows[str(c.id)]['code']), ('K1', c.code))

    def test_BUG_1004_poste_existant_applique_le_nouveau_noeud_et_le_nouveau_code(self):
        c = self.mk(self.k3, 'Va', 'Demenager2')
        row = cloud_rows('K1', 1)[0]
        row.update(id=str(c.id), code='K1-0099999', node='K1', node_origin='K1', first_name=c.first_name,
                   last_name=c.last_name, current_debt='0.00')
        apply_pull_response({'clients': [row]})
        c.refresh_from_db()
        self.assertEqual((c.node.code, c.code), ('K1', 'K1-0099999'))

    def test_deplacement_bulk_move_fait_avancer_updated_at(self):  # BUG-1004 (ex-constat)
        c = self.mk(self.k3, 'Constat', 'Move')
        Client.objects.filter(pk=c.pk).update(updated_at=timezone.now() - timedelta(hours=2))
        before = Client.objects.get(pk=c.pk).updated_at
        api(self.direction).post('/api/clients/clients/bulk_move/', {'ids': [str(c.id)], 'node': self.k1.pk}, format='json')
        self.assertGreater(Client.objects.get(pk=c.pk).updated_at, before)


# ---------------------------------------------------------------------------
# 5. Edition simultanee et lots (bulk_update)
# ---------------------------------------------------------------------------
class EditionEtLots(PageBase):
    def row(self, c, **kw):
        r = cloud_rows('K1', 1)[0]
        r.update(id=str(c.id), code=c.code, first_name=c.first_name, last_name=c.last_name)
        r.update(kw)
        return r

    def test_lot_mixte_edition_locale_mouvement_non_pousse_et_client_normal(self):
        a = self.mk(self.k1, 'A', 'EditLocale')
        b = self.mk(self.k1, 'B', 'MouvementLocal')
        n = self.mk(self.k1, 'N', 'Normal')
        Client.objects.filter(pk__in=[b.pk, n.pk]).update(is_synced=True)
        Client.objects.filter(pk=a.pk).update(is_synced=False, identity_updated_at=timezone.now(),
                                              credit_limit=D('99000.00'), first_name='LocalA', phone='0911')
        DebtMovement.objects.create(client=b, amount=D('700.00'), kind='ORDER', node_origin='K1', is_synced=False)
        Client.objects.filter(pk=b.pk).update(current_debt=D('700.00'))
        rows = [self.row(a, current_debt='111.00', credit_limit='10000.00', first_name='CloudA', phone='0922'),
                self.row(b, current_debt='222.00', credit_limit='10000.00', first_name='CloudB'),
                self.row(n, current_debt='333.00', credit_limit='20000.00', first_name='CloudN', phone='0933')]
        apply_pull_response({'clients': rows})
        a.refresh_from_db(), b.refresh_from_db(), n.refresh_from_db()
        self.assertEqual((a.first_name, a.phone, a.credit_limit, a.current_debt, a.is_synced),
                         ('LocalA', '0911', D('99000.00'), D('111.00'), False))
        self.assertEqual((b.first_name, b.current_debt), ('B', D('700.00')))  # mouvement non pousse : ignore
        self.assertEqual((n.first_name, n.phone, n.credit_limit, n.current_debt, n.is_synced),
                         ('CloudN', '0933', D('20000.00'), D('333.00'), True))

    def test_bulk_update_ne_touche_ni_updated_at_ni_is_synced(self):
        cs = [self.mk(self.k1, f'U{i}', 'Stable') for i in range(5)]
        Client.objects.update(updated_at=timezone.now() - timedelta(hours=3))
        before = dict(Client.objects.values_list('id', 'updated_at'))
        Client.objects.update(is_synced=True)
        apply_pull_response({'clients': [self.row(c, current_debt='10.00') for c in cs]})
        self.assertEqual(dict(Client.objects.values_list('id', 'updated_at')), before)
        self.assertFalse(Client.objects.filter(is_synced=False).exists())

    def test_categorie_a_risque_recalculee_dans_le_lot(self):
        a = self.mk(self.k1, 'R', 'Risque')
        b = self.mk(self.k1, 'S', 'Sain')
        apply_pull_response({'clients': [
            self.row(a, current_debt='60000.00', credit_limit='50000.00', category='NORMAL'),
            self.row(b, current_debt='100.00', credit_limit='50000.00', category='NORMAL')]})
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((a.category, b.category), ('RISK', 'NORMAL'))

    def test_dette_negative_epargne_et_valeurs_hostiles_dans_un_meme_lot(self):
        a = self.mk(self.k1, 'E', 'Epargne')
        b = self.mk(self.k1, 'H', 'Hostile')
        apply_pull_response({'clients': [
            self.row(a, current_debt='-8000.00'),
            self.row(b, current_debt='NaN'), 'x', None, {'id': 5}]})
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual(a.current_debt, D('-8000.00'))
        self.assertEqual(b.current_debt, D('0.00'))

    def test_conflit_de_code_un_seul_journal_meme_en_deux_lots_distincts(self):
        local = self.mk(self.k1, 'Local', 'Code')
        rows = [dict(r, code=local.code) for r in cloud_rows('K3', 2)]
        n0 = SyncConflictLog.objects.count()
        apply_pull_response({'clients': rows[:1], 'node_code': 'K1'})
        apply_pull_response({'clients': rows[:1], 'node_code': 'K1'})
        apply_pull_response({'clients': rows[1:], 'node_code': 'K1'})
        self.assertEqual(SyncConflictLog.objects.filter(conflict_type='CODE_CLIENT_EN_CONFLIT').count() - n0, 2)
        self.assertEqual(Client.objects.filter(code=local.code).count(), 1)

    def test_deux_lignes_meme_id_dans_la_reponse_pas_de_doublon_ni_exception(self):
        r = cloud_rows('K3', 1)[0]
        apply_pull_response({'clients': [r, dict(r, current_debt='5.00')]})
        self.assertEqual(Client.objects.filter(pk=r['id']).count(), 1)


# ---------------------------------------------------------------------------
# 6. Volumetrie : poste neuf a 20 000 clients (duree, memoire), perf du bulk_update
# ---------------------------------------------------------------------------
class Volumetrie(PageBase):
    N = 20000
    PAGE = 5000

    def seed(self):
        Client.objects.bulk_create([
            Client(code=f"{('K1', 'K3')[i % 2]}-V{i:05d}", first_name=f'Pr{i}', last_name=f'N{i % 90}',
                   node=(self.k1, self.k3)[i % 2], node_origin=('K1', 'K3')[i % 2],
                   credit_limit=D('50000.00'), current_debt=D('1500.00'), phone=f'09{i:08d}',
                   address='Av. Tabora, Mbanza-Ngungu') for i in range(self.N)], batch_size=500)

    def test_poste_neuf_20000_clients_duree_memoire_et_resultat(self):
        self.seed()
        t0 = time.perf_counter()
        pages, seen = self.walk(self.k1)
        t_pull = time.perf_counter() - t0
        sizes = [len(json.dumps(p)) for p in pages]
        self.assertEqual(len(pages), 4)
        self.assertEqual(len(set(seen)), self.N)
        Client.objects.all().delete()  # poste neuf
        tracemalloc.start()
        t0 = time.perf_counter()
        for p in pages:
            apply_pull_response(p)
        t_apply = time.perf_counter() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(f"PERF b17 poste neuf {self.N} clients : pull {t_pull:.1f}s ({[round(s / 1e6, 2) for s in sizes]} Mo/page), "
              f"creation {t_apply:.1f}s, pic memoire python {peak / 1e6:.0f} Mo")
        self.assertEqual(Client.objects.count(), self.N)
        self.assertLess(t_pull, 60)
        self.assertLess(t_apply, 180)
        self.assertLess(peak, 400e6)
        self.assertEqual(Client.objects.filter(is_synced=False).count(), 0)

    def test_perf_bulk_update_rejeu_5000_et_nombre_de_requetes_constant(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.seed()
        pages, _ = self.walk(self.k1)
        page = pages[0]
        with CaptureQueriesContext(connection) as q_all:
            t0 = time.perf_counter()
            apply_pull_response(page)
            dt = time.perf_counter() - t0
        print(f"PERF b17 rejeu {len(page['clients'])} clients : {dt:.1f}s, {len(q_all)} requetes")
        small = dict(page, clients=page['clients'][:500])
        with CaptureQueriesContext(connection) as q_small:
            apply_pull_response(small)
        self.assertLess(len(q_all), len(q_small) * 14)  # lineaire en lots de 500, pas en clients
        self.assertLess(len(q_all), 200)
        self.assertLess(dt, 60)
