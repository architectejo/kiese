"""BUG-410 : une copie de sécurité de restauration ne doit jamais en écraser une autre."""
import gzip
import logging
import sqlite3
import tempfile
from datetime import datetime as real_datetime
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

import desktop_server as ds

LOG = logging.getLogger('test.bug410')


def _make_db(path: Path, rows: int, prefix='g'):
    conn = sqlite3.connect(str(path))
    conn.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)')
    for i in range(rows):
        conn.execute('INSERT INTO t (v) VALUES (?)', (f'{prefix}{i}',))
    conn.commit()
    conn.close()


def _count(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute('SELECT COUNT(*) FROM t').fetchone()[0]
    finally:
        conn.close()


class _FrozenDatetime(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2026, 11, 21, 10, 0, 0, 123)


class Bug410SafetyCopyCollision(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)
        self.bk = self.d / 'backups'
        self.bk.mkdir()
        self.db = self.d / 'db.sqlite3'
        _make_db(self.db, 20, 'orig')
        src = self.d / 'src.sqlite3'
        _make_db(src, 2)
        with gzip.open(self.bk / 'kiese-a.sqlite3.gz', 'wb') as f:
            f.write(src.read_bytes())

    def test_meme_seconde_deux_copies_distinctes_et_restaurables(self):
        with mock.patch.object(ds, 'datetime', _FrozenDatetime):
            s1 = ds.restore_database(self.db, self.bk, 'kiese-a.sqlite3.gz', LOG)
            s2 = ds.restore_database(self.db, self.bk, 'kiese-a.sqlite3.gz', LOG)
        self.assertNotEqual(s1.name, s2.name)
        self.assertTrue(s1.is_file() and s2.is_file())
        for s in (s1, s2):
            self.assertEqual(ds.validate_backup_file_name(s.name), s.name)
        ds.restore_database(self.db, self.bk, s1.name, LOG)
        self.assertEqual(_count(self.db), 20)

    def test_trois_restaurations_meme_seconde(self):
        with mock.patch.object(ds, 'datetime', _FrozenDatetime):
            names = {ds.restore_database(self.db, self.bk, 'kiese-a.sqlite3.gz', LOG).name for _ in range(3)}
        self.assertEqual(len(names), 3)

    def test_sauvegarde_normale_inchangee(self):
        p = ds.backup_database(self.db, self.bk, LOG)
        self.assertRegex(p.name, r'^kiese-\d{8}-\d{4}\.sqlite3\.gz$')
