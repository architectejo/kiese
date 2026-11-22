"""BUG-522 : les boulangeries, l'auteur et les quantités d'en-tête d'un transfert
sont immuables après création (PATCH/PUT)."""
from core.tests.test_permissions_regression_2026_11_19 import cl
from core.tests.test_verif_isolation_a_c import IsoBase
from production.models import BreadTransfer, BreadTransferLine


class TransferImmutableFields(IsoBase):
    def _pending(self):
        t = BreadTransfer.objects.create(from_node=self.k2, to_node=self.k1,
                                         initiated_by=self.u['GERANT'], node_origin='P1')
        BreadTransferLine.objects.create(transfer=t, bread_price=self.bp, quantity_sent=2)
        return t, f'/api/production/transfers/{t.pk}/'

    def _assert_untouched(self, t):
        t.refresh_from_db()
        self.assertEqual((t.from_node_id, t.to_node_id, t.initiated_by_id),
                         (self.k2.pk, self.k1.pk, self.u['GERANT'].pk))
        self.assertEqual(t.transfer_status, 'PENDING')

    def test_patch_nodes_refused_with_french_detail(self):
        g = cl(self.u['GERANT'])
        t, url = self._pending()
        for body in ({'to_node': self.k3.pk}, {'from_node': self.k3.pk}, {'initiated_by': self.u3.pk},
                     {'quantity_sent': 99}):
            r = g.patch(url, body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.content))
            self.assertIn('detail', r.data, body)
            self._assert_untouched(t)

    def test_put_rewiring_refused(self):
        g = cl(self.u['GERANT'])
        t, url = self._pending()
        r = g.put(url, {'from_node': self.k3.pk, 'to_node': self.k1.pk}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self._assert_untouched(t)

    def test_unchanged_nodes_and_notes_still_allowed(self):
        g = cl(self.u['GERANT'])
        t, url = self._pending()
        r = g.patch(url, {'from_node': self.k2.pk, 'to_node': self.k1.pk, 'notes': 'urgent'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        t.refresh_from_db()
        self.assertEqual(t.notes, 'urgent')
        self._assert_untouched(t)

    def test_status_not_writable(self):
        g = cl(self.u['GERANT'])
        t, url = self._pending()
        g.patch(url, {'transfer_status': 'CONFIRMED', 'confirmed_by': self.u['GERANT'].pk}, format='json')
        t.refresh_from_db()
        self.assertEqual(t.transfer_status, 'PENDING')
        self.assertIsNone(t.confirmed_by_id)

    def test_supplier_side_cannot_rewire_either(self):
        t, url = self._pending()
        r = cl(self.u2['GERANT']).patch(url, {'to_node': self.k3.pk}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        self._assert_untouched(t)
