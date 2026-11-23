"""Testeur-production (cycle 20 / a19) : verification independante de BUG-1012 (d53 : inventaire physique negatif
refuse, formes exponentielles refusees pour `qty` d'opening-confirmation, prefixe `+` accepte) et balayage des
formes numeriques (+7, 7.0, 7E0, exposant, non ASCII, espaces, bool, null) entre REST et push sync sur les
lignes de fournee, dispositions, comptages, mouvements, transferts, opening-confirmation. Donnees fictives.
Les `@expectedFailure` referencent leur ticket.
"""
from datetime import date as ddate
from unittest import expectedFailure

from production.models import (BreadDisposal, BreadStock, BreadTransferLine, ConsumableCount, ConsumableMovement,
                               ConsumableStock, ProductionSession, ProductionSessionLine)
from production.tests.test_verif_a4_testeur_production import T, cl
from production.tests.test_verif_production_a8_v8 import PushBase, push, uid

S = '/api/production/sessions/'
D = '/api/production/disposals/'
C = '/api/production/counts/'
M = '/api/production/movements/'
OPEN = '/api/production/opening-confirmation/'
NBSP = chr(0xA0)
IDEO = chr(0x3000)


class A19Base(PushBase):
    # ---- REST
    def rest_line(self, q):
        return cl(self.g1).post(S, {'team': 'A', 'flour_sacks_used': '1', 'date': self.day(),
                                    'lines': [{'bread_price': self.b3.pk, 'quantity': q}]}, format='json').status_code

    def rest_disposal(self, q, dtype='UNSOLD'):
        rec, _ = self.push_sess()
        return cl(self.g1).post(D, {'session': rec['id'], 'bread_price': self.b3.pk, 'disposal_type': dtype,
                                    'quantity': q, 'unit_price_sold': 0}, format='json').status_code

    def rest_send(self, q):
        return cl(self.g1).post(f'{T}send/', {'to_node': self.k2.pk, 'lines': [
            {'bread_price': self.b3.pk, 'quantity_sent': q}]}, format='json').status_code

    def rest_open(self, q):
        return cl(self.g1).post(OPEN, {'date': str(ddate.today()), 'team': 'A', 'lines': [
            {'bread_price': self.b3.pk, 'qty': q}]}, format='json').status_code

    # ---- PUSH
    def push_line(self, q):
        rec, _ = self.push_sess()
        return push(self.a1, 'production.ProductionSessionLine',
                    {'id': uid(), 'session': rec['id'], 'bread_price': self.b3.pk, 'quantity': q})[0]

    def push_disposal(self, q, dtype='UNSOLD'):
        rec, _ = self.push_sess()
        return push(self.a1, 'production.BreadDisposal',
                    {'id': uid(), 'session': rec['id'], 'bread_price': self.b3.pk, 'disposal_type': dtype,
                     'quantity': q, 'unit_price_sold': 0})[0]

    def push_tline(self, q):
        t = {'id': uid(), 'from_node': self.k1.code, 'to_node': self.k2.code}
        push(self.a1, 'production.BreadTransfer', t)
        return push(self.a1, 'production.BreadTransferLine',
                    {'transfer': t['id'], 'bread_price': self.b3.pk, 'quantity_sent': q})[0], t['id']

    @staticmethod
    def ok(rest_status):
        return rest_status in (200, 201)


# --------------------------------------------------------------------------- BUG-1012 : verification
class V1012(A19Base):
    def test_inventaire_physique_negatif_refuse_rest_comptage_et_inventaire_et_push(self):
        ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='SALT', defaults={'unit': 'g'})
        r = cl(self.g1).post(C, {'consumable_type': 'SALT', 'count_date': str(ddate.today()),
                                 'physical_quantity': '-1400'}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        r = cl(self.g1).post('/api/production/inventories/',
                             {'lines': [{'consumable_type': 'SALT', 'physical_quantity': '-3'}]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        res = push(self.a1, 'production.ConsumableCount', {
            'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'count_date': str(ddate.today()),
            'system_quantity': '0', 'physical_quantity': '-1', 'gap': '-1'})
        self.assertEqual(res[0], 'REJECTED')
        self.assertEqual(ConsumableCount.objects.count(), 0)

    def test_mouvements_negatifs_et_nuls_toujours_acceptes_en_rest(self):
        st, _ = ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='SALT', defaults={'unit': 'g'})
        for q in ('-1', '0'):
            for mt in ('ENTRY', 'EXIT'):
                r = cl(self.g1).post(M, {'stock': st.pk, 'movement_type': mt, 'quantity': q, 'unit_price': '1'},
                                     format='json')
                self.assertEqual(r.status_code, 201, (q, mt, r.content))

    def test_opening_exposants_refuses_sans_effet_prefixe_plus_accepte(self):
        before = sorted(BreadStock.objects.values_list('pk', 'qty_produced', 'qty_adjusted', 'qty_sent', 'qty_received'))
        for ko in ('7E0', '1e3', '2E+9', '0E+999999', '2.000E+9', '7e0', '+7E0', '7E+0'):
            self.assertEqual(self.rest_open(ko), 400, ko)
        self.assertEqual(sorted(BreadStock.objects.values_list('pk', 'qty_produced', 'qty_adjusted', 'qty_sent', 'qty_received')), before)
        for ok in ('+7', '7.0', ' 7 ', '+0', '007', 7, 7.0):
            self.assertEqual(self.rest_open(ok), 200, ok)

    def test_opening_hostiles_toujours_400(self):
        for ko in (True, None, '', 'abc', '٣', '１２', '-1', '-0.5', 1.5, '7.5', '1_0', '7.', '0x7', '--7', '++7',
                   '+-7', [7], {'a': 1}, '7' + chr(0x200b)):
            self.assertEqual(self.rest_open(ko), 400, repr(ko))

    def test_opening_regex_ne_regresse_pas_les_grandes_chaines(self):
        import time
        for ko in ('9' * 5000, '+' + '9' * 5000, ' ' * 5000 + 'x', '1' + '0' * 4400):
            t = time.monotonic()
            self.assertEqual(self.rest_open(ko), 400)
            self.assertLess(time.monotonic() - t, 2.0)


# --------------------------------------------------------------------------- parite verifiee (OK)
class A19Parity(A19Base):
    def test_lignes_fournee_et_dispositions_memes_verdicts_rest_et_push(self):
        for f in (7, '7', '+7', '7.0', ' 7 ', 7.0, '7E0', '1e3', '2E+9', '٣', '１２', True, '0x7', '--7', '-0',
                  '00007', '٠٧', '7' + chr(0x200b), NBSP + '7', '7' + IDEO):
            self.assertEqual(self.ok(self.rest_line(f)), self.push_line(f) == 'ACCEPTED', ('ligne', f))
            self.assertEqual(self.ok(self.rest_disposal(f)), self.push_disposal(f) == 'ACCEPTED', ('dispo', f))

    def test_negatifs_lignes_et_dispositions_memes_verdicts(self):
        self.assertEqual(self.rest_line(-1), 400)
        self.assertEqual(self.push_line(-1), 'REJECTED')
        self.assertEqual(self.rest_disposal(-1), 400)
        self.assertEqual(self.push_disposal(-1), 'REJECTED')
        self.assertTrue(self.ok(self.rest_disposal(-1, 'REMAINING')))
        self.assertEqual(self.push_disposal(-1, 'REMAINING'), 'ACCEPTED')

    def test_consommables_decimaux_memes_verdicts_comptage_et_mouvement(self):
        st, _ = ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='SALT', defaults={'unit': 'g'})
        for f in ('0.25', '7', '+7', '7.0', '7E0', '1e3', '2E+9', '٣', True, 'abc', '0.0001'):
            rm = cl(self.g1).post(M, {'stock': st.pk, 'movement_type': 'ENTRY', 'quantity': f, 'unit_price': '1'},
                                  format='json').status_code
            pm = push(self.a1, 'production.ConsumableMovement', {
                'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'ENTRY',
                'quantity': f, 'unit': 'g'})[0]
            self.assertEqual(self.ok(rm), pm == 'ACCEPTED', ('mvt', f, rm, pm))
            gap = f if not isinstance(f, bool) and f not in ('abc',) else '0'
            rc = cl(self.g1).post(C, {'consumable_type': 'SALT', 'count_date': str(ddate.today()),
                                      'physical_quantity': f}, format='json').status_code
            pc = push(self.a1, 'production.ConsumableCount', {
                'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'count_date': str(ddate.today()),
                'system_quantity': '0', 'physical_quantity': f, 'gap': gap})[0]
            self.assertEqual(self.ok(rc), pc == 'ACCEPTED', ('compte', f, rc, pc))

    def test_transferts_formes_communes_memes_verdicts(self):
        for f in (7, '7', ' 7 ', 7.0, '7E0', '1e3', '٣', True, '0x7', '--7', '7' + chr(0x200b), -1):
            rs = self.rest_send(f)
            ps, _ = self.push_tline(f)
            self.assertEqual(self.ok(rs), ps == 'ACCEPTED', ('transfert', f, rs, ps))


# --------------------------------------------------------------------------- nouveaux defauts
class A19Defects(A19Base):
    @expectedFailure   # BUG-1015
    def test_1015_transferts_rest_et_push_meme_verdict_plus_decimal_zeros(self):
        bad = []
        for f in ('+7', '7.0', '00007', '-0', '+0'):
            rs = self.rest_send(f)
            ps, _ = self.push_tline(f)
            if self.ok(rs) != (ps == 'ACCEPTED'):
                bad.append((f, rs, ps))
        self.assertEqual(bad, [])

    @expectedFailure   # BUG-1016
    def test_1016_espaces_non_ascii_meme_verdict_partout(self):
        bad = []
        for f in (NBSP + '7', '7' + IDEO, chr(0x2007) + '7'):
            verdicts = {'ligne': self.ok(self.rest_line(f)), 'dispo': self.ok(self.rest_disposal(f)),
                        'transfert': self.ok(self.rest_send(f)), 'opening': self.ok(self.rest_open(f)),
                        'push_ligne': self.push_line(f) == 'ACCEPTED',
                        'push_transfert': self.push_tline(f)[0] == 'ACCEPTED'}
            if len(set(verdicts.values())) != 1:
                bad.append((ascii(f), verdicts))
        self.assertEqual(bad, [])

    @expectedFailure   # BUG-1017
    def test_1017_push_refuse_null_comme_rest(self):
        self.assertEqual(self.rest_disposal(None), 400)
        self.assertEqual(self.push_disposal(None), 'REJECTED')
        self.assertEqual(self.push_tline(None)[0], 'REJECTED')
        self.assertEqual(BreadTransferLine.objects.filter(quantity_sent=0).count(), 0)

    @expectedFailure   # BUG-1017 (sacs de farine)
    def test_1017_push_session_sans_sacs_refusee_comme_rest(self):
        r = cl(self.g1).post(S, {'team': 'A', 'flour_sacks_used': None, 'date': self.day(), 'lines': []},
                             format='json')
        self.assertEqual(r.status_code, 400)
        s = self.sess(flour_sacks_used=None)
        self.assertEqual(push(self.a1, 'production.ProductionSession', s)[0], 'REJECTED')

    @expectedFailure   # BUG-1018
    def test_1018_souligne_python_refuse_partout_comme_opening(self):
        self.assertEqual(self.rest_open('1_0'), 400)
        bad = []
        for name, status in (('rest_ligne', self.ok(self.rest_line('1_0'))),
                             ('rest_dispo', self.ok(self.rest_disposal('1_0'))),
                             ('push_ligne', self.push_line('1_0') == 'ACCEPTED'),
                             ('push_dispo', self.push_disposal('1_0') == 'ACCEPTED'),
                             ('push_transfert', self.push_tline('1_0')[0] == 'ACCEPTED')):
            if status:
                bad.append(name)
        self.assertEqual(bad, [])

    @expectedFailure   # BUG-1019
    def test_1019_mouvement_negatif_accepte_en_rest_donc_aussi_au_push(self):
        st, _ = ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='SALT', defaults={'unit': 'g'})
        r = cl(self.g1).post(M, {'stock': st.pk, 'movement_type': 'EXIT', 'quantity': '-1', 'unit_price': '1'},
                             format='json')
        self.assertEqual(r.status_code, 201)
        res = push(self.a1, 'production.ConsumableMovement', {
            'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'EXIT',
            'quantity': '-1', 'unit': 'g'})
        self.assertEqual(res[0], 'ACCEPTED', res)
