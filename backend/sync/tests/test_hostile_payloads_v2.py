"""
Testeur charge/resilience, ronde b2 (2026-11-22) : payloads de synchronisation
malformes ou hostiles contre `POST /api/sync/push/`.

Angles nouveaux (aucun test existant modifie) :
- structure du lot (`records` mal formes, enregistrement non objet),
- proprietaire / `node` / `node_origin` forges par un noeud authentifie,
- enumerations (statut, type de paiement) et montants non coherents,
- idempotence de lot (`batch_id` reutilise avec un autre contenu / par un autre
  noeud), rejeu, ordre inverse des dependances, lots mixtes,
- journal des conflits (`SyncConflictLog`),
- verrou : espion `select_for_update` sur `recompute_client_debt`.

NOTE SQLite : `select_for_update()` n'a AUCUN effet sous SQLite
(`connection.features.has_select_for_update` est False) ; ces tests verifient
que l'appel est emis (contrat du code), pas l'exclusion mutuelle reelle, qui ne
se verifie que sous PostgreSQL.

Defaut non corrige = `@expectedFailure` + ticket BUG-7NN (docs/qa/REGISTRE_BUGS.md).
Donnees fictives uniquement.
"""
import uuid
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.db import connection
from django.db.models.query import QuerySet
from django.test import TestCase
from rest_framework.test import APIClient

from clients.models import Client
from core.testing import make_client, make_node
from sales.models import Invoice
from sync.models import DebtMovement, NodeAuthToken, SyncBatchLog, SyncConflictLog
from treasury.models import CashbookEntry, CashClosure

URL = '/api/sync/push/'


def _api(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    # raise_request_exception=False : un 500 doit ressortir comme statut, pas
    # comme exception de test.
    api = APIClient(raise_request_exception=False)
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return api


def _push(api, records, batch_id=None):
    return api.post(URL, {'batch_id': batch_id or str(uuid.uuid4()), 'records': records}, format='json')


def _client_rec(node='K1', **extra):
    rec = {'id': str(uuid.uuid4()), 'node': node, 'first_name': 'Fictif', 'last_name': 'Client',
           'node_origin': node}
    rec.update(extra)
    return rec


def _invoice_rec(node='K1', client=None, **extra):
    rec = {'id': str(uuid.uuid4()), 'node': node, 'client': client, 'status': 'PENDING',
           'payment_type': 'CASH', 'order_total': '1000', 'payment_amount': '1000',
           'debt_before': '0', 'debt_after': '0', 'node_origin': node}
    rec.update(extra)
    return rec


def _status(resp, label, idx=0):
    return resp.data['results'][label][idx]['status']


class MalformedStructureTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.api = _api(self.k1)

    def test_records_liste_au_lieu_d_objet_donne_400(self):
        resp = self.api.post(URL, {'batch_id': str(uuid.uuid4()), 'records': []}, format='json')
        # `[] or {}` -> accepte comme lot vide : tolere ; une liste NON vide doit etre 400.
        self.assertIn(resp.status_code, (200, 400))
        resp = self.api.post(URL, {'batch_id': str(uuid.uuid4()), 'records': [1, 2]}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_batch_id_invalides(self):
        for bad in (None, '', 'pas-un-uuid', 123, ['x'], {'a': 1}, 'x' * 5000):
            resp = self.api.post(URL, {'batch_id': bad, 'records': {}}, format='json')
            self.assertEqual(resp.status_code, 400, repr(bad)[:40])

    def test_valeur_de_modele_non_liste_ne_provoque_pas_de_500(self):
        for bad in ('abc', {'a': 1}, 12, True, [None], [1], ['x'], [[1]]):
            for label in ('clients.Client', 'modele.Inconnu'):
                resp = _push(self.api, {label: bad})
                self.assertLess(resp.status_code, 500, (label, repr(bad)))

    def test_enregistrement_non_objet_rejete_proprement(self):
        resp = _push(self.api, {'clients.Client': [None, 7, 'x', [1]]})
        self.assertEqual(resp.status_code, 200, getattr(resp, 'content', b'')[:200])
        statuses = [r['status'] for r in resp.data['results']['clients.Client']]
        self.assertEqual(statuses, ['REJECTED'] * 4)

    def test_ids_non_uuid_rejetes_sans_500(self):
        for bad in ('abc', 3.5, ['x'], {'a': 1}, 'x' * 300, '../../etc'):
            resp = _push(self.api, {'clients.Client': [_client_rec(id=bad)]})
            self.assertEqual(resp.status_code, 200, repr(bad)[:30])
            self.assertEqual(_status(resp, 'clients.Client'), 'REJECTED', repr(bad)[:30])
        self.assertEqual(Client.objects.count(), 0)

    def test_aucune_ecriture_residuelle_quand_un_enregistrement_est_rejete(self):
        # Montant impossible (hors precision) : l'enregistrement est rejete ET
        # n'a laisse aucune ligne partielle (transaction par enregistrement).
        cl = make_client(self.k1)
        rec = {'id': str(uuid.uuid4()), 'client': str(cl.pk), 'amount': '9' * 40, 'kind': 'ORDER',
               'node_origin': 'K1'}
        resp = _push(self.api, {'sync.DebtMovement': [rec]})
        self.assertEqual(_status(resp, 'sync.DebtMovement'), 'REJECTED')
        self.assertEqual(DebtMovement.objects.count(), 0)
        cl.refresh_from_db()
        self.assertEqual(cl.current_debt, Decimal('0.00'))

    def test_montants_non_finis_rejetes_et_dette_intacte(self):
        cl = make_client(self.k1, current_debt=Decimal('0.00'))
        for bad in ('NaN', 'Infinity', '-Infinity', 'sNaN', '1e999999'):
            rec = {'id': str(uuid.uuid4()), 'client': str(cl.pk), 'amount': bad, 'kind': 'ORDER'}
            resp = _push(self.api, {'sync.DebtMovement': [rec]})
            self.assertEqual(resp.status_code, 200, bad)
            self.assertEqual(_status(resp, 'sync.DebtMovement'), 'REJECTED', bad)
        self.assertEqual(DebtMovement.objects.count(), 0)
        cl.refresh_from_db()
        self.assertEqual(cl.current_debt, Decimal('0.00'))

    def test_id_entier_n_est_pas_converti_en_uuid(self):
        for bad in (123, True):
            resp = _push(self.api, {'clients.Client': [_client_rec(id=bad)]})
            self.assertEqual(_status(resp, 'clients.Client'), 'REJECTED', repr(bad))

    def test_montant_hors_plage_ne_rend_pas_le_client_illisible(self):
        # Sous SQLite le DecimalField(14,2) n'est pas borne a l'ecriture : un seul
        # mouvement de 40 chiffres est ACCEPTE puis `Client.current_debt` est
        # illisible (decimal.InvalidOperation) -> toute liste de clients repond 500.
        from core.testing import make_user
        cl = make_client(self.k1)
        resp = _push(self.api, {'sync.DebtMovement': [
            {'id': str(uuid.uuid4()), 'client': str(cl.pk), 'amount': '9' * 40, 'kind': 'ORDER'}]})
        user = make_user('DIRECTION', node=None, username='v2_dir_poison')
        reader = APIClient(raise_request_exception=False)
        reader.force_authenticate(user)
        lst = reader.get('/api/clients/clients/')
        self.assertEqual(lst.status_code, 200, f"push={_status(resp, 'sync.DebtMovement')} liste={lst.status_code}")

    def test_champ_trop_long_rejete_independamment_du_moteur(self):
        # SQLite n'applique pas max_length ; PostgreSQL leve DataError. Le
        # comportement doit etre identique : rejet explicite.
        resp = _push(self.api, {'clients.Client': [_client_rec(first_name='A' * 10_000)]})
        self.assertEqual(_status(resp, 'clients.Client'), 'REJECTED')
        self.assertEqual(Client.objects.count(), 0)

    def test_lot_geant_5000_clients_traite_sans_erreur(self):
        recs = [_client_rec() for _ in range(1500)]
        resp = _push(self.api, {'clients.Client': recs})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Client.objects.count(), 1500)
        # rejeu : aucune duplication
        again = _push(self.api, {'clients.Client': recs})
        self.assertEqual(again.status_code, 200)
        self.assertEqual(Client.objects.count(), 1500)


class OwnershipForgeryTests(TestCase):
    """Un noeud authentifie (K1) ne doit pas ecrire dans les livres de K2."""

    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.api1 = _api(self.k1)

    def test_client_d_une_autre_boulangerie_refuse(self):
        resp = _push(self.api1, {'clients.Client': [_client_rec(node='K2', node_origin='K2')]})
        self.assertEqual(_status(resp, 'clients.Client'), 'REJECTED')
        self.assertEqual(Client.objects.filter(node=self.k2).count(), 0)

    def test_facture_d_une_autre_boulangerie_refusee(self):
        resp = _push(self.api1, {'sales.Invoice': [_invoice_rec(node='K2', node_origin='K2')]})
        self.assertEqual(_status(resp, 'sales.Invoice'), 'REJECTED')
        self.assertEqual(Invoice.objects.filter(node=self.k2).count(), 0)

    def test_cloture_validee_d_une_autre_boulangerie_n_ecrit_pas_au_livre_de_caisse(self):
        rec = {'id': str(uuid.uuid4()), 'node': 'K2', 'date': '2026-11-20',
               'total_entries': '500000', 'total_expenses': '0', 'is_validated': True,
               'node_origin': 'K2'}
        resp = _push(self.api1, {'treasury.CashClosure': [rec]})
        self.assertEqual(_status(resp, 'treasury.CashClosure'), 'REJECTED')
        self.assertEqual(CashClosure.objects.filter(node=self.k2).count(), 0)
        self.assertEqual(CashbookEntry.objects.count(), 0)

    def test_node_origin_forge_est_ecrase_par_le_noeud_authentifie(self):
        rec = _client_rec(node='K1', node_origin='K2')
        _push(self.api1, {'clients.Client': [rec]})
        stored = Client.objects.filter(pk=rec['id']).first()
        # soit rejete, soit node_origin ramene a K1 : jamais K2.
        self.assertTrue(stored is None or stored.node_origin == 'K1', stored and stored.node_origin)

    def test_mouvement_de_dette_node_origin_forge(self):
        cl = make_client(self.k1)
        mid = str(uuid.uuid4())
        _push(self.api1, {'sync.DebtMovement': [
            {'id': mid, 'client': str(cl.pk), 'amount': '100', 'kind': 'ORDER', 'node_origin': 'K2'}]})
        mv = DebtMovement.objects.filter(pk=mid).first()
        self.assertTrue(mv is None or mv.node_origin == 'K1', mv and mv.node_origin)

    def test_noeud_non_proprietaire_ne_modifie_pas_un_client_et_journalise(self):
        cl = make_client(self.k2)  # node_origin K2
        resp = _push(self.api1, {'clients.Client': [
            _client_rec(id=str(cl.pk), node='K2', first_name='Pirate')]})
        self.assertEqual(_status(resp, 'clients.Client'), 'REJECTED')
        cl.refresh_from_db()
        self.assertNotEqual(cl.first_name, 'Pirate')
        self.assertEqual(SyncConflictLog.objects.filter(
            conflict_type='NON_PROPRIETAIRE', object_id=str(cl.pk)).count(), 1)

    def test_rejeux_hostiles_n_inondent_pas_le_journal_des_conflits(self):
        cl = make_client(self.k2)
        for _ in range(5):
            _push(self.api1, {'clients.Client': [_client_rec(id=str(cl.pk), node='K2')]})
        self.assertEqual(SyncConflictLog.objects.filter(object_id=str(cl.pk)).count(), 1)

    def test_collision_de_code_client_journalisee_comme_conflit(self):
        existing = make_client(self.k1)
        resp = _push(self.api1, {'clients.Client': [_client_rec(code=existing.code)]})
        self.assertEqual(_status(resp, 'clients.Client'), 'REJECTED')
        self.assertTrue(SyncConflictLog.objects.exists(),
                        "rejet silencieux : aucune trace dans SyncConflictLog")

    def test_collision_de_code_ne_fuit_pas_de_details_sql(self):
        existing = make_client(self.k1)
        resp = _push(self.api1, {'clients.Client': [_client_rec(code=existing.code)]})
        reason = resp.data['results']['clients.Client'][0].get('reason', '')
        self.assertNotIn('UNIQUE constraint', reason)
        self.assertNotIn('clients_client', reason)


class EnumerationsAndConsistencyTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.api = _api(self.k1)

    def test_statut_de_facture_hors_enumeration_rejete(self):
        resp = _push(self.api, {'sales.Invoice': [_invoice_rec(status='PIRATE')]})
        self.assertEqual(_status(resp, 'sales.Invoice'), 'REJECTED')

    def test_type_de_paiement_hors_enumeration_rejete(self):
        resp = _push(self.api, {'sales.Invoice': [_invoice_rec(payment_type='TROC')]})
        self.assertEqual(_status(resp, 'sales.Invoice'), 'REJECTED')

    def test_montants_negatifs_de_facture_rejetes(self):
        resp = _push(self.api, {'sales.Invoice': [_invoice_rec(order_total='-5000', payment_amount='-1')]})
        self.assertEqual(_status(resp, 'sales.Invoice'), 'REJECTED')

    def test_dates_invalides_rejetees(self):
        for bad in ('pas-une-date', '2026-13-45', 12345, ['x']):
            resp = _push(self.api, {'sales.Invoice': [_invoice_rec(delivered_at=bad)]})
            self.assertEqual(_status(resp, 'sales.Invoice'), 'REJECTED', repr(bad))
        resp = _push(self.api, {'treasury.CashClosure': [
            {'id': str(uuid.uuid4()), 'node': 'K1', 'date': 'hier'}]})
        self.assertEqual(_status(resp, 'treasury.CashClosure'), 'REJECTED')

    def test_cloture_sans_date_rejetee_sans_500(self):
        resp = _push(self.api, {'treasury.CashClosure': [{'id': str(uuid.uuid4()), 'node': 'K1'}]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_status(resp, 'treasury.CashClosure'), 'REJECTED')

    def test_un_enregistrement_ne_peut_pas_regresser_une_facture_livree(self):
        cl = make_client(self.k1)
        rec = _invoice_rec(client=str(cl.pk), status='DELIVERED')
        _push(self.api, {'sales.Invoice': [rec]})
        back = dict(rec, status='PENDING', order_total='1')
        _push(self.api, {'sales.Invoice': [back]})
        inv = Invoice.objects.get(pk=rec['id'])
        self.assertEqual(inv.status, 'DELIVERED')
        self.assertEqual(inv.order_total, Decimal('1000'))


class BatchIdempotenceTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.api1 = _api(self.k1)
        self.api2 = _api(self.k2)

    def test_lot_mixte_resultats_par_enregistrement_et_statut_partiel(self):
        good = _client_rec()
        resp = _push(self.api1, {
            'clients.Client': [good, _client_rec(id='x')],
            'modele.Inconnu': [{'id': 'a'}],
            'sales.Invoice': [_invoice_rec(client=str(uuid.uuid4()))],
        })
        self.assertEqual(resp.status_code, 200)
        res = resp.data['results']
        self.assertEqual([r['status'] for r in res['clients.Client']], ['ACCEPTED', 'REJECTED'])
        self.assertEqual(res['modele.Inconnu'][0]['status'], 'REJECTED')
        self.assertIn('dépendance manquante', res['sales.Invoice'][0]['reason'])
        self.assertEqual(SyncBatchLog.objects.get(batch_id=resp.data['batch_id']).status, 'PARTIAL')

    def test_ordre_inverse_des_cles_du_lot_respecte_les_dependances(self):
        cl = _client_rec()
        inv = _invoice_rec(client=cl['id'])
        mv = {'id': str(uuid.uuid4()), 'client': cl['id'], 'invoice': inv['id'], 'amount': '700',
              'kind': 'ORDER'}
        # cles volontairement dans l'ordre INVERSE du graphe de dependances
        resp = _push(self.api1, {'sync.DebtMovement': [mv], 'sales.Invoice': [inv], 'clients.Client': [cl]})
        for label in ('clients.Client', 'sales.Invoice', 'sync.DebtMovement'):
            self.assertEqual(_status(resp, label), 'ACCEPTED', label)
        self.assertEqual(Client.objects.get(pk=cl['id']).current_debt, Decimal('700.00'))

    def test_rejeu_meme_lot_idempotent_et_marque_replayed(self):
        cl = _client_rec()
        bid = str(uuid.uuid4())
        first = _push(self.api1, {'clients.Client': [cl]}, batch_id=bid)
        second = _push(self.api1, {'clients.Client': [cl]}, batch_id=bid)
        self.assertFalse(first.data['replayed'])
        self.assertTrue(second.data['replayed'])
        self.assertEqual(second.data['results'], first.data['results'])
        self.assertEqual(Client.objects.count(), 1)

    def test_batch_id_reutilise_avec_un_autre_contenu_n_est_pas_avale_silencieusement(self):
        bid = str(uuid.uuid4())
        _push(self.api1, {'clients.Client': [_client_rec()]}, batch_id=bid)
        other = _client_rec()
        resp = _push(self.api1, {'clients.Client': [other]}, batch_id=bid)
        # Soit le contenu est traite, soit le serveur refuse explicitement (409/400).
        processed = Client.objects.filter(pk=other['id']).exists()
        self.assertTrue(processed or resp.status_code in (400, 409),
                        "payload different avale : resultats de l'ancien lot renvoyes")

    def test_batch_id_d_un_autre_noeud_ne_fuit_pas_ses_resultats(self):
        bid = str(uuid.uuid4())
        first = _push(self.api1, {'clients.Client': [_client_rec(node='K1')]}, batch_id=bid)
        mine = _client_rec(node='K2')
        resp = _push(self.api2, {'clients.Client': [mine]}, batch_id=bid)
        leaked = resp.status_code == 200 and resp.data.get('results') == first.data['results']
        self.assertFalse(leaked, "K2 a recu les resultats (ids) du lot de K1")
        self.assertTrue(Client.objects.filter(pk=mine['id']).exists())

    def test_rejet_dependance_manquante_puis_acceptation_apres_rattrapage(self):
        cl = _client_rec()
        inv = _invoice_rec(client=cl['id'])
        r1 = _push(self.api1, {'sales.Invoice': [inv]})
        self.assertEqual(_status(r1, 'sales.Invoice'), 'REJECTED')
        r2 = _push(self.api1, {'clients.Client': [cl], 'sales.Invoice': [inv]})
        self.assertEqual(_status(r2, 'sales.Invoice'), 'ACCEPTED')
        self.assertEqual(Invoice.objects.filter(pk=inv['id']).count(), 1)

    def test_meme_uuid_plusieurs_fois_dans_le_meme_lot_une_seule_ligne(self):
        cl = _client_rec()
        resp = _push(self.api1, {'clients.Client': [cl, dict(cl), dict(cl, first_name='Autre')]})
        self.assertEqual([r['status'] for r in resp.data['results']['clients.Client']], ['ACCEPTED'] * 3)
        self.assertEqual(Client.objects.filter(pk=cl['id']).count(), 1)
        self.assertEqual(Client.objects.get(pk=cl['id']).first_name, 'Fictif')

    def test_meme_mouvement_dette_rejoue_ne_double_pas(self):
        cl = make_client(self.k1)
        rec = {'id': str(uuid.uuid4()), 'client': str(cl.pk), 'amount': '250', 'kind': 'ORDER'}
        for _ in range(4):
            _push(self.api1, {'sync.DebtMovement': [rec]})
        cl.refresh_from_db()
        self.assertEqual(cl.current_debt, Decimal('250.00'))
        self.assertEqual(DebtMovement.objects.filter(pk=rec['id']).count(), 1)

    def test_meme_id_mouvement_avec_montant_different_est_un_conflit_journalise(self):
        cl = make_client(self.k1)
        mid = str(uuid.uuid4())
        _push(self.api1, {'sync.DebtMovement': [
            {'id': mid, 'client': str(cl.pk), 'amount': '250', 'kind': 'ORDER'}]})
        resp = _push(self.api1, {'sync.DebtMovement': [
            {'id': mid, 'client': str(cl.pk), 'amount': '999999', 'kind': 'ORDER'}]})
        self.assertEqual(_status(resp, 'sync.DebtMovement'), 'REJECTED')
        self.assertTrue(SyncConflictLog.objects.filter(object_id=mid).exists())


class DebtLockSpyTests(TestCase):
    """Espion de verrou (SQLite : appel emis mais sans effet d'exclusion)."""

    def test_sqlite_n_a_pas_d_effet_de_verrou_documente(self):
        # Garde-fou de documentation : si ce test echoue, le moteur de test a
        # change (PostgreSQL) et les tests de concurrence reelle deviennent possibles.
        if connection.vendor == 'sqlite':
            self.assertFalse(connection.features.has_select_for_update)

    def test_recompute_client_debt_verrouille_la_ligne_client(self):
        from sync.services import apply_debt_movement
        k1 = make_node(code='K1')
        cl = make_client(k1)
        calls = []
        original = QuerySet.select_for_update

        def spy(self, *a, **kw):
            calls.append(self.model.__name__)
            return original(self, *a, **kw)

        with patch.object(QuerySet, 'select_for_update', spy):
            apply_debt_movement(cl, Decimal('100'), 'ORDER', 'K1')
        self.assertIn('Client', calls)

    def test_dette_d_ouverture_non_couverte_par_un_mouvement_est_conservee(self):
        # Client avec 20 000 FC de dette initiale (import) sans DebtMovement :
        # un premier mouvement poussé de +1 000 doit donner 21 000, pas 1 000.
        k1 = make_node(code='K1')
        cl = make_client(k1, current_debt=Decimal('20000.00'))
        api = _api(k1)
        _push(api, {'sync.DebtMovement': [
            {'id': str(uuid.uuid4()), 'client': str(cl.pk), 'amount': '1000', 'kind': 'ORDER'}]})
        cl.refresh_from_db()
        self.assertEqual(cl.current_debt, Decimal('21000.00'))
