"""Verification independante BUG-408 / BUG-409 / BUG-404 (testeur-installation, 2026-11-21d).

Tests adversariaux sur `desktop_server.restore_database` et
`validate_backup_file_name`, avec des bases SQLite fictives en dossier temporaire.
"""
import gzip
import hashlib
import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

import desktop_server as ds

LOG = logging.getLogger('test.verif408_409')


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _make_db(path: Path, rows=3, prefix='g', table='t'):
    c = sqlite3.connect(str(path))
    c.execute(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY, v TEXT)')
    for i in range(rows):
        c.execute(f'INSERT INTO {table} (v) VALUES (?)', (f'{prefix}{i}',))
    c.commit()
    c.close()


def _db_bytes(tmp: Path, rows=3) -> bytes:
    p = tmp / '_src.sqlite3'
    p.unlink(missing_ok=True)
    _make_db(p, rows)
    data = p.read_bytes()
    p.unlink()
    return data


def _write_gz(path: Path, raw: bytes):
    with gzip.open(path, 'wb') as f:
        f.write(raw)


def _rows(path: Path):
    c = sqlite3.connect(str(path))
    try:
        return [tuple(r) for r in c.execute('SELECT id, v FROM t ORDER BY id')]
    finally:
        c.close()


class _Base(SimpleTestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.d = Path(self._td.name)
        self.db = self.d / 'kiese.sqlite3'
        self.bk = self.d / 'backups'
        self.bk.mkdir()
        _make_db(self.db, 20, prefix='cur')
        self.before = _sha(self.db)

    def _leftovers(self):
        return sorted(p.name for p in list(self.d.iterdir()) + list(self.bk.iterdir())
                      if p.name.endswith(('.tmp', '.part')))

    def _safeties(self):
        return [p.name for p in self.bk.glob('kiese-avant-restauration-*')]

    def assert_refused_before_safety_copy(self, name):
        """Refus, base courante identique a l'octet, AUCUNE copie de securite, aucun residu."""
        with self.assertRaises(ds.RestoreError) as cm:
            ds.restore_database(self.db, self.bk, name, LOG)
        self.assertEqual(_sha(self.db), self.before)
        self.assertEqual(self._safeties(), [])
        self.assertEqual(self._leftovers(), [])
        return str(cm.exception)


class Bug408ContenuInvalide(_Base):
    def test_gz_zero_octet(self):
        (self.bk / 'kiese-a.sqlite3.gz').write_bytes(b'')
        self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')

    def test_gzip_valide_contenu_vide(self):
        _write_gz(self.bk / 'kiese-a.sqlite3.gz', b'')
        msg = self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')
        self.assertIn('vide', msg)

    def test_base_sqlite_valide_sans_table(self):
        p = self.d / '_vide.sqlite3'
        c = sqlite3.connect(str(p))
        c.execute('PRAGMA user_version=7')
        c.commit()
        c.close()
        _write_gz(self.bk / 'kiese-a.sqlite3.gz', p.read_bytes())
        self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')

    def test_base_avec_seulement_une_vue(self):
        p = self.d / '_v.sqlite3'
        c = sqlite3.connect(str(p))
        c.execute('CREATE VIEW v AS SELECT 1 AS x')
        c.commit()
        c.close()
        _write_gz(self.bk / 'kiese-a.sqlite3.gz', p.read_bytes())
        self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')

    def test_entete_sqlite_tronque(self):
        raw = _db_bytes(self.d)
        for n in (1, 15, 16, 50, 99, 100):
            with self.subTest(n=n):
                _write_gz(self.bk / 'kiese-a.sqlite3.gz', raw[:n])
                self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')

    def test_base_tronquee_en_milieu_de_pages(self):
        raw = _db_bytes(self.d, rows=3000)
        self.assertGreater(len(raw), 3 * 4096)
        # n = len(raw) - 1 est accepte par SQLite (fin de derniere page tolerante) : observation, pas un ticket
        for n in (4096 + 100, len(raw) // 2, len(raw) - 4096 - 1):
            with self.subTest(n=n):
                _write_gz(self.bk / 'kiese-a.sqlite3.gz', raw[:n])
                self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')

    def test_base_tronquee_a_la_frontiere_de_page(self):
        raw = _db_bytes(self.d, rows=3000)
        _write_gz(self.bk / 'kiese-a.sqlite3.gz', raw[:4096 * 2])
        self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')

    def test_gz_corrompu_octets_internes(self):
        p = self.bk / 'kiese-a.sqlite3.gz'
        _write_gz(p, _db_bytes(self.d, rows=2000))
        buf = bytearray(p.read_bytes())
        for i in range(20, min(len(buf) - 8, 220)):
            buf[i] ^= 0xFF
        p.write_bytes(bytes(buf))
        self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')

    def test_gz_crc_final_altere(self):
        p = self.bk / 'kiese-a.sqlite3.gz'
        _write_gz(p, _db_bytes(self.d))
        buf = bytearray(p.read_bytes())
        buf[-8] ^= 0xFF
        p.write_bytes(bytes(buf))
        self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')

    def test_gz_contenant_autre_chose(self):
        for label, payload in (('texte', b'Bonjour\n' * 500), ('zip', b'PK\x03\x04' + b'\0' * 600),
                               ('json', b'{"a": 1}'), ('octets nuls', b'\0' * 8192),
                               ('en-tete seul', b'SQLite format 3\x00' + b'\0' * 84)):
            with self.subTest(label=label):
                _write_gz(self.bk / 'kiese-a.sqlite3.gz', payload)
                self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')

    def test_gz_double_compresse(self):
        inner = self.d / 'in.gz'
        _write_gz(inner, _db_bytes(self.d))
        _write_gz(self.bk / 'kiese-a.sqlite3.gz', inner.read_bytes())
        self.assert_refused_before_safety_copy('kiese-a.sqlite3.gz')

    def test_dossier_au_nom_de_sauvegarde(self):
        (self.bk / 'kiese-dir.sqlite3.gz').mkdir()
        with self.assertRaises(ds.RestoreError):
            ds.restore_database(self.db, self.bk, 'kiese-dir.sqlite3.gz', LOG)
        self.assertEqual(_sha(self.db), self.before)

    def test_LIMITE_CONNUE_base_valide_non_kiese_avec_tables_acceptee(self):
        """Limite assumee : une base SQLite valide avec une table quelconque est acceptee.
        Documente le comportement ; la copie de securite doit alors exister et permettre le retour."""
        p = self.d / '_autre.sqlite3'
        _make_db(p, 2, prefix='etranger')
        _write_gz(self.bk / 'kiese-etrangere.sqlite3.gz', p.read_bytes())
        safety = ds.restore_database(self.db, self.bk, 'kiese-etrangere.sqlite3.gz', LOG)
        self.assertTrue(safety.is_file())
        self.assertEqual([r[1] for r in _rows(self.db)], ['etranger0', 'etranger1'])
        ds.restore_database(self.db, self.bk, safety.name, LOG)
        self.assertEqual(len(_rows(self.db)), 20)


class Bug409NomsEtBug404(_Base):
    def test_noms_refuses(self):
        names = [
            'kiese-x.sqlite3.gz\n', 'kiese-x.sqlite3.gz\r', 'kiese-x.sqlite3.gz\r\n', 'kiese-x.sqlite3.gz\n\n',
            '\nkiese-x.sqlite3.gz', 'kiese-a\nb.sqlite3.gz', 'kiese-a\rb.sqlite3.gz',
            'kiese-x.sqlite3.gz ', ' kiese-x.sqlite3.gz', 'kiese-x.sqlite3.gz\t', 'kiese-a b.sqlite3.gz',
            'kiese-x.sqlite3.gz\x00', '../kiese-x.sqlite3.gz', '..\\kiese-x.sqlite3.gz', 'a/../kiese-x.sqlite3.gz',
            './kiese-x.sqlite3.gz', '.\\kiese-x.sqlite3.gz', '/kiese-x.sqlite3.gz', 'C:\\kiese-x.sqlite3.gz',
            'C:/kiese-x.sqlite3.gz', '/etc/passwd', '\\\\srv\\s\\kiese-x.sqlite3.gz', 'kiese-x.sqlite3.gz/',
            'KIESE-x.sqlite3.gz', 'Kiese-x.sqlite3.gz', 'kiese-x.SQLITE3.GZ', 'kiese-x.sqlite3.Gz',
            'kiese-x.sqlite3.gz.exe', 'kiese-x.sqlite3', 'kiese-x..sqlite3.gz',
            'kiese-x:ads.sqlite3.gz', 'kiese-\u00e9.sqlite3.gz', 'kiese-\uff0e\uff0e.sqlite3.gz', '', '.', '..',
        ]
        for name in names:
            with self.subTest(name=repr(name)):
                with self.assertRaises(ds.RestoreError):
                    ds.validate_backup_file_name(name)

    def test_noms_acceptes_dont_majuscules_internes(self):
        for ok in ('kiese-20261121-1030.sqlite3.gz', 'kiese-ABC.sqlite3.gz', 'kiese-a_b-c.d.sqlite3.gz',
                   'kiese-avant-restauration-20261121-103000.sqlite3.gz'):
            with self.subTest(ok=ok):
                self.assertEqual(ds.validate_backup_file_name(ok), ok)

    def test_restore_refuse_nom_avec_saut_de_ligne_meme_si_fichier_existe(self):
        _write_gz(self.bk / 'kiese-x.sqlite3.gz', _db_bytes(self.d))
        for name in ('kiese-x.sqlite3.gz\n', 'kiese-x.sqlite3.gz\r\n'):
            with self.assertRaises(ds.RestoreError):
                ds.restore_database(self.db, self.bk, name, LOG)
        self.assertEqual(_sha(self.db), self.before)
        self.assertEqual(self._safeties(), [])

    def test_chemin_absolu_et_traversee_ne_lisent_rien(self):
        outside = self.d / 'kiese-dehors.sqlite3.gz'
        _write_gz(outside, _db_bytes(self.d))
        for name in (str(outside), '../kiese-dehors.sqlite3.gz', '..\\kiese-dehors.sqlite3.gz'):
            with self.assertRaises(ds.RestoreError):
                ds.restore_database(self.db, self.bk, name, LOG)
        self.assertEqual(_sha(self.db), self.before)

    def test_restauration_deux_fois_de_suite(self):
        _write_gz(self.bk / 'kiese-a.sqlite3.gz', _db_bytes(self.d, rows=2))
        s1 = ds.restore_database(self.db, self.bk, 'kiese-a.sqlite3.gz', LOG)
        s2 = ds.restore_database(self.db, self.bk, 'kiese-a.sqlite3.gz', LOG)
        self.assertEqual([r[1] for r in _rows(self.db)], ['g0', 'g1'])
        self.assertTrue(ds._integrity_ok(self.db))
        self.assertEqual(self._leftovers(), [])
        # la copie de securite de la 1re restauration (donnees d'origine, 20 lignes)
        # ne doit pas avoir ete ecrasee par la 2e (meme seconde => meme nom ?)
        ds.restore_database(self.db, self.bk, s1.name, LOG)
        self.assertEqual(len(_rows(self.db)), 20,
                         f'copie de securite ecrasee (s1={s1.name}, s2={s2.name})')

    def test_safety_copy_conservee_si_remplacement_echoue(self):
        _write_gz(self.bk / 'kiese-a.sqlite3.gz', _db_bytes(self.d, rows=2))
        real_replace = ds.os.replace
        db = self.db

        def fake_replace(src, dst, *a, **k):
            if Path(dst) == db:
                raise PermissionError('verrouille')
            return real_replace(src, dst, *a, **k)

        with mock.patch.object(ds.os, 'replace', side_effect=fake_replace):
            with self.assertRaises(ds.RestoreError) as cm:
                ds.restore_database(self.db, self.bk, 'kiese-a.sqlite3.gz', LOG)
        self.assertIn('copie de sécurité', str(cm.exception))
        self.assertEqual(_sha(self.db), self.before)
        self.assertEqual(len(self._safeties()), 1)
        self.assertEqual(self._leftovers(), [])
        safety = self.bk / self._safeties()[0]
        self.assertGreater(safety.stat().st_size, 0)
        ds.restore_database(self.db, self.bk, safety.name, LOG)
        self.assertEqual(len(_rows(self.db)), 20)

    def test_safety_copy_echec_de_creation_annule_sans_toucher_la_base(self):
        _write_gz(self.bk / 'kiese-a.sqlite3.gz', _db_bytes(self.d, rows=2))
        with mock.patch.object(ds, 'backup_database', side_effect=sqlite3.OperationalError('disque plein')):
            with self.assertRaises(ds.RestoreError):
                ds.restore_database(self.db, self.bk, 'kiese-a.sqlite3.gz', LOG)
        self.assertEqual(_sha(self.db), self.before)
        self.assertEqual(self._leftovers(), [])

    def test_restauration_sans_base_courante_ni_copie(self):
        _write_gz(self.bk / 'kiese-a.sqlite3.gz', _db_bytes(self.d, rows=2))
        self.db.unlink()
        res = ds.restore_database(self.db, self.bk, 'kiese-a.sqlite3.gz', LOG)
        self.assertEqual(res, self.db)
        self.assertEqual(self._safeties(), [])
        self.assertEqual(len(_rows(self.db)), 2)
