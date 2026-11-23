"""
Ronde b18 (testeur clients/commissions, 2026-11-23) : verification independante de BUG-999 (is_active au pull),
BUG-1004 (deplacement de boulangerie, conflit de code). Donnees FICTIVES uniquement. Code applicatif non modifie.
Defauts confirmes = `@expectedFailure` + ticket (voir docs/qa/REGISTRE_BUGS.md).
"""
from datetime import timedelta
from decimal import Decimal as D
from unittest import expectedFailure

from django.utils import timezone

from clients.models import Client
from clients.tests.test_clients_v2 import api
from clients.tests.test_clients_v12 import cloud_rows
from clients.tests.test_clients_v13 import PageBase
from core.models import Node
from core.testing import make_bread_price
from sales.models import Invoice
from sync.management.commands.sync_now import apply_pull_response
from sync.models import SyncConflictLog


class Base14(PageBase):
    PAGE = 5000

    def setUp(self):
        super().setUp()
        self.k2 = Node.objects.get_or_create(code='K2', defaults={'name': 'K2 COQ'})[0]

    def row_of(self, payload, c):
        return {x['id']: x for x in payload['clients']}.get(str(c.id))

    def local_copy(self, c, **kw):
        """Cloud et poste partagent la meme base de test : l'edition API marque la ligne `is_synced=False` +
        `identity_updated_at` (edition non poussee, BUG-952). On simule la copie propre du poste."""
        Client.objects.filter(pk=c.pk).update(is_synced=True, identity_updated_at=None, **kw)

    def patch_active(self, c, value):
        r = api(self.direction).patch(f'/api/clients/clients/{c.pk}/', {'is_active': value}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))


# ---------------------------------------------------------------------------
# 1. BUG-999 : is_active
# ---------------------------------------------------------------------------
class IsActive(Base14):
    def test_desactive_au_cloud_vu_hors_ligne_puis_facturation_refusee(self):
        c3 = self.mk(self.k3, 'Hors', 'Ligne')
        first = self.get(self.k1)
        self.assertTrue(self.row_of(first, c3)['is_active'])
        self.patch_active(c3, False)
        second = self.get(self.k1, since_client_debt=first['since_client_debt'])
        row = self.row_of(second, c3)
        self.assertIs(row['is_active'], False)
        # Le poste K1 (copie locale encore active) applique la ligne.
        self.local_copy(c3, is_active=True)
        apply_pull_response(second)
        self.assertFalse(Client.objects.get(pk=c3.pk).is_active)
        bp = make_bread_price('GRAND', 'Pain 500 FC', 500)
        r = api(self.f1).post('/api/sales/invoices/', {
            'client': str(c3.pk), 'payment_amount': '0.00', 'payment_type': 'CREDIT', 'commission_rate': '0.25',
            'lines': [{'bread_price': str(bp.pk), 'quantity': 2}]}, format='json')
        self.assertEqual(r.status_code, 400, getattr(r, 'data', None))
        self.assertFalse(Invoice.objects.filter(client=c3).exists())

    def test_reactive_au_cloud_redescend_et_reactive_le_poste(self):
        c3 = self.mk(self.k3, 'Re', 'Active')
        self.patch_active(c3, False)
        Client.objects.filter(pk=c3.pk).update(updated_at=timezone.now() - timedelta(minutes=10))
        first = self.get(self.k1)  # pull initial : inactif non descendu
        self.assertIsNone(self.row_of(first, c3))
        self.patch_active(c3, True)
        second = self.get(self.k1, since_client_debt=first['since_client_debt'])
        row = self.row_of(second, c3)
        self.assertIsNotNone(row)
        self.local_copy(c3, is_active=False)
        apply_pull_response(second)
        self.assertTrue(Client.objects.get(pk=c3.pk).is_active)

    def test_inactif_d_un_autre_noeud_inconnu_du_poste_n_est_pas_cree(self):
        row = dict(cloud_rows('K3', 1)[0], is_active=False)
        apply_pull_response({'clients': [row], 'node_code': 'K1'})
        self.assertFalse(Client.objects.filter(pk=row['id']).exists())

    def test_inactif_du_noeud_local_inconnu_est_cree_inactif(self):
        row = dict(cloud_rows('K1', 1)[0], is_active=False)
        apply_pull_response({'clients': [row], 'node_code': 'K1'})
        self.assertFalse(Client.objects.get(pk=row['id']).is_active)

    def test_ancien_cloud_sans_is_active_tout_actif_et_ne_desactive_pas(self):
        c = self.mk(self.k3, 'Ancien', 'Cloud')
        row = cloud_rows('K3', 1)[0]
        row.update(id=str(c.id), code=c.code, first_name=c.first_name, last_name=c.last_name)
        row.pop('is_active', None)
        apply_pull_response({'clients': [row], 'node_code': 'K1'})
        self.assertTrue(Client.objects.get(pk=c.pk).is_active)

    def test_is_active_non_booleen_hostile_ignore(self):
        c = self.mk(self.k3, 'Hostile', 'Actif')
        for bad in ('false', 0, None, [], {}):
            row = dict(cloud_rows('K3', 1)[0], id=str(c.id), code=c.code, first_name='H', last_name='A', is_active=bad)
            apply_pull_response({'clients': [row], 'node_code': 'K1'})
            self.assertTrue(Client.objects.get(pk=c.pk).is_active, repr(bad))

    def test_rejeu_deux_fois_meme_pull_inactif_idempotent(self):
        c3 = self.mk(self.k3, 'Rejeu', 'Inactif')
        first = self.get(self.k1)
        self.patch_active(c3, False)
        second = self.get(self.k1, since_client_debt=first['since_client_debt'])
        self.local_copy(c3)
        for _ in range(3):
            apply_pull_response(second)
        self.assertFalse(Client.objects.get(pk=c3.pk).is_active)
        self.assertEqual(Client.objects.filter(pk=c3.pk).count(), 1)

    def test_pull_initial_ne_descend_jamais_les_inactifs_des_autres_noeuds(self):
        c3 = self.mk(self.k3, 'Init', 'Inactif')
        Client.objects.filter(pk=c3.pk).update(is_active=False)
        self.assertIsNone(self.row_of(self.get(self.k1), c3))

    def test_siege_ne_recoit_pas_les_inactifs_des_autres_noeuds(self):
        siege = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege'})[0]
        c3 = self.mk(self.k3, 'Siege', 'Inactif')
        first = self.get(siege)
        Client.objects.filter(pk=c3.pk).update(is_active=False, updated_at=timezone.now() + timedelta(seconds=5))
        second = self.get(siege, since_client_debt=first['since_client_debt'])
        self.assertIsNone(self.row_of(second, c3))

    # --- interaction BUG-952 (edition locale non poussee) ---
    def test_edition_locale_non_poussee_n_est_pas_desactivee_puis_l_est_apres_push(self):
        c = self.mk(self.k1, 'Edit', 'Locale')
        Client.objects.filter(pk=c.pk).update(is_synced=False, identity_updated_at=timezone.now(), first_name='Loc')
        row = dict(cloud_rows('K1', 1)[0], id=str(c.id), code=c.code, first_name='Cloud', last_name='X',
                   is_active=False)
        apply_pull_response({'clients': [row], 'node_code': 'K1'})
        c.refresh_from_db()
        self.assertEqual((c.first_name, c.is_active), ('Loc', True))
        Client.objects.filter(pk=c.pk).update(is_synced=True)  # edition poussee
        apply_pull_response({'clients': [row], 'node_code': 'K1'})
        c.refresh_from_db()
        self.assertFalse(c.is_active)

    def test_mouvement_de_dette_non_pousse_ignore_la_ligne_entiere_limite(self):
        from sync.models import DebtMovement
        c = self.mk(self.k1, 'Mvt', 'Local')
        DebtMovement.objects.create(client=c, amount=D('5.00'), kind='ORDER', node_origin='K1', is_synced=False)
        row = dict(cloud_rows('K1', 1)[0], id=str(c.id), code=c.code, first_name='M', last_name='L', is_active=False)
        apply_pull_response({'clients': [row], 'node_code': 'K1'})
        self.assertTrue(Client.objects.get(pk=c.pk).is_active)  # BUG-780 : ligne ignoree, rattrapee ensuite

    # --- pagination d'un pull INCREMENTAL ---
    @expectedFailure  # BUG-1008
    def test_BUG_1008_pull_incremental_pagine_ne_perd_pas_les_inactifs_des_pages_suivantes(self):
        cs = [self.mk(self.k3, f'Inc{i}', 'Paginee') for i in range(9)]
        first = self.get(self.k1)
        cursor = first['since_client_debt']
        base = timezone.now() + timedelta(seconds=5)
        # Tous modifies apres le curseur au meme instant ; 3 d'entre eux desactives.
        Client.objects.filter(pk__in=[c.pk for c in cs]).update(updated_at=base)
        inactifs = {str(c.id) for c in cs[:9:3]}
        Client.objects.filter(pk__in=inactifs).update(is_active=False)
        import sync.views as sv
        from unittest.mock import patch
        with patch.object(sv, 'PULL_CLIENT_PAGE_SIZE', 3):
            _, seen = self.walk(self.k1, first={'since_client_debt': cursor})
        self.assertTrue(inactifs <= set(seen),
                        f"inactifs perdus sur les pages 2+ : {sorted(inactifs - set(seen))}")


# ---------------------------------------------------------------------------
# 2. BUG-1004 : deplacement de boulangerie, code
# ---------------------------------------------------------------------------
class Deplacement(Base14):
    def move(self, c, node):
        r = api(self.direction).post('/api/clients/clients/bulk_move/', {'ids': [str(c.id)], 'node': node.pk},
                                     format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        c.refresh_from_db()

    def test_trois_postes_voient_le_deplacement(self):
        c = self.mk(self.k3, 'Trois', 'Postes')
        old = c.code
        firsts = {n.code: self.get(n) for n in (self.k1, self.k2, self.k3)}
        for p in firsts.values():
            self.assertEqual(self.row_of(p, c)['code'], old)
        self.move(c, self.k1)
        for n in (self.k1, self.k2, self.k3):
            second = self.get(n, since_client_debt=firsts[n.code]['since_client_debt'])
            row = self.row_of(second, c)
            self.assertIsNotNone(row, n.code)
            self.assertEqual((row['node'], row['code'], row['node_origin']), ('K1', c.code, 'K1'))
            # Application sur la copie locale restee a l'ancien etat.
            Client.objects.filter(pk=c.pk).update(node=self.k3, code=old, node_origin='K3')
            apply_pull_response(dict(second, node_code=n.code))
            c2 = Client.objects.get(pk=c.pk)
            self.assertEqual((c2.node.code, c2.code, c2.node_origin), ('K1', c.code, 'K1'), n.code)
            self.assertEqual(Client.objects.filter(code=c.code).count(), 1)

    def test_rejeu_du_deplacement_idempotent_et_sans_conflit(self):
        c = self.mk(self.k3, 'Rejeu', 'Move')
        first = self.get(self.k2)
        self.move(c, self.k1)
        second = self.get(self.k2, since_client_debt=first['since_client_debt'])
        Client.objects.filter(pk=c.pk).update(node=self.k3, code='K3-OLD', node_origin='K3')
        n0 = SyncConflictLog.objects.count()
        for _ in range(3):
            apply_pull_response(dict(second, node_code='K2'))
        c.refresh_from_db()
        self.assertEqual((c.node.code, c.code), ('K1', second['clients'][0]['code']))
        self.assertEqual(SyncConflictLog.objects.count(), n0)

    def test_conflit_de_code_au_deplacement_garde_l_ancien_et_journalise_une_fois(self):
        c = self.mk(self.k3, 'Conflit', 'Code')
        other = self.mk(self.k2, 'Autre', 'Local')
        row = dict(cloud_rows('K1', 1)[0], id=str(c.id), code=other.code, node='K1', node_origin='K1',
                   first_name=c.first_name, last_name=c.last_name)
        old = (c.node_id, c.code)
        n0 = SyncConflictLog.objects.filter(conflict_type='CODE_CLIENT_EN_CONFLIT').count()
        for _ in range(3):
            apply_pull_response({'clients': [row], 'node_code': 'K2'})
        c.refresh_from_db()
        self.assertEqual((c.node_id, c.code), old)
        self.assertEqual(Client.objects.filter(code=other.code).count(), 1)
        self.assertEqual(SyncConflictLog.objects.filter(conflict_type='CODE_CLIENT_EN_CONFLIT').count() - n0, 1)

    def test_deux_clients_du_meme_lot_visent_le_meme_code_un_seul_gagne(self):
        a = self.mk(self.k3, 'Lot', 'A')
        b = self.mk(self.k3, 'Lot', 'B')
        rows = [dict(cloud_rows('K1', 1)[0], id=str(x.id), code='K1-0777777', node='K1', node_origin='K1',
                     first_name=x.first_name, last_name=x.last_name) for x in (a, b)]
        apply_pull_response({'clients': rows, 'node_code': 'K2'})
        self.assertEqual(Client.objects.filter(code='K1-0777777').count(), 1)

    def test_deplace_vers_noeud_inconnu_du_poste_ne_change_rien(self):
        c = self.mk(self.k3, 'Noeud', 'Inconnu')
        row = dict(cloud_rows('ZZ', 1)[0], id=str(c.id), code='ZZ-1', node='ZZ', first_name=c.first_name,
                   last_name=c.last_name)
        apply_pull_response({'clients': [row], 'node_code': 'K1'})
        c.refresh_from_db()
        self.assertEqual(c.node_id, self.k3.pk)

    def test_deplacement_avec_edition_locale_non_poussee_garde_l_etat_local(self):  # BUG-952
        c = self.mk(self.k3, 'Edit', 'Move')
        Client.objects.filter(pk=c.pk).update(is_synced=False, identity_updated_at=timezone.now())
        row = dict(cloud_rows('K1', 1)[0], id=str(c.id), code='K1-0888888', node='K1', node_origin='K1',
                   first_name='C', last_name='M')
        apply_pull_response({'clients': [row], 'node_code': 'K2'})
        c.refresh_from_db()
        self.assertEqual(c.node_id, self.k3.pk)

    def test_code_trop_long_ou_vide_au_deplacement_ignore(self):
        c = self.mk(self.k3, 'Code', 'Hostile')
        old = c.code
        for bad in ('', '   ', 'K1-' + 'X' * 30, 12, None):
            row = dict(cloud_rows('K1', 1)[0], id=str(c.id), code=bad, node='K1', first_name='C', last_name='H')
            apply_pull_response({'clients': [row], 'node_code': 'K2'})
            self.assertEqual(Client.objects.get(pk=c.pk).code, old, repr(bad))

    def test_recalculate_category_fait_avancer_updated_at(self):
        c = self.mk(self.k1, 'Cat', 'Maj')
        Client.objects.filter(pk=c.pk).update(updated_at=timezone.now() - timedelta(hours=2))
        before = Client.objects.get(pk=c.pk).updated_at
        r = api(self.direction).post(f'/api/clients/clients/{c.pk}/recalculate_category/')
        self.assertIn(r.status_code, (200, 204), getattr(r, 'data', None))
        self.assertGreater(Client.objects.get(pk=c.pk).updated_at, before)

    def test_bulk_move_vers_meme_noeud_ne_change_pas_le_code(self):
        c = self.mk(self.k1, 'Meme', 'Noeud')
        old = c.code
        self.move(c, self.k1)
        self.assertEqual(c.code, old)
