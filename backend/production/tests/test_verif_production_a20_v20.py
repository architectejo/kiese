"""Testeur-production (cycle 21 / a20) : verification independante de BUG-1015 a 1020 (parseur numerique partage
`core/numeric.py`, regle canonique) par une matrice de formes numeriques sur TOUTES les entrees de quantite de
production, REST et push ; BUG-1021 (litige sans ligne juge sur l'entete) ; question BUG-1020 (stock negatif sans
notification pour une ENTRY). Donnees fictives. L'oracle `canon_int` / `canon_dec` est ecrit ICI, independamment
du code applicatif.
"""
import re
from datetime import date as ddate
from decimal import Decimal
from unittest import expectedFailure

from core.models import SystemNotification
from production.models import (BreadTransfer, BreadTransferLine, ConsumableInventory, ConsumableMovement,
                               ConsumableStock)
from production.tests.test_verif_a4_testeur_production import T, cl
from production.tests.test_verif_production_a8_v8 import PushBase, push, uid
from production.tests.test_verif_production_a19_v19 import A19Base, C, D, M, OPEN, S

NBSP, IDEO, EN = chr(0xA0), chr(0x3000), chr(0x2007)
ASCII_WS = ' \t\n\r\x0b\x0c'


def canon_int(f):
    """Oracle independant : entier selon la regle canonique (valeur >= 1 non verifiee ici)."""
    if isinstance(f, bool) or f is None:
        return False
    if isinstance(f, int):
        return True
    if isinstance(f, float):
        return f == int(f)
    if isinstance(f, str):
        s = f.strip(ASCII_WS)
        return bool(s) and len(s) <= 32 and re.fullmatch(r'[-+]?[0-9]+(\.0+)?', s, re.ASCII) is not None
    return False


def canon_dec(f, places):
    if isinstance(f, bool) or f is None:
        return False
    if isinstance(f, (int, float)):
        s = repr(f)
        if 'e' in s or 'E' in s:
            return False
        f = s
    if isinstance(f, str):
        s = f.strip(ASCII_WS)
        m = re.fullmatch(r'[-+]?[0-9]+(?:\.([0-9]+))?', s, re.ASCII) if s and len(s) <= 32 else None
        return bool(m) and len((m.group(1) or '').rstrip('0')) <= places
    return False


TRAILING = ('0.3330', '00.250', '1.500')  # zeros finaux au-dela des decimales : voir BUG-1031

INT_FORMS = [
    7, '7', '+7', '7.0', '7.00', ' 7 ', '\t7\n', '\r\x0b\x0c7', 7.0, '00007', '+007.000', '0' * 31 + '7',
    True, False, None, '', '   ', '7E0', '7e0', '1e3', '2E+9', '1_0', '٣', '１２', '٠٧', NBSP + '7', '7' + IDEO,
    EN + '7', '7' + chr(0x200b), '7' + chr(0x85), '\x1c7', '\x1f7', '7.5', 7.5, '7.', '.7', '0x7', '--7', '+-7',
    'NaN', 'Infinity', '-Infinity', '7 7', 'a' * 33, '0' * 32 + '7', '0' * 40 + '7', [7], {'a': 7}, '-0', '+0',
]
DEC_FORMS = [
    '0.25', '7', '+7', '7.0', ' 0.5 ', 0.25, 0.333, '00.250', '1.500', '0.3330', '+0.25', 7, 7.0,
    True, None, '', '  ', '1e3', '7E0', '1_0', '٣', '٠.٢٥', NBSP + '0.25', '0.25' + IDEO, '0.0001', 0.0001, '.5',
    '5.', 'NaN', 'Infinity', '-Infinity', [1], {'a': 1}, 'abc', '1,5', '0x7', '1 000',
]


class A20Base(A19Base):
    def setUp(self):
        super().setUp()
        self.st, _ = ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='SALT',
                                                           defaults={'unit': 'g'})

    @staticmethod
    def rest_ok(r):
        assert r.status_code < 500, (r.status_code, r.content)
        return r.status_code in (200, 201)

    def mismatches(self, forms, verdict_fns, oracle, skip=lambda f: False):
        """Chaque entree doit rendre le verdict de l'oracle ; renvoie la liste des ecarts."""
        bad = []
        for f in forms:
            if skip(f):
                continue
            want = oracle(f)
            for name, fn in verdict_fns.items():
                got = fn(f)
                if got != want:
                    bad.append((name, ascii(f), 'attendu' if want else 'refus', 'obtenu' if got else 'refus'))
        return bad


# --------------------------------------------------------------------------- entiers : pains
class IntegerMatrix(A20Base):
    def setUp(self):
        super().setUp()
        from production.models import _adjust_bread_stock
        _adjust_bread_stock(self.k1, self.b3, produced=5000)

    def _positive(self, f):
        # formes canoniques dont la valeur est 0 ou negative : verdict dependant de la borne metier
        return not (isinstance(f, str) and f.strip(ASCII_WS).lstrip('+-').replace('.', '').strip('0') == ''
                    and canon_int(f))

    def test_quantites_de_pains_rest_et_push_suivent_l_oracle(self):
        rec, _ = self.push_sess()

        def push_line(f):
            return push(self.a1, 'production.ProductionSessionLine',
                        {'id': uid(), 'session': rec['id'], 'bread_price': self.b3.pk, 'quantity': f})[0] == 'ACCEPTED'

        def push_disp(f):
            return push(self.a1, 'production.BreadDisposal', {
                'id': uid(), 'session': rec['id'], 'bread_price': self.b3.pk, 'disposal_type': 'UNSOLD',
                'quantity': f, 'unit_price_sold': 0})[0] == 'ACCEPTED'

        def rest_disp(f):
            return self.rest_ok(cl(self.g1).post(D, {'session': rec['id'], 'bread_price': self.b3.pk,
                                                     'disposal_type': 'UNSOLD', 'quantity': f,
                                                     'unit_price_sold': 0}, format='json'))

        fns = {
            'rest_ligne': lambda f: self.rest_ok(cl(self.g1).post(S, {
                'team': 'A', 'flour_sacks_used': '1', 'date': self.day(),
                'lines': [{'bread_price': self.b3.pk, 'quantity': f}]}, format='json')),
            'push_ligne': push_line, 'rest_dispo': rest_disp, 'push_dispo': push_disp,
            'rest_envoi': lambda f: self.rest_ok(cl(self.g1).post(f'{T}send/', {
                'to_node': self.k2.pk, 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': f}]}, format='json')),
            'push_ligne_transfert': lambda f: self.push_tline(f)[0] == 'ACCEPTED',
            'rest_opening': lambda f: self.rest_ok(cl(self.g1).post(OPEN, {
                'date': str(ddate.today()), 'team': 'A', 'lines': [{'bread_price': self.b3.pk, 'qty': f}]},
                format='json')),
        }
        # '-0' / '+0' : 0 pain = refus des lignes/envois (min 1) mais acceptes par les dispositions : hors matrice
        bad = self.mismatches(INT_FORMS, fns, canon_int, skip=lambda f: f in ('-0', '+0'))
        self.assertEqual(bad, [])

    def test_quantite_recue_rest_et_push_suivent_l_oracle(self):
        def rest_recv(f):
            r = cl(self.g1).post(f'{T}send/', {'to_node': self.k2.pk, 'lines': [
                {'bread_price': self.b3.pk, 'quantity_sent': 7}]}, format='json')
            self.assertEqual(r.status_code, 201, r.content)
            r2 = cl(self.g2).post(f'{T}{r.data["id"]}/confirm_reception/', {'lines': [
                {'bread_price': self.b3.pk, 'quantity_received': f}]}, format='json')
            return self.rest_ok(r2)

        def push_recv(f):
            t = {'id': uid(), 'from_node': self.k1.code, 'to_node': self.k2.code}
            push(self.a1, 'production.BreadTransfer', t)
            push(self.a1, 'production.BreadTransferLine',
                 {'transfer': t['id'], 'bread_price': self.b3.pk, 'quantity_sent': 7})
            return push(self.a2, 'production.BreadTransferLine',
                        {'transfer': t['id'], 'bread_price': self.b3.pk, 'quantity_sent': 7,
                         'quantity_received': f})[0] == 'ACCEPTED'

        bad = self.mismatches(INT_FORMS, {'rest_recu': rest_recv, 'push_recu': push_recv}, canon_int,
                              skip=lambda f: f in ('-0', '+0', None))  # None au push = ligne non recue (sans effet)
        self.assertEqual(bad, [])

    def test_prix_unitaire_solde_disposition_rest_et_push_suivent_l_oracle(self):
        rec, _ = self.push_sess()

        def rest_price(f):
            return self.rest_ok(cl(self.g1).post(D, {'session': rec['id'], 'bread_price': self.b3.pk,
                                                     'disposal_type': 'DECLASSED', 'quantity': 3,
                                                     'unit_price_sold': f}, format='json'))

        def push_price(f):
            return push(self.a1, 'production.BreadDisposal', {
                'id': uid(), 'session': rec['id'], 'bread_price': self.b3.pk, 'disposal_type': 'DECLASSED',
                'quantity': 3, 'unit_price_sold': f})[0] == 'ACCEPTED'

        # None / '' : `unit_price_sold or 0` (champ facultatif, 0 par defaut) : verdict hors matrice
        bad = self.mismatches(INT_FORMS, {'rest': rest_price, 'push': push_price}, canon_int,
                              skip=lambda f: f in (None, '', '   ', False, '-0', '+0'))
        self.assertEqual(bad, [])


# --------------------------------------------------------------------------- decimaux : consommables, sacs
class DecimalMatrix(A20Base):
    def _mvt_rest(self, f, mt='ENTRY'):
        return self.rest_ok(cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': mt, 'quantity': f,
                                                 'unit_price': '1'}, format='json'))

    def _mvt_push(self, f, mt='ENTRY'):
        return push(self.a1, 'production.ConsumableMovement', {
            'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': mt,
            'quantity': f, 'unit': 'g'})[0] == 'ACCEPTED'

    def test_mouvements_entree_et_sortie_rest_et_push_suivent_l_oracle(self):
        oracle = lambda f: canon_dec(f, 3)  # noqa: E731
        fns = {'rest_entree': self._mvt_rest, 'push_entree': self._mvt_push,
               'rest_sortie': lambda f: self._mvt_rest(f, 'EXIT'), 'push_sortie': lambda f: self._mvt_push(f, 'EXIT')}
        self.assertEqual(self.mismatches(DEC_FORMS, fns, oracle, skip=lambda f: f in TRAILING), [])

    def test_comptages_rest_et_push_suivent_l_oracle(self):
        def rest_count(f):
            return self.rest_ok(cl(self.g1).post(C, {'consumable_type': 'SALT', 'count_date': str(ddate.today()),
                                                     'physical_quantity': f}, format='json'))

        def push_count(f):
            return push(self.a1, 'production.ConsumableCount', {
                'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'count_date': str(ddate.today()),
                'system_quantity': '0', 'physical_quantity': f,
                'gap': f if canon_dec(f, 3) else '0'})[0] == 'ACCEPTED'

        # un comptage est une quantite physique >= 0 : les formes canoniques sont toutes >= 0 ici
        self.assertEqual(self.mismatches(DEC_FORMS, {'rest': rest_count, 'push': push_count},
                                         lambda f: canon_dec(f, 3), skip=lambda f: f in TRAILING), [])

    def test_inventaire_direction_gerant_suit_l_oracle(self):
        def rest_inv(f):
            ConsumableInventory.objects.all().delete()
            return self.rest_ok(cl(self.g1).post('/api/production/inventories/', {
                'lines': [{'consumable_type': 'SALT', 'physical_quantity': f}]}, format='json'))

        self.assertEqual(self.mismatches(DEC_FORMS, {'rest_inventaire': rest_inv}, lambda f: canon_dec(f, 3),
                                         skip=lambda f: f in TRAILING or f == '1,5'), [])
        self.assertTrue(rest_inv('1,5'))  # meme tolerance de la virgule que le dispatch (parse_qty partage)

    def test_dispatch_direction_suit_l_oracle_virgule_tolerance_documentee(self):
        from production.consumables_direction import siege_node
        ConsumableStock.objects.update_or_create(node=siege_node(), consumable_type='SALT',
                                                 defaults={'unit': 'g', 'quantity': Decimal('9000000')})

        def dispatch(f):
            return self.rest_ok(cl(self.dir).post('/api/production/consumables/dispatch/', {
                'consumable_type': 'SALT', 'allocations': [{'node': self.k1.pk, 'quantity': f}]}, format='json'))

        # 0 refuse (allow_zero=False) : formes a valeur nulle hors matrice
        def nonzero(f):
            return not (canon_dec(f, 3) and Decimal(str(f).strip(ASCII_WS) or '1') == 0)

        bad = self.mismatches(DEC_FORMS, {'dispatch': dispatch}, lambda f: canon_dec(f, 3),
                              skip=lambda f: not nonzero(f) or f == '1,5')
        self.assertEqual(bad, [])
        # tolerance de saisie documentee : « 1,5 » (virgule) devient 1.5 au dispatch uniquement
        self.assertTrue(dispatch('1,5'))
        # mais une virgule ne contourne pas la regle : exposant, non-ASCII refuses malgre la virgule
        for ko in ('1,5e1', '١,٥', '1,5_0'):
            self.assertFalse(dispatch(ko), ko)

    def test_sacs_de_farine_rest_et_push_suivent_l_oracle(self):
        def rest_flour(f):
            return self.rest_ok(cl(self.g1).post(S, {'team': 'A', 'flour_sacks_used': f, 'date': self.day(),
                                                     'lines': []}, format='json'))

        def push_flour(f):
            return push(self.a1, 'production.ProductionSession', self.sess(flour_sacks_used=f))[0] == 'ACCEPTED'

        self.assertEqual(self.mismatches(DEC_FORMS, {'rest': rest_flour, 'push': push_flour},
                                         lambda f: canon_dec(f, 2), skip=lambda f: f in TRAILING), [])

    def test_valeur_du_sac_push_suit_l_oracle_entier(self):
        def push_sac(f):
            return push(self.a1, 'production.ProductionSession', self.sess(sac_value_fc_used=f))[0] == 'ACCEPTED'

        bad = self.mismatches(INT_FORMS, {'push_sac': push_sac}, canon_int,
                              skip=lambda f: f in (None, '', '   ', '-0', '+0'))
        self.assertEqual(bad, [])

    def test_consommables_utilises_rest_suivent_l_oracle(self):
        def rest_used(f):
            return self.rest_ok(cl(self.g1).post(S, {
                'team': 'A', 'flour_sacks_used': '1', 'date': self.day(), 'lines': [],
                'consumables_used': [{'consumable_type': 'SALT', 'quantity': f}]}, format='json'))

        # arrondi a 3 decimales volontairement conserve (historique) : places=12 pour l'oracle
        bad = self.mismatches(DEC_FORMS, {'rest': rest_used}, lambda f: canon_dec(f, 12),
                              skip=lambda f: f in (None, ''))
        self.assertEqual(bad, [])

    def test_tolerance_historique_arrondi_consommables_utilises(self):
        """Point d'attention : `consumables_used` arrondit '0.0001' a 0.000 alors que mouvements/comptages/dispatch
        refusent. Documente, pas un defaut (valeur sans effet de stock, comportement BUG-219)."""
        r = cl(self.g1).post(S, {'team': 'A', 'flour_sacks_used': '1', 'date': self.day(), 'lines': [],
                                 'consumables_used': [{'consumable_type': 'SALT', 'quantity': '0.0004'}]},
                             format='json')
        self.assertEqual(r.status_code, 201, r.content)


class ZerosFinaux(A20Base):
    @expectedFailure
    def test_1031_zeros_finaux_meme_verdict_rest_et_push(self):
        """BUG-1031 : '0.3330' (mouvement, 3 decimales) et '1.500' (sacs, 2 decimales) : acceptes au push
        (parseur partage, valeur exacte), refuses en REST (DecimalField DRF compte les zeros finaux)."""
        bad = []
        for f in ('0.3330', '1.500'):
            rest = cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': f,
                                        'unit_price': '1'}, format='json').status_code in (200, 201)
            pushed = push(self.a1, 'production.ConsumableMovement', {
                'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'ENTRY',
                'quantity': f, 'unit': 'g'})[0] == 'ACCEPTED'
            if rest != pushed:
                bad.append(('mvt', f, rest, pushed))
        rest = cl(self.g1).post(S, {'team': 'A', 'flour_sacks_used': '1.500', 'date': self.day(), 'lines': []},
                                format='json').status_code in (200, 201)
        pushed = push(self.a1, 'production.ProductionSession', self.sess(flour_sacks_used='1.500'))[0] == 'ACCEPTED'
        if rest != pushed:
            bad.append(('sacs', '1.500', rest, pushed))
        self.assertEqual(bad, [])


# --------------------------------------------------------------------------- unit_price des mouvements
class UnitPriceQuestion(A20Base):
    def test_unit_price_verdicts_rest_vs_push(self):
        """Question de l'agent : le prix garde son controle historique (non ASCII), seule la quantite suit la
        regle canonique. Table REST / push pour juger l'incoherence."""
        forms = ['1_0', '1e1', '1E1', ' 5 ', '+5', '5.0', '٣', NBSP + '5', '5' + IDEO, True, 'NaN', 'Infinity',
                 '5.12345', 5, 5.5, '0.5', '1' + '0' * 20, '-5', '0x5', '5,5', [5]]
        rows = []
        for f in forms:
            r = cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': '1',
                                     'unit_price': f}, format='json')
            p = push(self.a1, 'production.ConsumableMovement', {
                'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'ENTRY',
                'quantity': '1', 'unit': 'g', 'unit_price': f})
            rows.append((ascii(f), r.status_code, p[0]))
        print('\nUNIT_PRICE (forme, REST, push):')
        for row in rows:
            print('   ', row)
        self.assertTrue(all(r[1] < 500 for r in rows))

    @expectedFailure
    def test_1032_unit_price_negatif_meme_verdict_rest_et_push(self):
        """BUG-1032 : prix unitaire d'entree negatif '-5' : accepte en REST (201), refuse au push."""
        r = cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': '1',
                                 'unit_price': '-5'}, format='json')
        p = push(self.a1, 'production.ConsumableMovement', {
            'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'ENTRY',
            'quantity': '1', 'unit': 'g', 'unit_price': '-5'})[0]
        self.assertEqual(r.status_code in (200, 201), p == 'ACCEPTED', (r.status_code, p))

    @expectedFailure
    def test_1033_unit_price_souligne_et_exposant_refuses_comme_la_quantite(self):
        """BUG-1033 (voir registre) : '1_0' / '1e1' acceptes comme prix unitaire de mouvement alors que la meme
        forme est refusee comme quantite."""
        accepted = []
        for f in ('1_0', '1e1', '1E1'):
            r = cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': '1',
                                     'unit_price': f}, format='json')
            if r.status_code in (200, 201):
                accepted.append(('rest', f))
            p = push(self.a1, 'production.ConsumableMovement', {
                'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'ENTRY',
                'quantity': '1', 'unit': 'g', 'unit_price': f})[0]
            if p == 'ACCEPTED':
                accepted.append(('push', f))
        self.assertEqual(accepted, [])


# --------------------------------------------------------------------------- poste ancien : "" pour les sacs
class AncienPoste(A20Base):
    def test_sacs_vide_refuse_en_push_comme_en_rest_et_sans_effet(self):
        from production.models import ProductionSession
        n = ProductionSession.objects.count()
        r = cl(self.g1).post(S, {'team': 'A', 'flour_sacks_used': '', 'date': self.day(), 'lines': []},
                             format='json')
        self.assertEqual(r.status_code, 400)
        res = push(self.a1, 'production.ProductionSession', self.sess(flour_sacks_used=''))
        self.assertEqual(res[0], 'REJECTED')
        self.assertIn('flour_sacks_used', res[1] or '')  # raison explicite, lisible par le poste
        self.assertEqual(ProductionSession.objects.count(), n)

    def test_sacs_absents_du_push_creation_et_mise_a_jour_restent_acceptes(self):
        """Un poste qui N'EXPORTE PAS la cle (ancien format) n'est pas touche, seul le « » explicite l'est."""
        rec = self.sess()
        rec.pop('flour_sacks_used')
        self.assertEqual(push(self.a1, 'production.ProductionSession', rec)[0], 'ACCEPTED')


# --------------------------------------------------------------------------- BUG-1020 / BUG-1021
class EntryNegatif(A20Base):
    def _notifs(self):
        return SystemNotification.objects.filter(title__startswith='Stock négatif').count()

    def test_sortie_depassant_le_stock_cree_une_alerte_reference(self):
        cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': '3', 'unit_price': '1'},
                         format='json')
        n = self._notifs()
        cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'EXIT', 'quantity': '5', 'unit_price': '1'},
                         format='json')
        self.assertEqual(self._notifs(), n + 1)

    def test_entree_negative_parite_rest_push_stock_final(self):
        cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': '3', 'unit_price': '1'},
                         format='json')
        self.assertTrue(self._mvt_push('-5'))
        self.st.refresh_from_db()
        self.assertEqual(self.st.quantity, Decimal('-2'))

    def _mvt_push(self, q):
        return push(self.a1, 'production.ConsumableMovement', {
            'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'ENTRY',
            'quantity': q, 'unit': 'g'})[0] == 'ACCEPTED'

    @expectedFailure
    def test_1034_entree_negative_sous_zero_signale_comme_une_sortie(self):
        """BUG-1034 (voir registre) : ENTRY -5 sur un stock de 3 (-> -2) ne cree aucune alerte « Stock negatif »."""
        cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': '3', 'unit_price': '1'},
                         format='json')
        n = self._notifs()
        r = cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': '-5',
                                 'unit_price': '1'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.st.refresh_from_db()
        self.assertLess(self.st.quantity, 0)
        self.assertEqual(self._notifs(), n + 1)


class LitigeSansLigne(A20Base):
    def _disputed(self, sent, recv):
        return BreadTransfer.objects.create(from_node=self.k1, to_node=self.k2, bread_price=self.b3,
                                            quantity_sent=sent, quantity_received=recv,
                                            transfer_status='DISPUTED', node_origin='P1')

    def _lift(self, api, t):
        push(api, 'production.BreadTransfer', {'id': str(t.pk), 'transfer_status': 'CONFIRMED'})
        t.refresh_from_db()
        return t.transfer_status

    def test_ecart_d_entete_empeche_la_levee_par_les_deux_noeuds(self):
        for api in ('a1', 'a2'):
            for sent, recv in ((100, 98), (100, None), (100, 0), (98, 100), (None, 5)):
                t = self._disputed(sent, recv)
                self.assertFalse(t.lines.exists())
                self.assertEqual(self._lift(getattr(self, api), t), 'DISPUTED', (api, sent, recv))

    def test_entete_egal_se_leve(self):
        for api in ('a1', 'a2'):
            t = self._disputed(100, 100)
            self.assertEqual(self._lift(getattr(self, api), t), 'CONFIRMED', api)

    def test_entete_egal_mais_record_avec_autre_quantite_ne_contourne_pas(self):
        t = self._disputed(100, 98)
        push(self.a2, 'production.BreadTransfer', {'id': str(t.pk), 'transfer_status': 'CONFIRMED',
                                                    'quantity_received': 100, 'quantity_sent': 98})
        t.refresh_from_db()
        self.assertEqual((t.transfer_status, t.quantity_received, t.quantity_sent), ('DISPUTED', 98, 100))

    def test_avec_lignes_le_comportement_966_est_inchange(self):
        t = self._disputed(100, 98)
        BreadTransferLine.objects.create(transfer=t, bread_price=self.b3, quantity_sent=100, quantity_received=98)
        self.assertEqual(self._lift(self.a2, t), 'DISPUTED')
        BreadTransferLine.objects.filter(transfer=t).update(quantity_received=100)
        self.assertEqual(self._lift(self.a2, t), 'CONFIRMED')

    @expectedFailure
    def test_1035_litige_d_entete_sans_ligne_bloque_la_cloture_de_la_receptrice(self):
        """BUG-1035 : litige sans ligne (push d'un poste a entetes seuls : envoi direct RESPONDED puis
        DISPUTED avec quantity_received != quantity_sent) : la cloture n'est PAS bloquee alors que le push
        refuse de le lever (BUG-1021) ; le gap de cloture ne regarde que les lignes."""
        from treasury.views import _unresolved_incoming_transfer_gap
        tid = uid()
        push(self.a1, 'production.BreadTransfer', {'id': tid, 'from_node': self.k1.code, 'to_node': self.k2.code,
                                                    'transfer_status': 'RESPONDED', 'quantity_sent': 100,
                                                    'flow': 'DIRECT'})
        push(self.a2, 'production.BreadTransfer', {'id': tid, 'transfer_status': 'DISPUTED',
                                                    'quantity_received': 98})
        t = BreadTransfer.objects.get(pk=tid)
        self.assertEqual((t.transfer_status, t.quantity_sent, t.quantity_received, t.lines.count()),
                         ('DISPUTED', 100, 98, 0))
        self.assertTrue(_unresolved_incoming_transfer_gap(self.k2))
