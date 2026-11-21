"""Verification independante BUG-410 (testeur-installation, 2026-11-21e)."""
import gzip
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime as real_datetime
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

import desktop_server as ds

LOG = logging.getLogger('test.verif410')
ROOT = Path(__file__).resolve().parents[3]


class _Frozen(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2026, 11, 21, 10, 0, 0, 5)


def _mk(path: Path, rows: int, prefix='g'):
    c = sqlite3.connect(str(path))
    c.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)')
    for i in range(rows):
        c.execute('INSERT INTO t (v) VALUES (?)', (f'{prefix}{i}',))
    c.commit()
    c.close()


def _n(path: Path) -> int:
    c = sqlite3.connect(str(path))
    try:
        return c.execute('SELECT COUNT(*) FROM t').fetchone()[0]
    finally:
        c.close()


class _Base(SimpleTestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.d = Path(self._td.name)
        self.bk = self.d / 'backups'
        self.bk.mkdir()
        self.db = self.d / 'kiese.sqlite3'
        _mk(self.db, 20, 'orig')
        src = self.d / 's.sqlite3'
        _mk(src, 2)
        with gzip.open(self.bk / 'kiese-a.sqlite3.gz', 'wb') as f:
            f.write(src.read_bytes())
        src.unlink()

    def _restore(self):
        return ds.restore_database(self.db, self.bk, 'kiese-a.sqlite3.gz', LOG)

    def _rows_of(self, gz: Path) -> int:
        out = self.d / 'chk.sqlite3'
        with gzip.open(gz, 'rb') as f, open(out, 'wb') as g:
            shutil.copyfileobj(f, g)
        try:
            return _n(out)
        finally:
            out.unlink()


class Bug410Verification(_Base):
    def test_ancien_comportement_simule_ecrase_la_copie(self):
        """Preuve : sans `unique`, la meme seconde ecrase la 1re copie."""
        real = ds.backup_database

        def old(*a, **k):
            k['unique'] = False
            return real(*a, **k)

        with mock.patch.object(ds, 'datetime', _Frozen), \
                mock.patch.object(ds, 'backup_database', side_effect=old):
            s1 = self._restore()
            s2 = self._restore()
        self.assertEqual(s1.name, s2.name)  # collision = ancien bug
        self.assertEqual(self._rows_of(s1), 2)  # les 20 lignes d'origine sont perdues

    def test_six_restaurations_meme_seconde_aucune_perte(self):
        with mock.patch.object(ds, 'datetime', _Frozen):
            safeties = [self._restore() for _ in range(6)]
        names = [s.name for s in safeties]
        self.assertEqual(len(set(names)), 6)
        self.assertEqual(names[0], 'kiese-avant-restauration-20261121-100000.sqlite3.gz')
        self.assertEqual(names[1], 'kiese-avant-restauration-20261121-100000-2.sqlite3.gz')
        self.assertEqual(names[5], 'kiese-avant-restauration-20261121-100000-6.sqlite3.gz')
        for s in safeties:
            self.assertTrue(ds.BACKUP_NAME_RE.fullmatch(s.name))
            self.assertEqual(ds.validate_backup_file_name(s.name), s.name)
            self.assertGreater(s.stat().st_size, 0)
        self.assertEqual(self._rows_of(safeties[0]), 20)
        for s in safeties[1:]:
            self.assertEqual(self._rows_of(s), 2)
        self.assertEqual([p.name for p in self.d.rglob('*') if p.name.endswith(('.tmp', '.part'))], [])

    def test_nom_liste_par_le_glob_et_copie_2_restaurable(self):
        with mock.patch.object(ds, 'datetime', _Frozen):
            self._restore()
            s2 = self._restore()
        listed = {p.name for p in self.bk.glob('kiese-*.sqlite3.gz')}
        self.assertIn(s2.name, listed)
        self.assertTrue(s2.name.endswith('-2.sqlite3.gz'))
        ds.restore_database(self.db, self.bk, s2.name, LOG)
        self.assertEqual(_n(self.db), 2)
        self.assertTrue(ds._integrity_ok(self.db))

    def test_rotation_ne_supprime_que_les_anciennes(self):
        with mock.patch.object(ds, 'datetime', _Frozen):
            s1 = self._restore()
            s2 = self._restore()
        old = self.bk / 'kiese-avant-restauration-20200101-000000.sqlite3.gz'
        shutil.copy(s1, old)
        t = time.time() - 40 * 86400
        os.utime(old, (t, t))
        ds._rotate_backups(self.bk, LOG)
        self.assertFalse(old.exists())
        self.assertTrue(s1.exists() and s2.exists())
        self.assertTrue((self.bk / 'kiese-a.sqlite3.gz').exists())

    def test_pas_de_collision_avec_sauvegarde_quotidienne(self):
        with mock.patch.object(ds, 'datetime', _Frozen):
            daily = ds.backup_database(self.db, self.bk, LOG)
            s = self._restore()
        self.assertEqual(daily.name, 'kiese-20261121-1000.sqlite3.gz')
        self.assertNotEqual(daily.name, s.name)
        self.assertTrue(daily.exists() and s.exists())

    def test_labels_differents_meme_instant_pas_de_suffixe(self):
        with mock.patch.object(ds, 'datetime', _Frozen):
            a = ds.backup_database(self.db, self.bk, LOG, label='pre-migration', with_seconds=True, unique=True)
            b = ds.backup_database(self.db, self.bk, LOG, label='avant-restauration', with_seconds=True, unique=True)
        self.assertNotEqual(a.name, b.name)
        self.assertFalse(b.name.endswith('-2.sqlite3.gz'))


class Bug410Typescript(SimpleTestCase):
    def test_regex_ts_executee_par_node(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node absent')
        src = (ROOT / 'desktop' / 'src' / 'backupNames.ts').read_text(encoding='utf-8')
        rx = [ln for ln in src.splitlines() if ln.startswith('const BACKUP_NAME_RE')][0]
        js = rx.replace('const BACKUP_NAME_RE =', 'const R =').rstrip(';') + ';' + (
            "const ok=['kiese-avant-restauration-20261121-100000-2.sqlite3.gz',"
            "'kiese-avant-restauration-20261121-100000-12.sqlite3.gz'];"
            "const ko=['../kiese-a.sqlite3.gz','kiese-a.sqlite3','kiese-a.sqlite3.gz.part'];"
            "process.exit(ok.every(n=>R.test(n))&&ko.every(n=>!R.test(n))?0:1)")
        r = subprocess.run([node, '-e', js], capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
