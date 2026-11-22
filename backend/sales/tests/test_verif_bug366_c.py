"""Vérification indépendante BUG-366 (Dev C) : migrations sales 0011 (schéma) + 0012 (rétro-remplissage).

Méthode : les données sont créées à l'état courant, puis on revient à 0010 (colonne supprimée),
on remonte 0011 puis 0012 avec `MigrationExecutor`, et l'on compare avant/après.
"""
from decimal import Decimal
from importlib import import_module
from unittest import mock

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Sum
from django.test import TransactionTestCase

from clients.models import Client
from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine

MIG = import_module('sales.migrations.0012_bug508_backfill_full_unit_price')
M0010 = ('sales', '0010_bug318_not_served')
M0011 = ('sales', '0011_bug508_full_unit_price')
M0012 = ('sales', '0012_bug508_backfill_full_unit_price')


def _migrate(target):
    ex = MigrationExecutor(connection)
    ex.migrate([target] if isinstance(target, tuple) else target)
    return MigrationExecutor(connection)


class Verif366Tests(TransactionTestCase):
    def setUp(self):
        self.node = make_node(code='V6')
        self.bp = make_bread_price('V6P300', 'Pain 300', 300)
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='v6_fa')
        self.cl = make_client(self.node)

    def tearDown(self):
        # Toujours laisser la base au dernier état pour les autres tests.
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())

    def _line(self, soldee, price, qty=2):
        inv = Invoice.objects.create(node=self.node, client=self.cl, facturier=self.fa, team='A',
                                     status='PENDING', payment_type='CREDIT', is_soldee=soldee)
        ln = InvoiceLine.objects.create(invoice=inv, bread_price=self.bp, quantity=qty)
        InvoiceLine.objects.filter(pk=ln.pk).update(unit_price=price, line_total=Decimal(price * qty))
        Invoice.objects.filter(pk=inv.pk).update(order_total=Decimal(price * qty))
        return ln.pk

    def _snapshot(self):
        return {
            'lines': list(InvoiceLine.objects.order_by('pk').values_list('pk', 'unit_price', 'line_total', 'quantity')),
            'inv': list(Invoice.objects.order_by('pk').values_list('pk', 'order_total', 'payment_amount')),
            'sum_total': InvoiceLine.objects.aggregate(s=Sum('line_total'))['s'],
            'debt': list(Client.objects.order_by('pk').values_list('pk', 'current_debt')),
        }

    def _full(self, pks):
        return {p: InvoiceLine.objects.values_list('full_unit_price', flat=True).get(pk=p) for p in pks}

    # -- chaîne complète ----------------------------------------------------------------
    def test_chaine_0010_0011_0012_cas_types_et_invariants(self):
        normale = self._line(False, 300)
        solde_plein = self._line(True, 225)        # 225 -> 300 (multiple de 4)
        solde_non_rec = self._line(True, 151)      # tarif courant 300 incompatible -> 151/0,75 = 201
        prix0 = self._line(False, 0)
        prix0_solde = self._line(True, 0)
        avant = self._snapshot()

        _migrate(M0010)
        ex = _migrate(M0011)
        # Après 0011 seul : colonne présente mais vide (aucun rétro-remplissage).
        Hist = ex.loader.project_state([M0011]).apps.get_model('sales', 'InvoiceLine')
        self.assertEqual(Hist.objects.filter(full_unit_price__isnull=False).count(), 0)
        _migrate(M0012)

        full = self._full([normale, solde_plein, solde_non_rec, prix0, prix0_solde])
        self.assertEqual(full[normale], 300)
        self.assertEqual(full[solde_plein], 300)
        self.assertEqual(full[solde_non_rec], 201)
        self.assertLessEqual(abs(full[solde_non_rec] - 201), 1)
        self.assertEqual(full[prix0], 0)
        self.assertEqual(full[prix0_solde], 0)
        self.assertEqual(avant, self._snapshot())   # rien d'autre n'a bougé

    def test_lots_multiples_via_chaine(self):
        pks = [self._line(True, 225, qty=1) for _ in range(7)] + [self._line(False, 300) for _ in range(3)]
        _migrate(M0010)
        _migrate(M0011)
        with mock.patch.object(MIG, 'BATCH', 3):
            _migrate(M0012)
        self.assertTrue(all(v is not None for v in self._full(pks).values()))
        self.assertEqual(set(self._full(pks[:7]).values()), {300})
        self.assertEqual(set(self._full(pks[7:]).values()), {300})

    def test_ancienne_0011_deja_appliquee_colonne_remplie(self):
        deja_normale = self._line(False, 300)
        deja_solde = self._line(True, 225)
        vide = self._line(True, 225)
        _migrate(M0010)
        ex = _migrate(M0011)
        Hist = ex.loader.project_state([M0011]).apps.get_model('sales', 'InvoiceLine')
        Hist.objects.filter(pk=deja_normale).update(full_unit_price=555)
        Hist.objects.filter(pk=deja_solde).update(full_unit_price=888)
        _migrate(M0012)
        full = self._full([deja_normale, deja_solde, vide])
        self.assertEqual(full[deja_normale], 555)
        self.assertEqual(full[deja_solde], 888)
        self.assertEqual(full[vide], 300)

    def test_interruption_puis_relance(self):
        pks = [self._line(True, 225, qty=1) for _ in range(6)]
        normale = self._line(False, 300)
        avant = self._snapshot()
        _migrate(M0010)
        ex = _migrate(M0011)
        Hist = ex.loader.project_state([M0011]).apps.get_model('sales', 'InvoiceLine')

        class Boom(Exception):
            pass

        real_filter = Hist.objects.filter
        calls = {'n': 0}
        orig_update = type(Hist.objects.all()).update

        def flaky(self, **kw):
            # laisse passer l'UPDATE des ventes normales + 2 soldées, puis casse
            calls['n'] += 1
            if calls['n'] > 3:
                raise Boom()
            return orig_update(self, **kw)

        class _Apps:
            def get_model(_s, a, m):
                return Hist

        with mock.patch.object(type(Hist.objects.all()), 'update', flaky):
            with self.assertRaises(Boom):
                MIG.backfill(_Apps(), None)
        partiel = InvoiceLine.objects.filter(full_unit_price__isnull=False).count()
        self.assertTrue(0 < partiel < 7)           # lots déjà validés conservés (non atomique)
        _migrate(M0012)                              # relance : termine
        self.assertEqual(set(self._full(pks).values()), {300})
        self.assertEqual(self._full([normale])[normale], 300)
        self.assertEqual(avant, self._snapshot())

    def test_idempotence_double_execution(self):
        pks = [self._line(True, 225), self._line(False, 300)]
        _migrate(M0010)
        ex = _migrate(M0011)
        Hist = ex.loader.project_state([M0011]).apps.get_model('sales', 'InvoiceLine')

        class _Apps:
            def get_model(_s, a, m):
                return Hist
        MIG.backfill(_Apps(), None)
        first = self._full(pks)
        MIG.backfill(_Apps(), None)
        self.assertEqual(first, self._full(pks))

    def test_reverse_0011_puis_0010_sans_perte(self):
        self._line(False, 300)
        self._line(True, 225)
        avant = self._snapshot()
        _migrate(M0010)
        ex = MigrationExecutor(connection)
        self.assertNotIn(M0011, ex.loader.applied_migrations)
        self.assertEqual(avant, self._snapshot())
        _migrate(M0011)
        _migrate(M0012)
        self.assertEqual(avant, self._snapshot())
        # retour 0011 : 0012 inversée = noop, colonne conservée
        _migrate(M0011)
        ex = MigrationExecutor(connection)
        self.assertNotIn(M0012, ex.loader.applied_migrations)
        self.assertEqual(InvoiceLine.objects.filter(full_unit_price=300).count(), 2)

    def test_sql_update_ventes_normales(self):
        """Capture du SQL de l'UPDATE unique (analyse de plan PostgreSQL : voir rapport, non testable ici)."""
        from django.db import connection as c
        from django.test.utils import CaptureQueriesContext
        self._line(False, 300)
        _migrate(M0010)
        ex = _migrate(M0011)
        Hist = ex.loader.project_state([M0011]).apps.get_model('sales', 'InvoiceLine')

        class _Apps:
            def get_model(_s, a, m):
                return Hist
        with CaptureQueriesContext(c) as ctx:
            MIG.backfill(_Apps(), None)
        updates = [q['sql'] for q in ctx.captured_queries if q['sql'].startswith('UPDATE')]
        self.assertTrue(updates)
        self.assertIn('"full_unit_price" = "sales_invoiceline"."unit_price"', updates[0])
        self.assertIn(' IN (', updates[0])   # sous-requête IN documentée dans le rapport


class MigrationHygiene(TransactionTestCase):
    def test_makemigrations_check(self):
        from django.core.management import call_command
        call_command('makemigrations', '--check', '--dry-run', verbosity=0)

    def test_0011_schema_seul(self):
        mod = import_module('sales.migrations.0011_bug508_full_unit_price')
        ops = mod.Migration.operations
        self.assertEqual([type(o).__name__ for o in ops], ['AddField'])
        self.assertTrue(ops[0].field.null)

    def test_0012_non_atomique_et_reversible(self):
        self.assertFalse(MIG.Migration.atomic)
        self.assertTrue(MIG.Migration.operations[0].reversible)
        self.assertEqual(MIG.Migration.dependencies, [M0011])
