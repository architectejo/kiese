"""BUG-365 : `reconciliation` renvoie le nœud réellement utilisé, pas l'écho du paramètre."""
from core.tests.test_permissions_regression_2026_11_19 import cl, mk
from core.tests.test_verif_isolation_a_c import IsoBase

URL = '/api/production/sessions/reconciliation/'


class ReconciliationNodeLabel(IsoBase):
    def test_gerant_forged_node_param_echoes_own_node(self):
        r = cl(self.u['GERANT']).get(f'{URL}?node={self.k2.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['node'], self.k1.pk)

    def test_gerant_without_param_echoes_own_node(self):
        self.assertEqual(cl(self.u['GERANT']).get(URL).data['node'], self.k1.pk)

    def test_node_less_non_hq_echoes_none(self):
        r = cl(mk('orph365_g', 'GERANT', None)).get(f'{URL}?node={self.k2.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['node'])

    def test_headquarters_node_filter_echoed(self):
        r = cl(self.u['DIRECTION']).get(f'{URL}?node={self.k2.pk}') if 'DIRECTION' in self.u else None
        if r is not None:
            self.assertEqual(str(r.data['node']), str(self.k2.pk))
