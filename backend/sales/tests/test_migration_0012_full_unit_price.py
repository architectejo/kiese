"""Migration de données sales/0012 (rétro-remplissage de `full_unit_price`, BUG-508)."""
from importlib import import_module

from django.apps import apps as global_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from core.testing import make_bread_price, make_client, make_node, make_user
from sales.models import Invoice, InvoiceLine

MIG = import_module('sales.migrations.0012_bug508_backfill_full_unit_price')


class Backfill0012Tests(TransactionTestCase):
    def setUp(self):
        self.node = make_node(code='MG')
        self.bp = make_bread_price('MG300', 'Pain 300', 300)
        self.fa = make_user('FACTURIER', node=self.node, team='A', username='mg_fa')
        self.cl = make_client(self.node)

    def _line(self, soldee, qty=1, price=None):
        inv = Invoice.objects.create(node=self.node, client=self.cl, facturier=self.fa, team='A',
                                     status='PENDING', payment_type='CREDIT', is_soldee=soldee)
        line = InvoiceLine.objects.create(invoice=inv, bread_price=self.bp, quantity=qty)
        fields = {'full_unit_price': None}
        if price is not None:
            fields['unit_price'] = price
        InvoiceLine.objects.filter(pk=line.pk).update(**fields)
        return line.pk

    def _run(self):
        MIG.backfill(global_apps, connection.schema_editor())

    def _get(self, pk):
        return InvoiceLine.objects.values_list('unit_price', 'full_unit_price').get(pk=pk)

    def test_cas_types(self):
        normale = self._line(False, price=300)
        solde_plein = self._line(True, price=225)       # 0,75 x 300, tarif inchangé -> 300
        # tarif passé à 300 depuis ; ligne figée à 0,75 x 201 = 151 (tarif d'origine 201)
        non_reconstituable = self._line(True, price=151)
        sans_prix = self._line(False, price=0)
        sans_prix_soldee = self._line(True, price=0)
        self._run()
        self.assertEqual(self._get(normale), (300, 300))
        self.assertEqual(self._get(solde_plein), (225, 300))
        # 151 / 0,75 = 201,33 -> 201 : écart <= 1 FC par rapport au tarif d'origine
        self.assertLessEqual(abs(self._get(non_reconstituable)[1] - 201), 1)
        self.assertEqual(self._get(sans_prix), (0, 0))
        self.assertEqual(self._get(sans_prix_soldee)[1], 0)

    def test_idempotence_et_lignes_deja_remplies(self):
        a = self._line(True, price=225)
        b = self._line(False, price=300)
        deja = self._line(True, price=225)
        InvoiceLine.objects.filter(pk=deja).update(full_unit_price=999)  # remplie par l'ancienne 0011
        self._run()
        first = [self._get(p) for p in (a, b, deja)]
        self._run()
        self.assertEqual(first, [self._get(p) for p in (a, b, deja)])
        self.assertEqual(self._get(deja)[1], 999)

    def test_lots_multiples(self):
        old = MIG.BATCH
        MIG.BATCH = 2
        try:
            pks = [self._line(True, price=225) for _ in range(5)]
            self._run()
        finally:
            MIG.BATCH = old
        self.assertTrue(all(self._get(p)[1] == 300 for p in pks))

    def test_chaine_migrations_retour_0011_puis_0012(self):
        pk = self._line(False, price=300)
        deja = self._line(True, price=225)
        InvoiceLine.objects.filter(pk=deja).update(full_unit_price=777)
        executor = MigrationExecutor(connection)
        executor.migrate([('sales', '0011_bug508_full_unit_price')])  # 0012 inversée (noop)
        self.assertIsNone(InvoiceLine.objects.get(pk=pk).full_unit_price)
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        self.assertEqual(self._get(pk), (300, 300))
        self.assertEqual(self._get(deja)[1], 777)  # no-op sur les lignes déjà remplies
