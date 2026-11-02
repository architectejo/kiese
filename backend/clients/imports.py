import re

import openpyxl

# Sheet tab names look like "CL-K1 TABO", "CL- K5 MPIANG", "CL-B1 KUMB" — the
# node code is always a token like K1..K9 or B1..B9 somewhere in the name.
_SHEET_NODE_RE = re.compile(r'\b([KB][1-9])\b')


def split_name(raw_name: str):
    """Split a single "name" column into (first_name, last_name), mirroring
    the same convention used by the manual client-creation form in the
    frontend (Clients.tsx): first word = first_name, remaining words =
    last_name, or the first word repeated when there is only one word."""
    parts = raw_name.strip().split()
    first = parts[0] if parts else raw_name.strip()
    last = ' '.join(parts[1:]) or first
    return first, last


def parse_client_excel(file_obj):
    """
    Parse the "Liste des Clients par Boulangerie" workbook.

    Each sheet sometimes carries a leftover/mislabeled report header (copy-
    pasted from another bakery's template) before the real client list, so
    the sheet's own header text can't be trusted to identify the bakery —
    only the sheet tab name can. The real client-list header is always the
    LAST row on the sheet where column A == "DATE" and column B == "CODE";
    the client list itself runs from the row right after that header down
    to the first row with an empty name cell.

    Returns (nodes, skipped_sheets) where nodes = {node_code: [name, ...]}.
    """
    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=True)
    nodes = {}
    skipped_sheets = []
    for sheet_name in wb.sheetnames:
        match = _SHEET_NODE_RE.search(sheet_name.upper())
        if not match:
            skipped_sheets.append(sheet_name)
            continue
        node_code = match.group(1)
        ws = wb[sheet_name]

        header_row = None
        for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if row and row[0] == 'DATE' and len(row) > 1 and row[1] == 'CODE':
                header_row = i
        if header_row is None:
            skipped_sheets.append(sheet_name)
            continue

        names = []
        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            name = row[2] if len(row) > 2 else None
            if name is None or str(name).strip() == '':
                break
            names.append(str(name).strip())
        nodes[node_code] = names
    return nodes, skipped_sheets
