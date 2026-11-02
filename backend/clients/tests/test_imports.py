"""
Tests de l'import Excel clients (`clients/imports.py`) — CLAUDE.md §5.1,
BUG-012. Fichier Excel entièrement FICTIF généré en mémoire : on
n'utilise jamais un fichier de `data_kiese/` (CLAUDE.md §4).
"""
import io

import openpyxl
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from core.testing import make_node, make_user
from clients.imports import parse_client_excel, split_name
from clients.models import Client


def _build_fake_workbook(sheets):
    """sheets: {sheet_name: [names...]}. Builds the 'DATE'/'CODE' header
    convention expected by parse_client_excel."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet_name, names in sheets.items():
        ws = wb.create_sheet(title=sheet_name)
        ws.append(['DATE', 'CODE', 'NOM'])
        for i, name in enumerate(names, start=1):
            ws.append([f'2026-10-{i:02d}', f'C{i:04d}', name])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class SplitNameTests(TestCase):
    def test_single_word_name_repeats_as_last_name(self):
        first, last = split_name('MUKENDI')
        self.assertEqual((first, last), ('MUKENDI', 'MUKENDI'))

    def test_multi_word_name_splits_first_rest(self):
        first, last = split_name('Jean Pierre KALALA')
        self.assertEqual(first, 'Jean')
        self.assertEqual(last, 'Pierre KALALA')


class ParseClientExcelTests(TestCase):
    def test_parses_known_node_sheet(self):
        buf = _build_fake_workbook({'CL-K1 TABO': ['DEMO Un', 'DEMO Deux']})
        parsed, skipped = parse_client_excel(buf)
        self.assertIn('K1', parsed)
        self.assertEqual(parsed['K1'], ['DEMO Un', 'DEMO Deux'])
        self.assertEqual(skipped, [])

    def test_unknown_sheet_without_node_token_is_skipped(self):
        buf = _build_fake_workbook({'Feuille sans boulangerie': ['DEMO Un']})
        parsed, skipped = parse_client_excel(buf)
        self.assertEqual(parsed, {})
        self.assertIn('Feuille sans boulangerie', skipped)

    def test_stops_names_at_first_empty_row(self):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        ws = wb.create_sheet(title='CL-K2 COQ')
        ws.append(['DATE', 'CODE', 'NOM'])
        ws.append(['2026-10-01', 'C0001', 'DEMO Un'])
        ws.append([None, None, None])
        ws.append(['2026-10-03', 'C0003', 'DEMO Trois Fantome'])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        parsed, _ = parse_client_excel(buf)
        self.assertEqual(parsed['K2'], ['DEMO Un'])


class ImportExcelApiTests(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1', name='K1 - TABORA')
        self.k2 = make_node(code='K2', name='K2 - COQ')
        self.direction = make_user(role='DIRECTION', node=None)
        self.api = APIClient()
        self.api.force_authenticate(user=self.direction)

    def test_dry_run_does_not_create_clients(self):
        buf = _build_fake_workbook({'CL-K1 TABO': ['DEMO Alpha', 'DEMO Beta']})
        resp = self.api.post(
            '/api/clients/clients/import_excel/',
            {'file': buf, 'dry_run': 'true'},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json()['created'], 0)
        self.assertEqual(Client.objects.count(), 0)

    def test_real_import_creates_clients_per_bakery(self):
        buf = _build_fake_workbook({
            'CL-K1 TABO': ['DEMO Alpha', 'DEMO Beta'],
            'CL-K2 COQ':  ['DEMO Gamma'],
        })
        resp = self.api.post(
            '/api/clients/clients/import_excel/',
            {'file': buf, 'dry_run': 'false'},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json()['created'], 3)
        self.assertEqual(Client.objects.filter(node=self.k1).count(), 2)
        self.assertEqual(Client.objects.filter(node=self.k2).count(), 1)

    def test_reimport_skips_existing_clients_as_duplicates(self):
        buf1 = _build_fake_workbook({'CL-K1 TABO': ['DEMO Alpha']})
        self.api.post('/api/clients/clients/import_excel/', {'file': buf1, 'dry_run': 'false'}, format='multipart')
        self.assertEqual(Client.objects.count(), 1)

        buf2 = _build_fake_workbook({'CL-K1 TABO': ['DEMO Alpha', 'DEMO Beta']})
        resp = self.api.post('/api/clients/clients/import_excel/', {'file': buf2, 'dry_run': 'false'}, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json()['created'], 1)  # seul "DEMO Beta" est nouveau
        self.assertEqual(Client.objects.count(), 2)

    def test_unknown_node_code_in_sheet_is_reported_not_crashed(self):
        buf = _build_fake_workbook({'CL-K9 FANTOME': ['DEMO Inconnu']})
        resp = self.api.post('/api/clients/clients/import_excel/', {'file': buf, 'dry_run': 'false'}, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertIn('K9', resp.json()['unknown_nodes'])
        self.assertEqual(Client.objects.count(), 0)
