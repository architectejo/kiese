"""BUG-1113 (lot I-4) : export Excel des statistiques d'intrants. Donnees FICTIVES.

Chaque cellule du classeur est recoupee avec la reponse JSON de `intrants-stats` (formules
evaluees ici, openpyxl ne calcule pas)."""
import io
import re
from decimal import Decimal as D

from django.utils import timezone
from openpyxl import load_workbook

from core.models import Node
from core.tests.test_permissions_regression_2026_11_19 import Base, cl, mk
from production.models import ConsumableType, ProductionSession
from production.tests.test_intrants_stats_a import TODAY, declare, move, stock

URL = '/api/production/intrants-export/'
STATS = '/api/production/intrants-stats/'
SHEETS = {'FLOUR': 'FARINE', 'YEAST': 'Levure', 'OIL': 'HUILE', 'SALT': 'SEL'}
REF = re.compile(r'\b([A-Z]+)(\d+)\b')
SUM = re.compile(r'SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)')


def value(ws, ref):
    """Valeur d'une cellule : nombre, ou formule simple evaluee (None si vide)."""
    v = ws[ref].value
    if not (isinstance(v, str) and v.startswith('=')):
        return v
    expr = v[1:]
    expr = SUM.sub(lambda m: '(' + '+'.join(
        str(value(ws, f'{m.group(1)}{r}') or 0) for r in range(int(m.group(2)), int(m.group(4)) + 1)) + ')',
        expr)
    expr = REF.sub(lambda m: str(value(ws, m.group(0)) or 0), expr)
    assert re.fullmatch(r'[0-9eE+\-*/(). ]+', expr), expr
    try:
        return eval(expr)
    except ZeroDivisionError:
        return 'DIV0'


class Export(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for code, label, unit in [('FLOUR', 'Farine', 'sacs'), ('YEAST', 'Levure', 'paquets'),
                                  ('SALT', 'Sel', 'g'), ('OIL', 'Huile', 'litres')]:
            ConsumableType.objects.get_or_create(code=code, defaults={'label': label, 'unit': unit})

    def book(self, user, **params):
        r = cl(user).get(URL, params)
        self.assertEqual(r.status_code, 200, getattr(r, 'data', r.content[:200]))
        return r, load_workbook(io.BytesIO(r.content))

    def scenario(self, siege=True):
        if siege:
            self.siege = Node.objects.get_or_create(
                code='SIEGE', defaults={'name': 'Siège', 'is_active': False})[0]
        for code in SHEETS:
            s1 = stock(self.k1, code, '20')
            sess = ProductionSession.objects.create(node=self.k1, team='A', date=TODAY,
                                                    flour_sacks_used=D('5')) if code == 'FLOUR' else \
                ProductionSession.objects.filter(node=self.k1, date=TODAY).first()
            move(self.k1, s1, 'ENTRY', '10.5')
            move(self.k1, s1, 'EXIT', '4')
            move(self.k1, s1, 'EXIT', '2.25', session=sess)
            declare(self.k1, code, '20')
            stock(self.k2, code, '7')
            if siege:
                sd = stock(self.siege, code, '100')
                move(self.siege, sd, 'EXIT', '8')
        ProductionSession.objects.create(node=self.k2, team='A', date=TODAY, flour_sacks_used=D('2'))

    def rows_of(self, ws):
        out = {}
        for r in range(6, ws.max_row + 1):
            if ws[f'B{r}'].value:
                out[ws[f'B{r}'].value] = r
        return out

    def check_against_json(self, user, **params):
        r, wb = self.book(user, date=TODAY.isoformat(), **params)
        self.assertEqual(wb.sheetnames[:4], ['FARINE', 'Levure', 'HUILE', 'SEL'])
        for code, name in SHEETS.items():
            js = cl(user).get(STATS, {'type': code, 'date': TODAY.isoformat(), **params}).data
            ws = wb[name]
            rows = self.rows_of(ws)
            self.assertEqual(set(rows), {x['code'] for x in js['rows']} | {'TOTAUX'})
            lines = [(x['code'], x) for x in js['rows']] + [('TOTAUX', js['totals'])]
            for ident, x in lines:
                rr = rows[ident]
                for key, col in (('initial', 'C'), ('entry', 'D'), ('exit', 'E'),
                                 ('total_before_production', 'F'), ('consumption', 'G'),
                                 ('balance', 'H'), ('production_reference', 'I'),
                                 ('declared_remaining', 'K'), ('gap', 'L')):
                    cell = value(ws, f'{col}{rr}')
                    if x[key] is None:
                        self.assertIsNone(cell, (name, ident, key))
                    else:
                        self.assertAlmostEqual(cell, float(x[key]), places=6, msg=(name, ident, key))
                cell = value(ws, f'J{rr}')
                if x['consumption_index'] is None:
                    self.assertIsNone(cell, (name, ident, 'index'))
                else:
                    self.assertAlmostEqual(cell, float(x['consumption_index']), places=4)
        return wb

    # ---- contenu ----
    def test_toutes_les_cellules_egalent_le_json_direction_avec_d1(self):
        self.scenario()
        wb = self.check_against_json(self.u['DIRECTION'])
        self.assertIn('D1', self.rows_of(wb['FARINE']))

    def test_formules_du_client_et_cellules_vides(self):
        self.scenario()
        _, wb = self.book(self.u['DIRECTION'], date=TODAY.isoformat())
        ws = wb['Levure']
        r = self.rows_of(ws)['P1']
        self.assertEqual(ws[f'F{r}'].value, f'=C{r}+D{r}-E{r}')
        self.assertEqual(ws[f'H{r}'].value, f'=F{r}-G{r}')
        self.assertEqual(ws[f'L{r}'].value, f'=K{r}-H{r}')
        self.assertEqual(ws[f'J{r}'].value, f'=G{r}/I{r}')
        # P2 : reference production nulle sur la levure (aucune fournee de farine ... 2 sacs)
        # mais pas de reste declare : ecart vide, jamais d'erreur Excel
        r2 = self.rows_of(ws)['P2']
        self.assertIsNone(ws[f'K{r2}'].value)
        self.assertIsNone(ws[f'L{r2}'].value)
        d1 = self.rows_of(ws)['D1']
        self.assertIsNone(ws[f'J{d1}'].value)       # D1 : aucune reference -> indice vide
        for sheet in wb:
            for row in sheet.iter_rows():
                for c in row:
                    self.assertNotIn('#DIV', str(c.value))

    def test_sel_colonnes_conversion_vides_avec_commentaire(self):
        self.scenario()
        _, wb = self.book(self.u['DIRECTION'], date=TODAY.isoformat())
        ws = wb['SEL']
        self.assertEqual(ws['M5'].value, 'RESTE/SAC')
        self.assertEqual(ws['N5'].value, 'RESTE/BOITE')
        self.assertIn('Conversion à venir', ws['M5'].comment.text)
        for r in self.rows_of(ws).values():
            self.assertIsNone(ws[f'M{r}'].value)
            self.assertIsNone(ws[f'N{r}'].value)

    def test_en_tetes_deux_lignes_et_hypotheses(self):
        self.scenario()
        r, wb = self.book(self.u['ADMIN'], date=TODAY.isoformat())
        ws = wb['FARINE']
        self.assertEqual([ws[f'{c}4'].value for c in 'ABCDFGHIJK'],
                         ['DATE', 'BLGR', 'STOCK', 'MOUVEMENT', 'TOTAL AVANT', 'CONSOMMATION',
                          'SOLDE', 'REFERENCE', 'INDICE DE', 'INVENTAIRE PHYSIQUE'])
        self.assertEqual([ws[f'{c}5'].value for c in 'CDEFHIJKL'],
                         ['INITIAL', 'ENTREE', 'SORTIE', 'PRODUCTION', 'COMPTABLE', 'PRODUCTION',
                          'CONSOMMATION', 'RESTE DECLARE', 'ECART'])
        self.assertEqual(ws['C6'].number_format, '0.000')
        hyp = cl(self.u['ADMIN']).get(STATS, {'type': 'FLOUR', 'date': TODAY.isoformat()}).data['hypotheses']
        sheet = wb['Hypothèses']
        self.assertEqual([sheet[f'A{i}'].value for i in range(3, 3 + len(hyp))], hyp)
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn(f'statistiques-intrants-{TODAY.isoformat()}.xlsx', r['Content-Disposition'])
        self.assertIn('spreadsheetml', r['Content-Type'])

    def test_d1_absent_hors_cloud(self):
        Node.objects.filter(code='SIEGE').delete()    # poste local : pas de noeud SIEGE
        self.scenario(siege=False)
        wb = self.check_against_json(self.u['DIRECTION'])
        self.assertNotIn('D1', self.rows_of(wb['FARINE']))

    def test_filtre_node(self):
        self.scenario()
        wb = self.check_against_json(self.u['DIRECTION'], node='P2')
        self.assertEqual(set(self.rows_of(wb['FARINE'])), {'P2', 'TOTAUX'})

    # ---- droits ----
    def test_droits_par_role(self):
        self.scenario()
        for role, expected in (('ADMIN', 200), ('DIRECTION', 200), ('COMPTABLE', 200), ('GERANT', 200),
                               ('FACTURIER', 403), ('LIVREUR', 403)):
            r = cl(self.u[role]).get(URL, {'date': TODAY.isoformat()})
            self.assertEqual(r.status_code, expected, role)
        self.assertEqual(cl().get(URL).status_code, 401)

    def test_gerant_limite_a_sa_boulangerie(self):
        self.scenario()
        wb = self.check_against_json(self.u['GERANT'])
        self.assertEqual(set(self.rows_of(wb['FARINE'])), {'P1', 'TOTAUX'})
        r = cl(self.u['GERANT']).get(URL, {'node': 'P2'})
        self.assertEqual(r.status_code, 404)

    def test_compte_sans_boulangerie(self):
        orphan = mk('orphan_g', 'GERANT', None)
        self.assertEqual(cl(orphan).get(URL).status_code, 403)

    # ---- parametres ----
    def test_parametres_invalides_400_francais(self):
        for params in ({'date': '2026-13-45'}, {'date': 'abc'}, {'date': '1999-01-01'},
                       {'month': '2026-13'}, {'month': 'x'}, {'node': 'ZZZ'}, {'node': '1e2'}):
            r = cl(self.u['DIRECTION']).get(URL, params)
            self.assertEqual(r.status_code, 400, params)
            self.assertIn('detail', r.data)

    # ---- injection ----
    def test_injection_de_formule_dans_un_nom_de_boulangerie(self):
        evil = Node.objects.create(code='=EVIL1', name='=cmd|x')
        self.scenario(siege=False)
        _, wb = self.book(self.u['DIRECTION'], date=TODAY.isoformat(), month='2026-11')
        found = False
        for sheet in wb:
            for row in sheet.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and 'EVIL1' in c.value:
                        found = True
                        self.assertTrue(c.value.startswith("'="), c.value)
                        self.assertNotEqual(c.data_type, 'f')
        self.assertTrue(found)
        evil.delete()

    # ---- mensuel ----
    def test_feuille_mensuelle_egale_le_json(self):
        self.scenario()
        ProductionSession.objects.create(node=self.k1, team='B', date=TODAY.replace(day=1),
                                         flour_sacks_used=D('3.5'))
        month = TODAY.strftime('%Y-%m')
        _, wb = self.book(self.u['DIRECTION'], date=TODAY.isoformat(), month=month)
        self.assertIn('ENTREE FARINE', wb.sheetnames)
        js = cl(self.u['DIRECTION']).get(
            '/api/production/consumables/flour-month-stats/', {'month': month}).data
        ws = wb['ENTREE FARINE']
        codes = [b['code'] for b in js['bakeries']]
        for i, row in enumerate(js['rows'], start=4):
            self.assertEqual(ws[f'A{i}'].value.date().isoformat(), row['date'])
            for j, c in enumerate(codes, start=2):
                self.assertAlmostEqual(ws.cell(i, j).value, float(row['consumption'][c]), places=6)
            self.assertAlmostEqual(ws.cell(i, len(codes) + 2).value, float(row['total']), places=6)
            self.assertAlmostEqual(ws.cell(i, len(codes) + 6).value, float(row['balance']), places=6)
        n = len(js['rows']) + 4
        self.assertEqual(ws[f'A{n}'].value, 'TOTAL DU MOIS')
        self.assertEqual(ws[f'A{n + 1}'].value, 'MOYENNE / JOUR')
        self.assertAlmostEqual(ws.cell(n, len(codes) + 2).value, float(js['summary']['total']['total']))
        self.assertAlmostEqual(ws.cell(n + 1, len(codes) + 2).value,
                               float(js['summary']['average_per_day']['total']))

    def test_mois_sans_donnees_et_gerant_sans_direction(self):
        _, wb = self.book(self.u['DIRECTION'], date=TODAY.isoformat(), month='2024-02')
        ws = wb['ENTREE FARINE']
        self.assertEqual(ws['A4'].value.date().isoformat(), '2024-02-01')
        self.assertEqual(ws['A33'].value, 'TOTAL DU MOIS')           # 2024 bissextile : 29 jours
        self.assertEqual(ws['A3'].value, 'DATE')
        _, wbg = self.book(self.u['GERANT'], date=TODAY.isoformat(), month='2024-02')
        heads = [c.value for c in wbg['ENTREE FARINE'][3] if c.value]
        self.assertNotIn('ENTREE', heads)
        self.assertNotIn('SOLDE', heads)

    def test_sans_month_pas_de_feuille_mensuelle(self):
        _, wb = self.book(self.u['DIRECTION'], date=TODAY.isoformat())
        self.assertNotIn('ENTREE FARINE', wb.sheetnames)
        self.assertEqual(wb.sheetnames[-1], 'Hypothèses')
