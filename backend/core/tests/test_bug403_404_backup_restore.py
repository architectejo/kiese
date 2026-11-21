"""BUG-403 / BUG-404 : sauvegarde WAL-aware et restauration sûre (desktop).

Teste `backend/desktop_server.py` (fonctions pures, stdlib uniquement) avec
des bases SQLite fictives dans un dossier temporaire.
"""
import gzip
import logging
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

import desktop_server as ds

LOG = logging.getLogger('test.bug403_404')


def _make_wal_db(path: Path, rows):
    """Base WAL dont les écritures restent dans le -wal (pas de checkpoint auto)."""
    conn = sqlite3.connect(str(path))
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA wal_autocheckpoint=0;')
    conn.execute('CREATE TABLE IF NOT EXISTS t (v TEXT)')
    for r in rows:
        conn.execute('INSERT INTO t VALUES (?)', (r,))
    conn.commit()
    return conn  # laissé ouvert : le WAL n'est pas rejoué dans le fichier principal


def _values(path: Path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute('SELECT v FROM t ORDER BY rowid')]
    finally:
        conn.close()


def _gunzip_to(gz: Path, dest: Path):
    with gzip.open(gz, 'rb') as f_in, open(dest, 'wb') as f_out:
        f_out.write(f_in.read())


class BackupWalTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.db = self.dir / 'kiese.sqlite3'
        self.backups = self.dir / 'backups'

    def test_backup_includes_uncheckpointed_wal_data(self):
        conn = _make_wal_db(self.db, ['vente-1', 'vente-2'])
        self.addCleanup(conn.close)
        wal = Path(str(self.db) + '-wal')
        self.assertTrue(wal.exists() and wal.stat().st_size > 0, 'le WAL doit contenir les écritures')
        # Preuve : copier le seul fichier principal (ancien comportement) perd les données.
        naive = self.dir / 'naive.sqlite3'
        naive.write_bytes(self.db.read_bytes())
        naive_rows = []
        try:
            naive_rows = _values(naive)
        except sqlite3.Error:
            pass
        self.assertNotEqual(naive_rows, ['vente-1', 'vente-2'])
        # Même sans le checkpoint préalable, sqlite3.backup() lit le WAL.
        with mock.patch.object(ds, '_checkpoint_wal'):
            dest = ds.backup_database(self.db, self.backups, LOG, label='manuelle', with_seconds=True)
        self.assertIsNotNone(dest)
        self.assertRegex(dest.name, r'^kiese-manuelle-\d{8}-\d{6}\.sqlite3\.gz$')
        restored = self.dir / 'check.sqlite3'
        _gunzip_to(dest, restored)
        self.assertEqual(_values(restored), ['vente-1', 'vente-2'])
        self.assertEqual([p.name for p in self.backups.iterdir()], [dest.name], 'aucun fichier temporaire résiduel')

    def test_backup_without_db_returns_none(self):
        self.assertIsNone(ds.backup_database(self.db, self.backups, LOG))


class RestoreTests(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.db = self.dir / 'kiese.sqlite3'
        self.backups = self.dir / 'backups'
        self.backups.mkdir()

    def _backup_of(self, rows, name):
        src = self.dir / f'src-{name}.sqlite3'
        c = _make_wal_db(src, rows)
        c.close()
        dest = self.backups / name
        with open(src, 'rb') as f_in, gzip.open(dest, 'wb') as f_out:
            f_out.write(f_in.read())
        return dest

    def test_restore_replaces_db_and_keeps_safety_copy(self):
        self._backup_of(['ancien'], 'kiese-20260101-0800.sqlite3.gz')
        conn = _make_wal_db(self.db, ['courant-1', 'courant-2'])
        conn.close()
        safety = ds.restore_database(self.db, self.backups, 'kiese-20260101-0800.sqlite3.gz', LOG)
        self.assertEqual(_values(self.db), ['ancien'])
        self.assertRegex(safety.name, r'^kiese-avant-restauration-.*\.sqlite3\.gz$')
        check = self.dir / 'safety.sqlite3'
        _gunzip_to(safety, check)
        self.assertEqual(_values(check), ['courant-1', 'courant-2'])
        self.assertFalse(Path(str(self.db) + '.restore.tmp').exists())

    def test_corrupted_gzip_is_refused_and_current_db_untouched(self):
        conn = _make_wal_db(self.db, ['courant'])
        conn.close()
        bad = self.backups / 'kiese-20260102-0800.sqlite3.gz'
        good = self._backup_of(['x' * 5000], 'kiese-tmp.sqlite3.gz')
        bad.write_bytes(good.read_bytes()[:40])  # tronqué
        before = self.db.read_bytes()
        with self.assertRaises(ds.RestoreError) as ctx:
            ds.restore_database(self.db, self.backups, bad.name, LOG)
        self.assertIn('corrompue', str(ctx.exception))
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(_values(self.db), ['courant'])
        self.assertFalse(Path(str(self.db) + '.restore.tmp').exists())
        self.assertFalse(any('avant-restauration' in p.name for p in self.backups.iterdir()))

    def test_valid_gzip_but_not_sqlite_is_refused(self):
        conn = _make_wal_db(self.db, ['courant'])
        conn.close()
        bad = self.backups / 'kiese-20260103-0800.sqlite3.gz'
        with gzip.open(bad, 'wb') as f:
            f.write(b'ceci n est pas une base sqlite' * 200)
        with self.assertRaises(ds.RestoreError):
            ds.restore_database(self.db, self.backups, bad.name, LOG)
        self.assertEqual(_values(self.db), ['courant'])

    def test_database_failing_integrity_check_is_refused(self):
        conn = _make_wal_db(self.db, ['courant'])
        conn.close()
        with mock.patch.object(ds, '_integrity_ok', return_value=False):
            self._backup_of(['ancien'], 'kiese-20260104-0800.sqlite3.gz')
            with self.assertRaises(ds.RestoreError):
                ds.restore_database(self.db, self.backups, 'kiese-20260104-0800.sqlite3.gz', LOG)
        self.assertEqual(_values(self.db), ['courant'])

    def test_failed_safety_copy_aborts_without_touching_db(self):
        self._backup_of(['ancien'], 'kiese-20260105-0800.sqlite3.gz')
        conn = _make_wal_db(self.db, ['courant'])
        conn.close()
        with mock.patch.object(ds, 'backup_database', side_effect=OSError('disque plein')):
            with self.assertRaises(ds.RestoreError) as ctx:
                ds.restore_database(self.db, self.backups, 'kiese-20260105-0800.sqlite3.gz', LOG)
        self.assertIn('copie de sécurité', str(ctx.exception))
        self.assertEqual(_values(self.db), ['courant'])

    def test_path_traversal_and_bad_names_are_refused(self):
        for name in (
            '../kiese-x.sqlite3.gz',
            '..\\kiese-x.sqlite3.gz',
            'sub/kiese-x.sqlite3.gz',
            'C:\\kiese-x.sqlite3.gz',
            'autre.sqlite3.gz',
            'kiese-x.sqlite3',
            'kiese-..sqlite3.gz',
            '',
        ):
            with self.subTest(name=name):
                with self.assertRaises(ds.RestoreError):
                    ds.validate_backup_file_name(name)
        self.assertEqual(
            ds.validate_backup_file_name('kiese-avant-restauration-20260101-080000.sqlite3.gz'),
            'kiese-avant-restauration-20260101-080000.sqlite3.gz',
        )

    def test_missing_backup_file(self):
        with self.assertRaises(ds.RestoreError):
            ds.restore_database(self.db, self.backups, 'kiese-inexistant.sqlite3.gz', LOG)

    def test_restore_when_no_current_db(self):
        self._backup_of(['ancien'], 'kiese-20260106-0800.sqlite3.gz')
        ds.restore_database(self.db, self.backups, 'kiese-20260106-0800.sqlite3.gz', LOG)
        self.assertEqual(_values(self.db), ['ancien'])
