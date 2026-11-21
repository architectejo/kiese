"""Verification BUG-228 (testeur-permissions, 2026-11-21). Donnees fictives, tests independants du dev."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.db.models.query import QuerySet
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from core.management.commands.fix_mojibake_names import fix_mojibake
from core.models import ActivityLog, Node, User


def cp(s):
    return s.encode('utf-8').decode('cp1252')


def lat(s):
    return s.encode('utf-8').decode('latin-1')


class PureFunction(TestCase):
    def test_textes_corrects_intacts(self):
        for ok in ('Gérant', 'Élodie', 'Noël', 'Ça va', 'Zoé', 'Привет', 'Иван', '😀 ok', '', None,
                   'ASCII', 'Ã', 'Œuvre', 'naïve façade', 'À côté', '日本語'):
            self.assertEqual(fix_mojibake(ok), ok, repr(ok))

    def test_vrais_cas_cp1252(self):
        self.assertEqual(fix_mojibake('GÃ©rant'), 'Gérant')
        self.assertEqual(fix_mojibake(cp('Élodie')), 'Élodie')
        self.assertEqual(fix_mojibake('Ã‰lodie'), 'Élodie')
        self.assertEqual(fix_mojibake(cp('Noël Zoé')), 'Noël Zoé')

    def test_vrais_cas_latin1(self):
        # É = C3 89 : 0x89 est un caractere de controle en latin-1 pur
        self.assertEqual(fix_mojibake(lat('Élodie')), 'Élodie')
        self.assertEqual(fix_mojibake(lat('Gérant')), 'Gérant')

    def test_idempotence_fonction(self):
        for s in ('GÃ©rant', cp('Élodie'), lat('Élodie'), 'Gérant'):
            once = fix_mojibake(s)
            self.assertEqual(fix_mojibake(once), once)

    def test_emoji_double_encode_ne_leve_pas(self):
        r = fix_mojibake(lat('😀'))
        self.assertIn(r, ('😀', lat('😀')))


class CommandTests(TestCase):
    def setUp(self):
        self.bad = User.objects.create_user(username='v228_bad', password='x-pass-123',
                                            first_name=cp('Gérant'), last_name=lat('Élodie'),
                                            email='Ã©@x.cd')
        self.ok = User.objects.create_user(username='v228_ok', password='x-pass-123',
                                           first_name='Noël', last_name='Ça va')
        self.empty = User.objects.create_user(username='v228_empty', password='x-pass-123',
                                              first_name='', last_name='')
        self.node = Node.objects.create(code='V2', name=cp('Boulangerie Éclair'), address='Av. Tabora')
        self.log = ActivityLog.objects.create(action='X', user_display=cp('Gérant Coq'))

    def run_cmd(self, *args):
        out = StringIO()
        call_command('fix_mojibake_names', *args, stdout=out)
        return out.getvalue()

    def snap(self):
        return (list(User.objects.order_by('username').values()) + list(Node.objects.values())
                + list(ActivityLog.objects.values()))

    def test_dry_run_defaut_zero_ecriture(self):
        before = self.snap()
        with CaptureQueriesContext(connection) as q:
            out = self.run_cmd()
        self.assertEqual(self.snap(), before)
        writes = [x['sql'] for x in q.captured_queries
                  if x['sql'].lstrip().upper().startswith(('UPDATE', 'INSERT', 'DELETE'))]
        self.assertEqual(writes, [])
        self.assertIn('simulation', out)
        self.assertIn('3 enregistrement', out)

    def test_dry_run_explicite_et_dry_run_prime_sur_apply(self):
        before = self.snap()
        self.run_cmd('--dry-run')
        self.run_cmd('--apply', '--dry-run')
        self.assertEqual(self.snap(), before)

    def test_apply_ecrit(self):
        out = self.run_cmd('--apply')
        self.assertIn('3 enregistrement(s) corrigé', out)
        self.bad.refresh_from_db()
        self.node.refresh_from_db()
        self.log.refresh_from_db()
        self.assertEqual((self.bad.first_name, self.bad.last_name), ('Gérant', 'Élodie'))
        self.assertEqual(self.node.name, 'Boulangerie Éclair')
        self.assertEqual(self.log.user_display, 'Gérant Coq')

    def test_apply_idempotent(self):
        self.run_cmd('--apply')
        s1 = self.snap()
        out = self.run_cmd('--apply')
        self.assertIn('0 enregistrement', out)
        self.assertEqual(self.snap(), s1)

    def test_hors_perimetre_et_corrects_intacts(self):
        before_ok = User.objects.filter(pk=self.ok.pk).values().get()
        before_empty = User.objects.filter(pk=self.empty.pk).values().get()
        self.run_cmd('--apply')
        self.assertEqual(User.objects.filter(pk=self.ok.pk).values().get(), before_ok)
        self.assertEqual(User.objects.filter(pk=self.empty.pk).values().get(), before_empty)
        self.bad.refresh_from_db()
        self.assertEqual(self.bad.email, 'Ã©@x.cd')
        self.assertEqual(self.bad.username, 'v228_bad')
        self.assertTrue(self.bad.check_password('x-pass-123'))

    def test_pas_de_signal_ni_save(self):
        from django.db.models import signals
        calls = []

        def h(sender, **kw):
            calls.append(sender)

        signals.post_save.connect(h, weak=False)
        signals.pre_save.connect(h, weak=False)
        try:
            with mock.patch.object(User, 'save', side_effect=AssertionError('save interdit')):
                self.run_cmd('--apply')
        finally:
            signals.post_save.disconnect(h)
            signals.pre_save.disconnect(h)
        self.assertEqual(calls, [])

    def test_updated_at_et_is_synced_inchanges(self):
        pass
        fields = [f.name for f in Node._meta.concrete_fields if f.name in ('updated_at', 'is_synced', 'created_at')] or ['code']
        before = Node.objects.filter(pk=self.node.pk).values(*fields).get()
        self.run_cmd('--apply')
        self.assertEqual(Node.objects.filter(pk=self.node.pk).values(*fields).get(), before)

    def test_atomique_rollback_si_erreur(self):
        real_update = QuerySet.update

        def boom(qs, **kw):
            if qs.model is Node:
                raise RuntimeError('panne simulee')
            return real_update(qs, **kw)

        with mock.patch.object(QuerySet, 'update', boom):
            with self.assertRaises(RuntimeError):
                self.run_cmd('--apply')
        self.bad.refresh_from_db()
        self.assertEqual(self.bad.first_name, cp('Gérant'))
