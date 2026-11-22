"""Verification independante Dev C (testeur-permissions) de BUG-522 :
immutabilite de from_node / to_node / initiated_by / quantites d'en-tete d'un
BreadTransfer apres creation. Donnees fictives uniquement."""
from production.models import BreadTransfer, BreadTransferLine
from core.models import Node
from core.tests.test_permissions_regression_2026_11_19 import cl
from core.tests.test_verif_isolation_a_c import IsoBase

STATUSES = ['PENDING', 'RESPONDED', 'DISPUTED', 'CONFIRMED', 'CANCELLED']


class Bug522Base(IsoBase):
    def mk(self, status='PENDING'):
        """Demande K1 (to_node, demandeur) -> K2 (from_node, fournisseur)."""
        t = BreadTransfer.objects.create(
            from_node=self.k2, to_node=self.k1, initiated_by=self.u['GERANT'],
            node_origin='P1', transfer_status=status)
        BreadTransferLine.objects.create(transfer=t, bread_price=self.bp, quantity_sent=2,
                                         quantity_received=2 if status != 'PENDING' else None)
        return t, f'/api/production/transfers/{t.pk}/'

    def snapshot(self, t):
        t.refresh_from_db()
        return {f.attname: getattr(t, f.attname) for f in BreadTransfer._meta.concrete_fields}

    def forged(self):
        return {
            'from_node': self.k3.pk, 'to_node': self.k3.pk, 'initiated_by': self.u3.pk,
            'quantity_sent': 99, 'quantity_received': 98,
        }


class ImmutableMatrix(Bug522Base):
    """Chaque champ x chaque statut x chaque role, PATCH et PUT."""

    def test_each_field_each_status_requester_and_supplier(self):
        for status in STATUSES:
            for who, user in (('demandeur', self.u['GERANT']), ('fournisseur', self.u2['GERANT'])):
                for field, val in self.forged().items():
                    t, url = self.mk(status)
                    before = self.snapshot(t)
                    r = cl(user).patch(url, {field: val}, format='json')
                    self.assertEqual(r.status_code, 400, (status, who, field, r.content))
                    self.assertIn('detail', r.data)
                    self.assertEqual(self.snapshot(t), before, (status, who, field))
                    # PUT complet avec un seul champ falsifie
                    body = {'from_node': self.k2.pk, 'to_node': self.k1.pk,
                            'initiated_by': self.u['GERANT'].pk, 'quantity_sent': None,
                            'quantity_received': None}
                    body[field] = val
                    r = cl(user).put(url, body, format='json')
                    self.assertEqual(r.status_code, 400, (status, who, 'PUT', field, r.content))
                    self.assertEqual(self.snapshot(t), before, (status, who, 'PUT', field))

    def test_hq_roles_also_refused(self):
        """Siege (ADMIN/DIRECTION/COMPTABLE) : meme regle (immuable pour tous)."""
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            for field, val in self.forged().items():
                t, url = self.mk('PENDING')
                before = self.snapshot(t)
                r = cl(self.u[role]).patch(url, {field: val}, format='json')
                self.assertEqual(r.status_code, 400, (role, field, r.content))
                self.assertEqual(self.snapshot(t), before, (role, field))

    def test_third_gerant_404_and_facturier_livreur_403(self):
        t, url = self.mk('PENDING')
        before = self.snapshot(t)
        self.assertEqual(cl(self.u3).patch(url, {'to_node': self.k3.pk}, format='json').status_code, 404)
        self.assertEqual(cl(self.u3).put(url, {'to_node': self.k3.pk, 'from_node': self.k2.pk},
                                         format='json').status_code, 404)
        for role in ('FACTURIER', 'LIVREUR'):
            for u in (self.u[role], self.u2[role]):
                for m in ('patch', 'put'):
                    r = getattr(cl(u), m)(url, {'to_node': self.k3.pk}, format='json')
                    self.assertEqual(r.status_code, 403, (role, m, r.status_code))
        self.assertEqual(cl().patch(url, {'notes': 'x'}, format='json').status_code, 401)
        self.assertEqual(self.snapshot(t), before)

    def test_every_model_field_untouched_by_patch(self):
        """Tous les champs concrets du modele : seule `notes` peut changer."""
        t, url = self.mk('PENDING')
        before = self.snapshot(t)
        attack = {
            'id': '11111111-1111-4111-8111-111111111111', 'bread_price': self.bp.pk,
            'quantity_sent': 7, 'quantity_received': 7, 'transfer_status': 'CONFIRMED',
            'initiated_by': self.u3.pk, 'confirmed_by': self.u['GERANT'].pk,
            'node_origin': 'ZZ', 'is_synced': True, 'created_at': '2001-01-01T00:00:00Z',
            'updated_at': '2001-01-01T00:00:00Z', 'from_node': self.k3.pk, 'to_node': self.k3.pk,
            'request_status': 'X', 'request_quantity': 5, 'transfer_type': 'GIFT',
            'quantity_gap': 0, 'total_sent': 0, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 500}],
        }
        names = {f.name for f in BreadTransfer._meta.concrete_fields}
        # un champ a la fois (sauf notes) : jamais de 500, jamais de modification
        for k, v in attack.items():
            r = cl(self.u['GERANT']).patch(url, {k: v}, format='json')
            self.assertLess(r.status_code, 500, (k, r.status_code))
            after = self.snapshot(t)
            diff = {a for a in after if after[a] != before[a]}
            self.assertEqual(diff - {'updated_at'}, set(), (k, diff))
        # tous ensemble
        r = cl(self.u['GERANT']).patch(url, attack, format='json')
        self.assertLess(r.status_code, 500)
        after = self.snapshot(t)
        self.assertEqual({a for a in after if after[a] != before[a]} - {'updated_at'}, set())
        self.assertEqual(t.lines.get().quantity_sent, 2)
        # champs du modele non couverts par l'attaque
        self.assertTrue(names <= set(attack) | {'notes', 'id'}, names - set(attack))

    def test_status_and_confirmed_by_ignored(self):
        t, url = self.mk('PENDING')
        r = cl(self.u['GERANT']).patch(
            url, {'transfer_status': 'CONFIRMED', 'confirmed_by': self.u['GERANT'].pk}, format='json')
        self.assertEqual(r.status_code, 200)
        t.refresh_from_db()
        self.assertEqual(t.transfer_status, 'PENDING')
        self.assertIsNone(t.confirmed_by_id)


class RoundTrip(Bug522Base):
    def test_put_with_identical_values_roundtrip_all_statuses(self):
        # PENDING seul : les autres statuts sont figes par la garde BUG-223
        # (perform_update), verifiee dans test_non_pending_frozen_even_if_identical.
        for status in ('PENDING',):
            for user in (self.u['GERANT'], self.u2['GERANT'], self.u['DIRECTION']):
                t, url = self.mk(status)
                g = cl(user)
                data = dict(g.get(url).data)
                data['notes'] = f'aller-retour {status}'
                r = g.put(url, data, format='json')
                self.assertEqual(r.status_code, 200, (status, user.role, r.content))
                t.refresh_from_db()
                self.assertEqual((t.from_node_id, t.to_node_id, t.initiated_by_id),
                                 (self.k2.pk, self.k1.pk, self.u['GERANT'].pk))
                self.assertEqual(t.transfer_status, status)
                self.assertEqual(t.notes, f'aller-retour {status}')

    def test_non_pending_frozen_even_if_identical(self):
        for status in ('RESPONDED', 'DISPUTED', 'CONFIRMED', 'CANCELLED'):
            t, url = self.mk(status)
            before = self.snapshot(t)
            g = cl(self.u['GERANT'])
            r = g.patch(url, {'notes': 'x'}, format='json')
            self.assertEqual(r.status_code, 400, (status, r.content))
            r = g.put(url, dict(g.get(url).data), format='json')
            self.assertEqual(r.status_code, 400, (status, r.content))
            self.assertEqual(self.snapshot(t), before)

    def test_patch_identical_values_ok(self):
        t, url = self.mk('PENDING')
        r = cl(self.u['GERANT']).patch(
            url, {'from_node': self.k2.pk, 'to_node': self.k1.pk,
                  'initiated_by': self.u['GERANT'].pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_string_form_of_identical_value_ok(self):
        """Formulaire multipart : les pk arrivent en chaines."""
        t, url = self.mk('PENDING')
        r = cl(self.u['GERANT']).patch(
            url, {'from_node': str(self.k2.pk), 'to_node': str(self.k1.pk)}, format='multipart')
        self.assertEqual(r.status_code, 200, r.content)

    def test_null_and_invalid_values_are_400_not_500(self):
        t, url = self.mk('PENDING')
        for body in ({'to_node': None}, {'from_node': None}, {'initiated_by': None},
                     {'from_node': 'zzz'}, {'to_node': 987654}, {'quantity_sent': -1}):
            r = cl(self.u['GERANT']).patch(url, body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code))
        t.refresh_from_db()
        self.assertEqual((t.from_node_id, t.to_node_id, t.initiated_by_id),
                         (self.k2.pk, self.k1.pk, self.u['GERANT'].pk))


class CreationRules(Bug522Base):
    def lines(self):
        return [{'bread_price': self.bp.pk, 'quantity_sent': 3}]

    def test_gerant_cannot_create_transfer_not_involving_own_node(self):
        """K3 tente K2 -> K1 (ni demandeur ni fournisseur) : to_node force a K3."""
        r = cl(self.u3).post('/api/production/transfers/', {
            'from_node': self.k2.pk, 'to_node': self.k1.pk, 'lines': self.lines()}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        t = BreadTransfer.objects.get(pk=r.data['id'])
        self.assertEqual((t.to_node_id, t.from_node_id), (self.k3.pk, self.k2.pk))
        self.assertEqual(t.initiated_by_id, self.u3.pk)
        # aucune combinaison ne permet un transfert sans le noeud de l'appelant
        self.assertFalse(BreadTransfer.objects.filter(from_node=self.k2, to_node=self.k1,
                                                       initiated_by=self.u3).exists())

    def test_create_missing_or_self_from_node_is_400(self):
        g = cl(self.u['GERANT'])
        for body in ({'lines': self.lines()}, {'from_node': self.k1.pk, 'lines': self.lines()}):
            r = g.post('/api/production/transfers/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.status_code, r.content))

    def test_create_roles(self):
        body = {'from_node': self.k2.pk, 'lines': self.lines()}
        for role in ('FACTURIER', 'LIVREUR'):
            self.assertEqual(cl(self.u[role]).post('/api/production/transfers/', body,
                                                   format='json').status_code, 403, role)
        self.assertEqual(cl().post('/api/production/transfers/', body, format='json').status_code, 401)
        # siege sans boulangerie : refus propre (400), pas 500
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            r = cl(self.u[role]).post('/api/production/transfers/', body, format='json')
            self.assertEqual(r.status_code, 400, (role, r.status_code, r.content))

    def test_create_ignores_forged_state_fields(self):
        r = cl(self.u['GERANT']).post('/api/production/transfers/', {
            'from_node': self.k2.pk, 'to_node': self.k3.pk, 'initiated_by': self.u3.pk,
            'transfer_status': 'CONFIRMED', 'confirmed_by': self.u3.pk, 'quantity_received': 50,
            'node_origin': 'ZZ', 'lines': self.lines()}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        t = BreadTransfer.objects.get(pk=r.data['id'])
        self.assertEqual((t.to_node_id, t.initiated_by_id, t.transfer_status, t.confirmed_by_id,
                          t.node_origin), (self.k1.pk, self.u['GERANT'].pk, 'PENDING', None, 'P1'))

    def test_create_with_nested_lines_node_fields_ignored(self):
        r = cl(self.u['GERANT']).post('/api/production/transfers/', {
            'from_node': self.k2.pk,
            'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 3, 'transfer': str(self.tr23.pk)}]},
            format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.tr23.lines.count(), 1)


class ActionsDoNotRewire(Bug522Base):
    def _nodes(self, t):
        t.refresh_from_db()
        return (t.from_node_id, t.to_node_id, t.initiated_by_id)

    def test_respond_confirm_resolve_ignore_node_fields(self):
        extra = {'from_node': self.k3.pk, 'to_node': self.k3.pk, 'initiated_by': self.u3.pk,
                 'transfer_status': 'CANCELLED'}
        # respond (fournisseur K2)
        t, url = self.mk('PENDING')
        r = cl(self.u2['GERANT']).post(
            url + 'respond_to_request/',
            {'approved': True, 'lines': [{'bread_price': self.bp.pk, 'quantity_sent': 2}], **extra},
            format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._nodes(t), (self.k2.pk, self.k1.pk, self.u['GERANT'].pk))
        self.assertEqual(t.transfer_status, 'RESPONDED')
        # confirm (demandeur K1) avec ecart -> DISPUTED
        r = cl(self.u['GERANT']).post(
            url + 'confirm_reception/',
            {'lines': [{'bread_price': self.bp.pk, 'quantity_received': 1}], **extra}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._nodes(t), (self.k2.pk, self.k1.pk, self.u['GERANT'].pk))
        self.assertEqual(t.transfer_status, 'DISPUTED')
        # resolve (fournisseur K2)
        r = cl(self.u2['GERANT']).post(
            url + 'resolve_dispute/',
            {'resolution': 'ALIGN_ON_SENT', 'reason': 'recompte', **extra}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._nodes(t), (self.k2.pk, self.k1.pk, self.u['GERANT'].pk))
        self.assertEqual(t.transfer_status, 'CONFIRMED')

    def test_actions_refused_for_wrong_side_and_outsiders(self):
        t, url = self.mk('PENDING')
        self.assertEqual(cl(self.u['GERANT']).post(url + 'respond_to_request/', {'approved': False},
                                                   format='json').status_code, 403)
        self.assertEqual(cl(self.u3).post(url + 'respond_to_request/', {'approved': False},
                                          format='json').status_code, 404)
        for role in ('FACTURIER', 'LIVREUR'):
            for a in ('respond_to_request', 'confirm_reception', 'resolve_dispute'):
                self.assertEqual(cl(self.u[role]).post(url + a + '/', {}, format='json').status_code, 403)
        t.refresh_from_db()
        self.assertEqual(t.transfer_status, 'PENDING')
