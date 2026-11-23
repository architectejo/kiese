"""Sync - ronde b5 (testeur Clients/Commissions, 2026-11-23) : verification de
BUG-761/785/786/787/788/789 et nouveaux angles (portee des nœuds, jeton, curseur).
Donnees FICTIVES. Code applicatif non modifie."""
import uuid
from decimal import Decimal as D
from unittest import expectedFailure

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_bread_price, make_client, make_node
from production.models import BreadTransfer, BreadTransferLine
from sync.models import DebtMovement, NodeAuthToken
from sync.services import recompute_client_debt
from sync.tests.test_verif_charge_v4 import _api, _push

PULL = '/api/sync/pull/'


class Jeton761(TestCase):
    def setUp(self):
        self.k1, self.k2 = make_node(code='K1'), make_node(code='K2')

    def _client(self, raw):
        c = APIClient(raise_request_exception=False)
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
        return c

    def test_reemission_remplace_l_ancien_jeton_et_n_affecte_pas_l_autre_noeud(self):
        _, raw_a = NodeAuthToken.issue_for_node(self.k1)
        _, raw_k2 = NodeAuthToken.issue_for_node(self.k2)
        self.assertEqual(self._client(raw_a).get(PULL).status_code, 200)
        _, raw_b = NodeAuthToken.issue_for_node(self.k1)
        self.assertNotEqual(raw_a, raw_b)
        self.assertEqual(self._client(raw_a).get(PULL).status_code, 401)
        self.assertEqual(self._client(raw_b).get(PULL).status_code, 200)
        self.assertEqual(self._client(raw_k2).get(PULL).status_code, 200)
        self.assertEqual(NodeAuthToken.objects.filter(node=self.k1).count(), 1)

    def test_reemission_apres_revocation_reactive_le_noeud(self):
        tok, _ = NodeAuthToken.issue_for_node(self.k1)
        from django.utils import timezone
        NodeAuthToken.objects.filter(pk=tok.pk).update(revoked_at=timezone.now())
        _, raw = NodeAuthToken.issue_for_node(self.k1)
        self.assertEqual(self._client(raw).get(PULL).status_code, 200)

    def test_jeton_en_clair_non_stocke(self):
        tok, raw = NodeAuthToken.issue_for_node(self.k1)
        self.assertNotIn(raw, str(tok.__dict__.values()))


class Debt787(TestCase):
    def test_recompute_fait_avancer_updated_at_et_le_pull_incremental_renvoie_le_client(self):
        k1 = make_node(code='K1')
        api, _ = _api(k1)
        c = make_client(k1)
        DebtMovement.objects.create(client=c, amount=D('700'), kind='ORDER', node_origin='K1', is_synced=True)
        from core.models import Node  # noqa: F401
        from clients.models import Client
        Client.objects.filter(pk=c.pk).update(updated_at='2020-01-01T00:00:00Z')
        recompute_client_debt(c.pk)
        c.refresh_from_db()
        self.assertEqual(c.current_debt, D('700.00'))
        r = api.get(PULL, {'since_client_debt': '2021-01-01T00:00:00+00:00'})
        self.assertEqual([x['id'] for x in r.json()['clients']], [str(c.pk)])


class PorteeV5(TestCase):
    def setUp(self):
        self.k1, self.k2, self.k3 = (make_node(code=c) for c in ('K1', 'K2', 'K3'))
        self.a1, _ = _api(self.k1)
        self.a2, _ = _api(self.k2)
        self.a3, _ = _api(self.k3)
        self.bp = make_bread_price('GRAND', 'Pain 500 FC', 500)

    def _transfer(self, status='RESPONDED'):
        return BreadTransfer.objects.create(from_node=self.k1, to_node=self.k2, bread_price=self.bp,
                                            quantity_sent=100, transfer_status=status, node_origin='K1')

    # (BUG-87x corrigé)
    def test_emetteur_ne_confirme_pas_la_reception_de_son_propre_transfert(self):
        """La validation par la boulangerie receptrice est la regle (5.4) : l'emetteur ne peut pas la court-circuiter."""
        t = self._transfer('RESPONDED')
        r = _push(self.a1, {'production.BreadTransfer': [{'id': str(t.pk), 'transfer_status': 'CONFIRMED'}]})
        t.refresh_from_db()
        self.assertNotEqual(t.transfer_status, 'CONFIRMED', r.data)

    # (BUG-87x corrigé)
    def test_emetteur_ne_cree_pas_un_transfert_deja_confirme_avec_quantite_recue(self):
        rec = {'id': str(uuid.uuid4()), 'from_node': 'K1', 'to_node': 'K2', 'bread_price': self.bp.pk,
               'quantity_sent': 100, 'quantity_received': 100, 'transfer_status': 'CONFIRMED', 'node_origin': 'K1'}
        r = _push(self.a1, {'production.BreadTransfer': [rec]})
        t = BreadTransfer.objects.filter(pk=rec['id']).first()
        ok = t is None or (t.quantity_received is None and t.transfer_status != 'CONFIRMED')
        self.assertTrue(ok, f"recu et confirme sans la receptrice : {r.data}")

    # (BUG-87x corrigé)
    def test_emetteur_ne_cree_pas_une_ligne_avec_quantite_recue(self):
        t = self._transfer('PENDING')
        rec = {'transfer': str(t.pk), 'bread_price': self.bp.pk,
               'quantity_sent': 100, 'quantity_received': 100}
        r = _push(self.a1, {'production.BreadTransferLine': [rec]})
        line = BreadTransferLine.objects.filter(transfer=t).first()
        ok = line is None or line.quantity_received is None
        self.assertTrue(ok, f"quantite recue ecrite par l'emetteur : {r.data}")

    def test_receptrice_peut_confirmer_et_ecrire_la_quantite_recue(self):
        t = self._transfer('RESPONDED')
        _push(self.a2, {'production.BreadTransfer': [
            {'id': str(t.pk), 'transfer_status': 'CONFIRMED', 'quantity_received': 100}]})
        t.refresh_from_db()
        self.assertEqual((t.transfer_status, t.quantity_received), ('CONFIRMED', 100))

    def test_ligne_existante_quantite_recue_refusee_a_l_emetteur(self):
        t = self._transfer('RESPONDED')
        line = BreadTransferLine.objects.create(transfer=t, bread_price=self.bp, quantity_sent=100)
        _push(self.a1, {'production.BreadTransferLine': [
            {'id': str(line.pk), 'transfer': str(t.pk), 'bread_price': self.bp.pk, 'quantity_sent': 100,
             'quantity_received': 100}]})
        line.refresh_from_db()
        self.assertIsNone(line.quantity_received)

    def test_bordereau_pousse_par_k2_et_k3_rejete(self):
        from treasury.models import CashbookEntry
        before = CashbookEntry.objects.count()
        for api in (self.a2, self.a3):
            v = {'id': str(uuid.uuid4()), 'date': '2026-11-21', 'motif': 'Fictif', 'bills_10000': 1,
                 'node_origin': 'CLOUD'}
            r = _push(api, {'treasury.DisbursementVoucher': [v]})
            self.assertEqual(r.data['results']['treasury.DisbursementVoucher'][0]['status'], 'REJECTED')
        self.assertEqual(CashbookEntry.objects.count(), before)
