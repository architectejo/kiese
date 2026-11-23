"""Lot I-4 (BUG-1113) : export Excel des statistiques d'intrants au format du client.

GET /api/production/intrants-export/?date=AAAA-MM-JJ[&month=AAAA-MM][&node=<id|code>]

Classeur .xlsx (`statistiques-intrants-AAAA-MM-JJ.xlsx`) :
* une feuille par intrant (FARINE, Levure, HUILE, SEL) pour la date donnee, mise en page du fichier
  « STATISQUES NOVEMBRE 2026 LOGICIEL » (titre, en-tetes sur deux lignes, une ligne par boulangerie
  active, ligne D1 si les donnees SIEGE existent (cloud), ligne TOTAUX) ;
* si `month` : feuille « ENTREE FARINE » (statistiques mensuelles de la farine) ;
* feuille « Hypotheses » (celles de `intrants-stats`).

AUCUN calcul n'est duplique : les lignes viennent de `intrants_stats.compute_rows` / `_totals`
(identiques a la reponse JSON de `intrants-stats`), le mois de `flour_month_stats.build_month_stats`.
Les Decimal ne deviennent des float qu'au moment d'ecrire la cellule.

Colonnes calculables = formules Excel du client (F = C+D-E, H = F-G, L = K-H, J = G/I) ; une valeur
absente (ecart non declare, indice sans reference) reste une cellule VIDE, jamais « #DIV/0! ».
Colonnes « reste/sac » et « reste/boite » du sel (M, N) : valeurs `declared_remaining_bags` /
`declared_remaining_units` de `intrants_stats._serialize` (BUG-1117, aucun recalcul) ; vides, avec un
commentaire, si la conversion (`bag_weight_g`, `units_per_bag`) n'est pas configuree. Le stock du sel
reste en grammes (titre « STOCK (g) »).
Toute chaine issue de la base commencant par = + - @ (ou tabulation/retour) est prefixee d'une
apostrophe (aucune injection de formule).
"""
import datetime
import io
from decimal import Decimal

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from rest_framework.response import Response
from rest_framework.views import APIView

from core.mixins import is_node_less_non_hq
from core.models import Node
from kiese.node_guard import resolve_node_param

from .flour_month_stats import build_month_stats, parse_month
from .intrants_stats import (HYPOTHESES, SIEGE_CODE, SUPPORTED_TYPES, CanReadIntrantsStats,
                             _serialize, _totals, compute_rows, parse_day, salt_conversion)
from .models import ConsumableType

Q3 = Decimal('0.001')
Q4 = Decimal('0.0001')
Q2 = Decimal('0.01')
FMT3, FMT4, FMT2 = '0.000', '0.0000', '0.00'
FMT1 = '0.0'
XLSX_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

# (code, nom de feuille dans le fichier du client)
SHEETS = [('FLOUR', 'FARINE'), ('YEAST', 'Levure'), ('OIL', 'HUILE'), ('SALT', 'SEL')]

THIN = Side(style='thin')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
BOLD = Font(bold=True)
HEAD_FILL = PatternFill('solid', fgColor='FFFF00')   # jaune de l'en-tete du client
TOTAL_FILL = PatternFill('solid', fgColor='D9D9D9')

# En-tetes sur deux lignes (comme le fichier) : (ligne 4, ligne 5).
HEADERS = [
    ('DATE', None), ('BLGR', None), ('STOCK', 'INITIAL'), ('MOUVEMENT', 'ENTREE'),
    (None, 'SORTIE'), ('TOTAL AVANT', 'PRODUCTION'), ('CONSOMMATION', None),
    ('SOLDE', 'COMPTABLE'), ('REFERENCE', 'PRODUCTION'), ('INDICE DE', 'CONSOMMATION'),
    ('INVENTAIRE PHYSIQUE', 'RESTE DECLARE'), (None, 'ECART'),
]
SALT_EXTRA = ['RESTE/SAC', 'RESTE/BOITE']
# cle JSON <-> lettre de colonne (A date, B boulangerie)
COLS = {'initial': 'C', 'entry': 'D', 'exit': 'E', 'total_before_production': 'F',
        'consumption': 'G', 'balance': 'H', 'production_reference': 'I',
        'consumption_index': 'J', 'declared_remaining': 'K', 'gap': 'L'}


def safe_text(value):
    """Chaine issue de la base : neutralise l'injection de formule (= + - @, tab, retour chariot)."""
    text = '' if value is None else str(value)
    if text[:1] in ('=', '+', '-', '@', '\t', '\r', '\n'):
        return "'" + text
    return text


def _num(value, quantum):
    """Decimal -> float, uniquement a l'ecriture dans la cellule ; None reste vide."""
    return None if value is None else float(Decimal(value).quantize(quantum))


def _opt(conv_vals, key, quantum):
    """Valeur deja calculee par intrants_stats (chaine Decimal) -> nombre ; absente -> cellule vide."""
    v = conv_vals.get(key) if conv_vals else None
    return None if v is None else _num(Decimal(v), quantum)


def _put(ws, ref, value, fmt=None, bold=False, fill=None, align=CENTER):
    cell = ws[ref]
    cell.value = value
    cell.border = BORDER
    cell.alignment = align
    if fmt:
        cell.number_format = fmt
    if bold:
        cell.font = BOLD
    if fill:
        cell.fill = fill
    return cell


def _select_nodes(user, node_raw):
    """Meme selection que IntrantsStatsView. Retourne (nodes, None) ou (None, Response)."""
    all_nodes = user.can_access_all_nodes
    bakeries = Node.objects.filter(is_active=True).exclude(code=SIEGE_CODE).order_by('code')
    show_direction = all_nodes
    if node_raw not in (None, ''):
        node, resp = resolve_node_param(node_raw)
        if resp is not None:
            return None, resp
        if node.code == SIEGE_CODE or not node.is_active or (
                not all_nodes and node.pk != user.node_id):
            return None, Response({'detail': "Boulangerie introuvable."}, status=404)
        bakeries = bakeries.filter(pk=node.pk)
        show_direction = False
    elif not all_nodes:
        bakeries = bakeries.filter(pk=user.node_id)
    nodes = list(bakeries)
    siege = Node.objects.filter(code=SIEGE_CODE).first() if show_direction else None
    return nodes + ([siege] if siege else []), None


def _intrant_sheet(wb, title, code, day, nodes):
    label, unit = SUPPORTED_TYPES[code]
    ctype = ConsumableType.objects.filter(code=code).first()
    if ctype is not None:
        label, unit = ctype.label, ctype.unit or unit
    computed = compute_rows(day, code, nodes) if nodes else []

    ws = wb.create_sheet(title)
    last_col = 'N' if code == 'SALT' else 'L'
    ws.merge_cells(f'A1:{last_col}1')
    ws['A1'] = day
    ws['A1'].number_format = 'dd/mm/yyyy'
    ws['A1'].font = BOLD
    ws['A1'].alignment = CENTER
    ws.merge_cells(f'A2:{last_col}2')
    ws['A2'] = safe_text(f'INTRANT : {label.upper()} ({unit})')
    ws['A2'].font = BOLD
    ws['A2'].alignment = CENTER

    conv = salt_conversion(ctype) if code == 'SALT' else None
    headers = list(HEADERS)
    if code == 'SALT':                                  # le stock du sel est en unite de base (g)
        headers[2] = (safe_text(f'STOCK ({unit})'), 'INITIAL')
    headers += ([(None, SALT_EXTRA[0]), (None, SALT_EXTRA[1])] if code == 'SALT' else [])
    merges = ['D4:E4']                                 # « MOUVEMENT » couvre entree + sortie
    for idx, (top, bottom) in enumerate(headers, start=1):
        col = get_column_letter(idx)
        _put(ws, f'{col}4', top, bold=True, fill=HEAD_FILL)
        _put(ws, f'{col}5', bottom, bold=True, fill=HEAD_FILL)
        if top is not None and bottom is None:        # titre fusionne sur les deux lignes
            merges.append(f'{col}4:{col}5')
    for ref in merges:
        ws.merge_cells(ref)
    if code == 'SALT':
        if conv is None:
            note = ("Conversion non configurée : renseigner le poids d'un sac et le nombre de boîtes "
                    "par sac du sel ; colonnes laissées vides.")
            ws['M5'].comment = Comment(note, 'KIESE')
            ws['N5'].comment = Comment(note, 'KIESE')

    first = 6
    r = first
    for node, vals in zip(nodes, computed):
        conv_vals = _serialize(vals, conv, True) if code == 'SALT' else None
        _write_row(ws, r, day, 'D1' if node.code == SIEGE_CODE else node.code, vals, code, conv_vals)
        r += 1
    last = r - 1
    totals = _totals(computed) if computed else None
    totals_conv = _serialize(totals, conv, True) if (code == 'SALT' and totals) else None
    _write_totals(ws, r, first, last, totals, code, totals_conv)

    widths = {'A': 12, 'B': 10}
    for idx in range(3, len(headers) + 1):
        widths[get_column_letter(idx)] = 16
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    ws.freeze_panes = 'C6'
    return ws


def _write_row(ws, r, day, code_label, vals, code, conv_vals=None):
    _put(ws, f'A{r}', day, fmt='dd/mm/yyyy', align=Alignment(horizontal='right'))
    _put(ws, f'B{r}', safe_text(code_label))
    _put(ws, f'C{r}', _num(vals['initial'], Q3), FMT3)
    _put(ws, f'D{r}', _num(vals['entry'], Q3), FMT3)
    _put(ws, f'E{r}', _num(vals['exit'], Q3), FMT3)
    _put(ws, f'F{r}', f'=C{r}+D{r}-E{r}', FMT3)
    _put(ws, f'G{r}', _num(vals['consumption'], Q3), FMT3)
    _put(ws, f'H{r}', f'=F{r}-G{r}', FMT3)
    _put(ws, f'I{r}', _num(vals['production_reference'], Q3), FMT3)
    _put(ws, f'J{r}', f'=G{r}/I{r}' if vals['consumption_index'] is not None else None, FMT4)
    declared = vals['declared_remaining']
    _put(ws, f'K{r}', _num(declared, Q3), FMT3)
    _put(ws, f'L{r}', f'=K{r}-H{r}' if declared is not None else None, FMT3)
    if code == 'SALT':
        _put(ws, f'M{r}', _opt(conv_vals, 'declared_remaining_bags', Q3), FMT3)
        _put(ws, f'N{r}', _opt(conv_vals, 'declared_remaining_units', Decimal('0.1')), FMT1)


def _write_totals(ws, r, first, last, totals, code, conv_vals=None):
    _put(ws, f'A{r}', None, fill=TOTAL_FILL)
    _put(ws, f'B{r}', 'TOTAUX', bold=True, fill=TOTAL_FILL)
    for key in ('initial', 'entry', 'exit', 'consumption', 'production_reference'):
        col = COLS[key]
        formula = f'=SUM({col}{first}:{col}{last})' if last >= first else None
        _put(ws, f'{col}{r}', formula, FMT3, bold=True, fill=TOTAL_FILL)
    _put(ws, f'F{r}', f'=C{r}+D{r}-E{r}', FMT3, bold=True, fill=TOTAL_FILL)
    _put(ws, f'H{r}', f'=F{r}-G{r}', FMT3, bold=True, fill=TOTAL_FILL)
    has_idx = totals is not None and totals['consumption_index'] is not None
    _put(ws, f'J{r}', f'=G{r}/I{r}' if has_idx else None, FMT4, bold=True, fill=TOTAL_FILL)
    # reste declare et ecart : totaux des seules lignes declarees (valeurs, pas de formule)
    _put(ws, f'K{r}', _num(totals['declared_remaining'], Q3) if totals else None, FMT3,
         bold=True, fill=TOTAL_FILL)
    _put(ws, f'L{r}', _num(totals['gap'], Q3) if totals else None, FMT3, bold=True, fill=TOTAL_FILL)
    if code == 'SALT':
        _put(ws, f'M{r}', _opt(conv_vals, 'declared_remaining_bags', Q3), FMT3, bold=True, fill=TOTAL_FILL)
        _put(ws, f'N{r}', _opt(conv_vals, 'declared_remaining_units', Decimal('0.1')), FMT1,
             bold=True, fill=TOTAL_FILL)


def _month_sheet(wb, body):
    ws = wb.create_sheet('ENTREE FARINE')
    codes = [b['code'] for b in body['bakeries']]
    direction = body['direction_visible']
    heads = ['DATE'] + codes + ['TOTAL'] + (['ENTREE', 'PU', 'PT', 'SOLDE'] if direction else [])
    ncol = len(heads)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    ws['A1'] = f"STATISTIQUES FARINE — {body['month']}"
    ws['A1'].font = BOLD
    ws['A1'].alignment = CENTER
    for i, h in enumerate(heads, start=1):
        _put(ws, f'{get_column_letter(i)}3', safe_text(h), bold=True, fill=HEAD_FILL)

    def dec(v):
        return None if v is None else float(Decimal(v).quantize(Q2))

    r = 4
    for row in body['rows']:
        y, m, d = (int(x) for x in row['date'].split('-'))
        _put(ws, f'A{r}', datetime.date(y, m, d), 'dd/mm/yyyy', align=Alignment(horizontal='right'))
        for i, c in enumerate(codes, start=2):
            _put(ws, f'{get_column_letter(i)}{r}', dec(row['consumption'][c]), FMT2)
        col = len(codes) + 2
        _put(ws, f'{get_column_letter(col)}{r}', dec(row['total']), FMT2, bold=True)
        if direction:
            for k, key in enumerate(('entry_quantity', 'unit_price', 'total_price', 'balance'), start=1):
                _put(ws, f'{get_column_letter(col + k)}{r}', dec(row.get(key)), FMT2)
        r += 1
    summary = body['summary']
    for label, key in (('TOTAL DU MOIS', 'total'), ('MOYENNE / JOUR', 'average_per_day')):
        _put(ws, f'A{r}', label, bold=True, fill=TOTAL_FILL)
        for i, c in enumerate(codes, start=2):
            _put(ws, f'{get_column_letter(i)}{r}', dec(summary[key][c]), FMT2, bold=True, fill=TOTAL_FILL)
        col = len(codes) + 2
        _put(ws, f'{get_column_letter(col)}{r}', dec(summary[key]['total']), FMT2, bold=True,
             fill=TOTAL_FILL)
        if direction:
            p = body.get('purchases') or {}
            vals = [None, None, None, None]
            if key == 'total':
                vals = [p.get('quantity'), p.get('average_unit_price'), p.get('total_price'),
                        body.get('closing_balance')]
            for k, v in enumerate(vals, start=1):
                _put(ws, f'{get_column_letter(col + k)}{r}', dec(v), FMT2, bold=True, fill=TOTAL_FILL)
        r += 1
    for note in body.get('notes', []):
        r += 1
        ws[f'A{r}'] = safe_text(note)
    ws.column_dimensions['A'].width = 16
    for i in range(2, ncol + 1):
        ws.column_dimensions[get_column_letter(i)].width = 12
    ws.freeze_panes = 'B4'


def _hypotheses_sheet(wb):
    ws = wb.create_sheet('Hypothèses')
    ws['A1'] = 'Hypothèses de calcul (à confirmer avec le client)'
    ws['A1'].font = BOLD
    for i, text in enumerate(HYPOTHESES, start=3):
        ws[f'A{i}'] = safe_text(text)
        ws[f'A{i}'].alignment = Alignment(wrap_text=True, vertical='top')
    ws.column_dimensions['A'].width = 120


def _error(message, code=400):
    return Response({'detail': message}, status=code)


class IntrantsExportView(APIView):
    """GET /api/production/intrants-export/ : classeur Excel des statistiques d'intrants (lot I-4)."""
    permission_classes = [CanReadIntrantsStats]

    def get(self, request):
        user = request.user
        if is_node_less_non_hq(user):
            return _error("Votre compte n'est rattaché à aucune boulangerie : action impossible.", 403)
        day, msg = parse_day(request.query_params.get('date'))
        if msg:
            return _error(msg)
        month_raw = request.query_params.get('month')
        ym = None
        if month_raw not in (None, ''):
            ym, msg = parse_month(month_raw)
            if msg:
                return _error(msg)
        node_raw = request.query_params.get('node')
        nodes, resp = _select_nodes(user, node_raw)
        if resp is not None:
            return resp
        body = None
        if ym is not None:
            body, resp = build_month_stats(user, ym[0], ym[1], node_raw)
            if resp is not None:
                return resp

        wb = Workbook()
        wb.remove(wb.active)
        for code, title in SHEETS:
            _intrant_sheet(wb, title, code, day, nodes)
        if body is not None:
            _month_sheet(wb, body)
        _hypotheses_sheet(wb)
        wb.calculation.fullCalcOnLoad = True

        buf = io.BytesIO()
        wb.save(buf)
        response = HttpResponse(buf.getvalue(), content_type=XLSX_TYPE)
        response['Content-Disposition'] = (
            f'attachment; filename="statistiques-intrants-{day.isoformat()}.xlsx"')
        return response
