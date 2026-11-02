"""
BUG-083 (« ventes passées », remarque.md l.360) : `Config.allow_backdated_sales`.

Décision client §1/§5 (2026-10-29) : réglage désactivé par défaut, modifiable
uniquement par ADMIN/DIRECTION via `/api/core/config/` (même permission que
les autres réglages globaux, ex. `best_client_threshold`).
"""
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Config
from core.testing import make_user


class ConfigAllowBackdatedSalesTests(TestCase):

    def setUp(self):
        self.admin = make_user(role='ADMIN', username='admin_bug083')
        self.direction = make_user(role='DIRECTION', username='direction_bug083')
        self.gerant = make_user(role='GERANT', username='gerant_bug083')
        self.facturier = make_user(role='FACTURIER', username='facturier_bug083')

    def test_disabled_by_default(self):
        self.assertFalse(Config.get_instance().allow_backdated_sales)

    def test_direction_can_enable_it(self):
        api = APIClient()
        api.force_authenticate(self.direction)
        resp = api.patch('/api/core/config/', {'allow_backdated_sales': True}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(Config.get_instance().allow_backdated_sales)

    def test_admin_can_enable_it(self):
        api = APIClient()
        api.force_authenticate(self.admin)
        resp = api.patch('/api/core/config/', {'allow_backdated_sales': True}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(Config.get_instance().allow_backdated_sales)

    def test_gerant_cannot_enable_it(self):
        """Décision client §5 : réservé à ADMIN/DIRECTION, pas au gérant."""
        api = APIClient()
        api.force_authenticate(self.gerant)
        resp = api.patch('/api/core/config/', {'allow_backdated_sales': True}, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertFalse(Config.get_instance().allow_backdated_sales)

    def test_facturier_cannot_enable_it(self):
        api = APIClient()
        api.force_authenticate(self.facturier)
        resp = api.patch('/api/core/config/', {'allow_backdated_sales': True}, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertFalse(Config.get_instance().allow_backdated_sales)

    def test_facturier_can_read_the_flag(self):
        """Décision client §5 : une fois activé, tout rôle habilité à
        facturer doit pouvoir LIRE le réglage (pour afficher/masquer le
        champ de date dans Clients.tsx/Sales.tsx) — seule l'ÉCRITURE est
        restreinte."""
        Config.get_instance()
        config = Config.get_instance()
        config.allow_backdated_sales = True
        config.save(update_fields=['allow_backdated_sales'])

        api = APIClient()
        api.force_authenticate(self.facturier)
        resp = api.get('/api/core/config/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data['allow_backdated_sales'])
