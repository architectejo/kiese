"""Vérification indépendante BUG-403 / BUG-404 (testeur-installation).

Cherche à casser `desktop_server.backup_database` / `restore_database` avec
des bases SQLite fictives dans un dossier temporaire.
"""
import gzip
import hashlib
import io
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

from django.test import SimpleTestCase

import desktop_server as ds

LOG = logging.getLogger('test.verif403_404')


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _wal_db(path: Path, n: int, prefix='r'):
    """Base WAL avec écritures NON checkpointées ; connexion renvoyée ouverte."""
    c = sqlite3.connect(str(path))
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA wal_autocheckpoint=0')
    c.execute('CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)')
    for i in range(n):
        c.execute('INSERT INTO t (v) VALUES (?)', (f'{prefix}{i}',))
    c.commit()
    return c


def _rows(path: Path):
    c = sqlite3.connect(str(path))
    try:
        return [tuple(r) for r in c.execute('SELECT id, v FROM t ORDER BY id')]
    finally:
        c.close()


def _write_gz(path: Path, raw: bytes):
    with gzip.open(path, 'wb') as f:
        f.write(raw)


def _valid_sqlite_bytes(tmp: Path, n=3) -> bytes:
    p = tmp / '_src.sqlite3'
    c = sqlite3.connect(str(p))
    c.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)')
    for i in range(n):
        c.execute('INSERT INTO t (v) VALUES (?)', (f'g{i}',))
    c.commit()
    c.close()
    data = p.read_bytes()
    p.unlink()
    return data


class VerifBackupRestore(SimpleTestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.d = Path(self._td.name)
        self.db = self.d / 'kiese.sqlite3'
        self.bk = self.d / 'backups'
        self.bk.mkdir()

    def _leftovers(self):
        return sorted(
            p.name for p in list(self.d.iterdir()) + list(self.bk.iterdir())
            if p.name.endswith(('.tmp', '.part'))
        )

    # ---- BUG-403 -------------------------------------------------------
    def test_backup_wal_non_checkpointe_restaure_sur_autre_base(self):
        conn = _wal_db(self.db, 500)
        self.addCleanup(conn.close)
        # le -wal doit contenir des données (preuve du scénario)
        self.assertTrue(Path(str(self.db) + '-wal').exists())
        gz = ds.backup_database(self.db, self.bk, LOG, label='t', with_seconds=True)
        self.assertIsNotNone(gz)
        expected = _rows(self.db)
        self.assertEqual(len(expected), 500)

        other_dir = self.d / 'autre'
        other_dir.mkdir()
        other = other_dir / 'kiese.sqlite3'
        oc = _wal_db(other, 7, prefix='x')
        oc.close()
        ds.restore_database(other, self.bk, gz.name, LOG)
        self.assertEqual(_rows(other), expected)
        self.assertTrue(ds._integrity_ok(other))

    def test_backup_pendant_qu_une_connexion_ecrit(self):
        conn = _wal_db(self.db, 10)
        self.addCleanup(conn.close)
        stop = threading.Event()
        errors = []

        def writer():
            c = sqlite3.connect(str(self.db), timeout=10)
            c.execute('PRAGMA wal_autocheckpoint=0')
            i = 0
            try:
                while not stop.is_set():
                    c.execute('INSERT INTO t (v) VALUES (?)', (f'w{i}',))
                    c.commit()
                    i += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                c.close()

        th = threading.Thread(target=writer)
        th.start()
        try:
            time.sleep(0.2)
            gzs = [ds.backup_database(self.db, self.bk, LOG, label=f'c{i}', with_seconds=True) for i in range(3)]
        finally:
            stop.set()
            th.join()
        self.assertEqual(errors, [])
        for gz in gzs:
            target = self.d / f'r_{gz.stem}.sqlite3'
            with gzip.open(gz, 'rb') as f:
                target.write_bytes(f.read())
            self.assertTrue(ds._integrity_ok(target))
            self.assertGreaterEqual(len(_rows(target)), 10)
        self.assertEqual(self._leftovers(), [])

    def test_backup_sans_base(self):
        self.assertIsNone(ds.backup_database(self.db, self.bk, LOG))
        self.assertEqual(list(self.bk.iterdir()), [])

    def test_backup_ne_laisse_pas_de_temporaire_si_echec(self):
        self.db.write_bytes(b'ceci n est pas une base sqlite' * 50)
        with self.assertRaises(Exception):
            ds.backup_database(self.db, self.bk, LOG, label='ko', with_seconds=True)
        import gc
        gc.collect()  # Windows : libere un descripteur SQLite eventuellement reste ouvert
        self.assertEqual(self._leftovers(), [])
        self.assertEqual([p.name for p in self.bk.glob('*.gz')], [])

    # ---- BUG-404 : base courante intacte --------------------------------
    def _current(self):
        c = _wal_db(self.db, 20, prefix='cur')
        c.close()  # checkpoint à la fermeture : fichier principal complet
        for suf in ('-wal', '-shm'):
            self.assertFalse(Path(str(self.db) + suf).exists() and Path(str(self.db) + suf).stat().st_size > 0 and suf == '-wal')
        return _sha(self.db)

    def _assert_refused_untouched(self, name, before):
        with self.assertRaises(ds.RestoreError) as cm:
            ds.restore_database(self.db, self.bk, name, LOG)
        self.assertEqual(_sha(self.db), before)
        self.assertEqual(self._leftovers(), [])
        self.assertEqual([p.name for p in self.bk.glob('kiese-avant-restauration-*')], [])
        return str(cm.exception)

    def test_gz_tronque(self):
        before = self._current()
        raw = _valid_sqlite_bytes(self.d)
        full = io.BytesIO()
        with gzip.GzipFile(fileobj=full, mode='wb') as f:
            f.write(raw * 20)
        (self.bk / 'kiese-trunc.sqlite3.gz').write_bytes(full.getvalue()[: len(full.getvalue()) // 2])
        msg = self._assert_refused_untouched('kiese-trunc.sqlite3.gz', before)
        self.assertIn('corrompue', msg)

    def test_gz_vide_zero_octet(self):
        before = self._current()
        (self.bk / 'kiese-vide.sqlite3.gz').write_bytes(b'')
        self._assert_refused_untouched('kiese-vide.sqlite3.gz', before)

    def test_gz_valide_mais_contenu_vide(self):
        """gzip valide dont le contenu est 0 octet : SQLite le voit comme une base vide « ok »."""
        before = self._current()
        _write_gz(self.bk / 'kiese-zero.sqlite3.gz', b'')
        try:
            ds.restore_database(self.db, self.bk, 'kiese-zero.sqlite3.gz', LOG)
            restored_empty = True
        except ds.RestoreError:
            restored_empty = False
        # Constat consigné : si restored_empty, la base courante a été écrasée par une base vide.
        self.__class__.zero_content_overwrites = restored_empty
        if restored_empty:
            self.assertNotEqual(_sha(self.db), before)

    def test_non_sqlite(self):
        before = self._current()
        _write_gz(self.bk / 'kiese-txt.sqlite3.gz', b'Bonjour, ceci est un texte.\n' * 400)
        msg = self._assert_refused_untouched('kiese-txt.sqlite3.gz', before)
        self.assertIn('base valide', msg)

    def test_non_gzip_du_tout(self):
        before = self._current()
        (self.bk / 'kiese-raw.sqlite3.gz').write_bytes(_valid_sqlite_bytes(self.d))  # sqlite brut renommé .gz
        self._assert_refused_untouched('kiese-raw.sqlite3.gz', before)

    def test_integrity_check_negatif(self):
        before = self._current()
        raw = bytearray(_valid_sqlite_bytes(self.d, n=400))
        # corrompt l'en-tete de la page B-tree n.2 (type de page invalide)
        raw[4096] = 0x7F
        raw[4097:4100] = bytes([255, 255, 255])
        _write_gz(self.bk / 'kiese-corrupt.sqlite3.gz', bytes(raw))
        self._assert_refused_untouched('kiese-corrupt.sqlite3.gz', before)

    def test_sauvegarde_introuvable(self):
        before = self._current()
        msg = self._assert_refused_untouched('kiese-absente.sqlite3.gz', before)
        self.assertIn('introuvable', msg)

    # ---- copie de sécurité ------------------------------------------------
    def test_copie_de_securite_restaurable(self):
        conn = _wal_db(self.db, 15, prefix='avant')
        conn.commit()  # connexion laissée ouverte : -wal non checkpointé
        self.addCleanup(conn.close)
        before_rows = _rows(self.db)
        _write_gz(self.bk / 'kiese-ancienne.sqlite3.gz', _valid_sqlite_bytes(self.d, n=2))
        conn.close()
        safety = ds.restore_database(self.db, self.bk, 'kiese-ancienne.sqlite3.gz', LOG)
        self.assertTrue(safety.name.startswith('kiese-avant-restauration-'))
        self.assertEqual([r[1] for r in _rows(self.db)], ['g0', 'g1'])
        self.assertEqual(self._leftovers(), [])
        # la copie est listable (liste blanche) et restaurable
        self.assertTrue(ds.BACKUP_NAME_RE.match(safety.name))
        ds.restore_database(self.db, self.bk, safety.name, LOG)
        self.assertEqual(_rows(self.db), before_rows)

    def test_restauration_idempotente(self):
        c = _wal_db(self.db, 5)
        c.close()
        gz = ds.backup_database(self.db, self.bk, LOG, label='i', with_seconds=True)
        rows = _rows(self.db)
        for _ in range(3):
            ds.restore_database(self.db, self.bk, gz.name, LOG)
            self.assertEqual(_rows(self.db), rows)
        self.assertEqual(self._leftovers(), [])
        self.assertTrue(ds._integrity_ok(self.db))

    def test_restauration_sans_base_courante(self):
        c = _wal_db(self.db, 4)
        c.close()
        gz = ds.backup_database(self.db, self.bk, LOG, label='s', with_seconds=True)
        rows = _rows(self.db)
        for suf in ('', '-wal', '-shm'):
            Path(str(self.db) + suf).unlink(missing_ok=True)
        res = ds.restore_database(self.db, self.bk, gz.name, LOG)
        self.assertEqual(res, self.db)
        self.assertEqual(_rows(self.db), rows)

    def test_wal_orphelin_de_l_ancienne_base_supprime(self):
        """Un -wal résiduel de l'ancienne base ne doit pas être rejoué sur la base restaurée."""
        conn = _wal_db(self.db, 30, prefix='vieux')
        self.addCleanup(conn.close)
        _write_gz(self.bk / 'kiese-n.sqlite3.gz', _valid_sqlite_bytes(self.d, n=2))
        conn.close()
        ds.restore_database(self.db, self.bk, 'kiese-n.sqlite3.gz', LOG)
        self.assertEqual([r[1] for r in _rows(self.db)], ['g0', 'g1'])

    # ---- noms hostiles ------------------------------------------------------
    def test_noms_hostiles(self):
        hostiles = [
            '../x', '..\\x', 'C:\\x', 'C:/x', '/etc/passwd', 'kiese-x.sqlite3.gz/../..',
            'kiese-x.sqlite3.gz/..', '../kiese-x.sqlite3.gz', 'sub/kiese-x.sqlite3.gz',
            'kiese-\u00e9t\u00e9.sqlite3.gz', 'kiese-\u202egz.sqlite3.gz', 'kiese-x\x00.sqlite3.gz',
            'kiese-' + 'a' * 5000 + '.sqlite3.zip', 'KIESE-x.sqlite3.gz', 'Kiese-x.sqlite3.gz',
            'kiese-x.SQLITE3.GZ', 'kiese-x.sqlite3', 'kiese-x.sqlite3.gz.exe', 'x.sqlite3.gz',
            '', ' kiese-x.sqlite3.gz', 'kiese-x.sqlite3.gz ', 'kiese-a b.sqlite3.gz',
            'kiese-x..sqlite3.gz', '\\\\srv\\share\\kiese-x.sqlite3.gz', 'kiese-x:ads.sqlite3.gz',
        ]
        for name in hostiles:
            with self.subTest(name=repr(name)[:60]):
                with self.assertRaises(ds.RestoreError) as cm:
                    ds.validate_backup_file_name(name)
                self.assertIn('invalide', str(cm.exception))

    def test_noms_non_chaine(self):
        for bad in (None, 12, b'kiese-x.sqlite3.gz', ['kiese-x.sqlite3.gz']):
            with self.assertRaises(ds.RestoreError):
                ds.validate_backup_file_name(bad)

    def test_noms_valides(self):
        for ok in ('kiese-20261121-1030.sqlite3.gz', 'kiese-manuelle-20261121-103000.sqlite3.gz',
                   'kiese-avant-restauration-20261121-103000.sqlite3.gz'):
            self.assertEqual(ds.validate_backup_file_name(ok), ok)

    def test_nom_hostile_ne_sort_pas_du_dossier(self):
        before = self._current()
        outside = self.d / 'kiese-dehors.sqlite3.gz'
        _write_gz(outside, _valid_sqlite_bytes(self.d))
        for name in ('../kiese-dehors.sqlite3.gz', '..\\kiese-dehors.sqlite3.gz', str(outside)):
            with self.assertRaises(ds.RestoreError):
                ds.restore_database(self.db, self.bk, name, LOG)
        self.assertEqual(_sha(self.db), before)

    # ---- messages en français ------------------------------------------------
    def test_messages_en_francais(self):
        before = self._current()
        _write_gz(self.bk / 'kiese-t.sqlite3.gz', b'texte' * 100)
        for name in ('kiese-t.sqlite3.gz', 'kiese-absent.sqlite3.gz', '../x'):
            with self.assertRaises(ds.RestoreError) as cm:
                ds.restore_database(self.db, self.bk, name, LOG)
            msg = str(cm.exception)
            for eng in ('Traceback', 'No such file', 'database disk image', 'Not a gzip', 'Errno'):
                self.assertNotIn(eng, msg)
        self.assertEqual(_sha(self.db), before)

    # ---- rotation --------------------------------------------------------------
    def test_rotation_30_jours(self):
        c = _wal_db(self.db, 3)
        c.close()
        old = self.bk / 'kiese-20200101-0000.sqlite3.gz'
        _write_gz(old, b'x')
        ts = (datetime.now() - timedelta(days=45)).timestamp()
        os.utime(old, (ts, ts))
        autre = self.bk / 'notes.txt'
        autre.write_text('a garder')
        os.utime(autre, (ts, ts))
        new = ds.backup_database(self.db, self.bk, LOG, label='r', with_seconds=True)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertTrue(autre.exists())

    def test_rotation_ne_supprime_pas_la_derniere_copie_ni_la_securite(self):
        """Toutes les copies vieilles de >30 j + restauration : la copie de sécurité fraîche survit,
        mais la sauvegarde qu'on vient de restaurer (ancienne) peut avoir été supprimée par la rotation."""
        c = _wal_db(self.db, 3)
        c.close()
        old = self.bk / 'kiese-20200101-0000.sqlite3.gz'
        _write_gz(old, _valid_sqlite_bytes(self.d, n=2))
        ts = (datetime.now() - timedelta(days=45)).timestamp()
        os.utime(old, (ts, ts))
        safety = ds.restore_database(self.db, self.bk, old.name, LOG)
        self.assertTrue(safety.exists())
        self.__class__.restored_source_deleted = not old.exists()

    # ---- CLI -------------------------------------------------------------------
    def _cli(self, *argv):
        script = Path(ds.__file__)
        r = subprocess.run(
            [sys.executable, '-I', str(script), *argv],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, cwd=str(self.d),
        )
        lines = [ln for ln in (r.stdout or '').splitlines() if ln.strip().startswith('{')]
        return r.returncode, (json.loads(lines[-1]) if lines else None), r

    def test_cli_backup_restore_et_erreurs(self):
        c = _wal_db(self.db, 6)
        self.addCleanup(c.close)
        rc, res, _ = self._cli('backup', '--data-dir', str(self.d))
        self.assertEqual(rc, 0, res)
        self.assertTrue(res['ok'])
        name = Path(res['path']).name
        c.close()
        rc, res, _ = self._cli('restore', '--data-dir', str(self.d), '--file', name)
        self.assertEqual(rc, 0, res)
        self.assertTrue(res['safetyCopy'].startswith('kiese-avant-restauration-'))
        rc, res, _ = self._cli('restore', '--data-dir', str(self.d), '--file', '../x')
        self.assertEqual(rc, 1)
        self.assertFalse(res['ok'])
        self.assertIn('invalide', res['error'])
        rc, res, _ = self._cli('restore', '--data-dir', str(self.d))
        self.assertEqual(rc, 1)
        self.assertFalse(res['ok'])

    def test_cli_backup_sans_base(self):
        rc, res, _ = self._cli('backup', '--data-dir', str(self.d))
        self.assertEqual(rc, 1)
        self.assertIn('Aucune base', res['error'])

    def test_nom_avec_saut_de_ligne_final(self):
        """BUG-409 : `$` accepte un « \n » final dans la liste blanche."""
        with self.assertRaises(ds.RestoreError):
            ds.validate_backup_file_name('kiese-x.sqlite3.gz\n')
