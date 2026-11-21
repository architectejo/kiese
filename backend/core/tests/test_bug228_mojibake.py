"""BUG-228 : réparation du double encodage des prénoms (données fictives)."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.management.commands.fix_mojibake_names import fix_mojibake
from core.models import User


def _moji(s):
    return s.encode('utf-8').decode('cp1252')


class FixMojibakeTests(TestCase):
    def setUp(self):
        self.bad = User.objects.create_user(username='b228_bad', password='x-pass-123',
                                            first_name=_moji('Gérant'), last_name='Coq')
        self.ok = User.objects.create_user(username='b228_ok', password='x-pass-123',
                                           first_name='Gérant', last_name='Élodie')

    def run_cmd(self, *args):
        out = StringIO()
        call_command('fix_mojibake_names', *args, stdout=out)
        return out.getvalue()

    def test_fonction_pure(self):
        self.assertEqual(fix_mojibake('GÃ©rant'), 'Gérant')
        for ok in ('Gérant', 'Élodie', 'Kiese', '', 'Ça va', 'Noël'):
            self.assertEqual(fix_mojibake(ok), ok)

    def test_dry_run_par_defaut_ne_modifie_rien(self):
        self.assertEqual(self.bad.first_name, 'GÃ©rant')
        self.run_cmd()
        self.bad.refresh_from_db()
        self.assertEqual(self.bad.first_name, 'GÃ©rant')

    def test_apply_repare_et_est_idempotent(self):
        self.run_cmd('--apply')
        self.bad.refresh_from_db(); self.ok.refresh_from_db()
        self.assertEqual(self.bad.first_name, 'Gérant')
        self.assertEqual(self.ok.first_name, 'Gérant')
        self.assertEqual(self.ok.last_name, 'Élodie')
        out = self.run_cmd('--apply')
        self.assertIn('0 enregistrement', out)
        self.bad.refresh_from_db()
        self.assertEqual(self.bad.first_name, 'Gérant')
