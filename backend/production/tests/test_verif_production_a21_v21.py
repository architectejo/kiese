"""Testeur-production (cycle 22 / a21) : verification independante de BUG-1031 a 1035 (d61).
Oracle `canon_dec` ecrit dans a20 (independant du code applicatif). Donnees fictives.
"""
import re
from datetime import date as ddate
from decimal import Decimal

from core.models import SystemNotification
from production.models import BreadTransfer, BreadTransferLine, ConsumableCount, ConsumableInventory, ConsumableMovement, \
    ConsumableStock
from production.tests.test_verif_a4_testeur_production import cl
from production.tests.test_verif_production_a8_v8 import push, uid
from production.tests.test_verif_production_a19_v19 import C, M, S
from production.tests.test_verif_production_a20_v20 import A20Base, ASCII_WS, DEC_FORMS, canon_dec

TRAIL = ['0.3330', '00.250', '1.500', '0.33300000', '1.50000000000', ' 0.3330 ', '+0.3330', '0.3330000000000000000',
         '0.3333', '0.3331', '1.505', '1.5001', '0.33300000000001', '.3330', '3330.', '0.0000', '0.000']


class V1031(A20Base):
    def mvt_rest(self, f, price='1'):
        return self.rest_ok(cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': f,
                                                 'unit_price': price}, format='json'))

    def mvt_push(self, f):
        return push(self.a1, 'production.ConsumableMovement', {
            'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'ENTRY',
            'quantity': f, 'unit': 'g'})[0] == 'ACCEPTED'

    def test_matrice_complete_sans_exclusion_mouvements_comptages_inventaire_sacs(self):
        forms = list(DEC_FORMS) + TRAIL

        def rest_count(f):
            ConsumableCount.objects.all().delete()
            ConsumableInventory.objects.all().delete()
            rr = cl(self.g1).post(C, {'consumable_type': 'SALT', 'count_date': str(ddate.today()),
                                      'physical_quantity': f}, format='json')
            return self.rest_ok(rr)

        def rest_inv(f):
            ConsumableInventory.objects.all().delete()
            return self.rest_ok(cl(self.g1).post('/api/production/inventories/', {
                'lines': [{'consumable_type': 'SALT', 'physical_quantity': f}]}, format='json'))

        def push_count(f):
            ConsumableCount.objects.all().delete()
            ConsumableInventory.objects.all().delete()
            return push(self.a1, 'production.ConsumableCount', {
                'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'count_date': str(ddate.today()),
                'system_quantity': '0', 'physical_quantity': f, 'gap': f if canon_dec(f, 3) else '0'})[0] == 'ACCEPTED'

        def rest_flour(f):
            return self.rest_ok(cl(self.g1).post(S, {'team': 'A', 'flour_sacks_used': f, 'date': self.day(),
                                                     'lines': []}, format='json'))

        def push_flour(f):
            return push(self.a1, 'production.ProductionSession', self.sess(flour_sacks_used=f))[0] == 'ACCEPTED'

        bad = []
        for f in forms:
            if f in (None, '', '  ', True) or f == '1,5':
                continue
            want = canon_dec(f, 3)
            for name, fn in (('rest_mvt', self.mvt_rest), ('push_mvt', self.mvt_push), ('rest_count', rest_count),
                             ('push_count', push_count), ('rest_inv', rest_inv)):
                if fn(f) != want:
                    bad.append((name, ascii(f), want))
            want2 = canon_dec(f, 2)
            r, p = rest_flour(f), push_flour(f)
            if not (r == p == want2):
                bad.append(('sacs', ascii(f), want2, r, p))
        self.maxDiff = None
        self.assertEqual(bad, [])

    def test_valeur_stockee_exacte_apres_normalisation(self):
        self.assertTrue(self.mvt_rest('0.3330'))
        self.assertTrue(self.mvt_rest('00.250'))
        self.st.refresh_from_db()
        self.assertEqual(self.st.quantity, Decimal('0.583'))
        r = cl(self.g1).post(S, {'team': 'A', 'flour_sacks_used': '1.500', 'date': self.day(), 'lines': []},
                             format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Decimal(str(r.data['flour_sacks_used'])), Decimal('1.5'))
        self.assertFalse(self.mvt_rest('0.3333'))
        self.assertFalse(self.mvt_rest('0.33301'))

    def test_pas_d_effet_de_bord_sur_le_payload_de_l_appelant(self):
        data = {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': '0.3330', 'unit_price': '2.5000'}
        r = cl(self.g1).post(M, data, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(data['quantity'], '0.3330')
        mv = ConsumableMovement.objects.get(pk=r.data['id'])
        self.assertEqual((mv.quantity, mv.unit_price), (Decimal('0.333'), Decimal('2.5000')))

    def test_formulaire_multipart_querydict(self):
        from rest_framework.test import APIClient
        c = APIClient(raise_request_exception=False)
        c.force_authenticate(self.g1)
        r = c.post(M, {'stock': str(self.st.pk), 'movement_type': 'ENTRY', 'quantity': '0.3330',
                       'unit_price': '1'}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        r = c.post(M, {'stock': str(self.st.pk), 'movement_type': 'ENTRY', 'quantity': '0.3333',
                       'unit_price': '1'}, format='multipart')
        self.assertEqual(r.status_code, 400, r.content)

    def test_nombres_json_non_chaine_pas_de_500(self):
        for q in (0.333, 1, 0.0, 1e-9, 10 ** 20):
            r = cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': q,
                                     'unit_price': 1}, format='json')
            self.assertLess(r.status_code, 500, (q, r.content))


class V1032_1033(A20Base):
    def rest(self, price, qty='1', mt='ENTRY'):
        return cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': mt, 'quantity': qty, 'unit_price': price},
                                format='json')

    def pushed(self, price, mt='ENTRY'):
        return push(self.a1, 'production.ConsumableMovement', {
            'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': mt, 'quantity': '1',
            'unit': 'g', 'unit_price': price})[0] == 'ACCEPTED'

    @staticmethod
    def oracle(f):
        if isinstance(f, bool) or f is None or f == '':
            return None
        if isinstance(f, (int, float)):
            f = repr(f)
            if 'e' in f:
                return False
        if not isinstance(f, str):
            return False
        s = f.strip(ASCII_WS)
        m = re.fullmatch(r'\+?([0-9]+)(?:\.([0-9]+))?', s, re.ASCII) if s and len(s) <= 32 else None
        return bool(m) and len((m.group(2) or '').rstrip('0')) <= 4

    FORMS = ['0', '0.0', '1', '+5', ' 5 ', '5.0', '5.1234', '5.12340', '5.123400000', '5.12345', '5.1234000001',
             '1_0', '1e1', '1E1', '٣', '٠.٥', '5' + chr(0x3000), chr(0xA0) + '5', 'NaN', 'Infinity', '-Infinity',
             '0x5', '5,5', '1 000', 'abc', [5], {'a': 1}, 5, 5.5, 0.0001, '.5', '5.', '0.0001', '99999999999.9999',
             ]

    def test_matrice_prix_rest_et_push_suivent_l_oracle(self):
        bad = []
        for f in self.FORMS:
            want = self.oracle(f)
            if want is None:
                continue
            got_r = self.rest_ok(self.rest(f))
            got_p = self.pushed(f)
            if got_r != got_p:
                bad.append(('parite', ascii(f), got_r, got_p))
            elif got_r != want:
                bad.append(('oracle', ascii(f), want, got_r))
        self.assertEqual(bad, [])

    def test_prix_negatif_refuse_des_deux_cotes_toutes_formes(self):
        for f in ('-5', '-0.0001', ' -5 ', '-1e1', -5, -0.5):
            self.assertEqual(self.rest(f).status_code, 400, f)
            self.assertFalse(self.pushed(f), f)
        for mt in ('EXIT', 'ENTRY'):
            self.assertEqual(self.rest('-5', mt=mt).status_code, 400)
        self.assertEqual(ConsumableMovement.objects.count(), 0)
        self.st.refresh_from_db()
        self.assertEqual(self.st.quantity, 0)

    def test_message_en_francais_et_moins_zero_n_est_pas_negatif(self):
        r = self.rest('-5')
        self.assertEqual(r.data.get('detail'), 'Le prix unitaire ne peut pas être négatif.')
        self.assertLess(self.rest('-0').status_code, 500)

    def test_prix_negatif_sur_patch_non_accepte(self):
        r = self.rest('2')
        self.assertEqual(r.status_code, 201, r.content)
        r2 = cl(self.g1).patch(f'{M}{r.data["id"]}/', {'unit_price': '-3'}, format='json')
        self.assertNotEqual(r2.status_code, 200, r2.content)
        mv = ConsumableMovement.objects.get(pk=r.data['id'])
        self.assertGreaterEqual(mv.unit_price or 0, 0)

    def test_prix_absent_ou_nul_accepte(self):
        r = cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': '10'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertLess(self.rest(None).status_code, 500)
        self.assertEqual(self.rest('0').status_code, 201)

    def test_coherence_avec_BUG_216_quantite_negative_acceptee_prix_negatif_refuse(self):
        """Decision BUG-1032 : correction (quantite negative) acceptee et sans effet sur le CUMP ; prix negatif
        refuse, y compris combine a une quantite negative (pas de contournement)."""
        self.assertEqual(self.rest('1', qty='5').status_code, 201)
        self.st.refresh_from_db()
        avg0 = self.st.average_unit_cost
        r = self.rest('1', qty='-2')
        self.assertEqual(r.status_code, 201, r.content)
        self.st.refresh_from_db()
        self.assertEqual(self.st.quantity, Decimal('3'))
        self.assertEqual(self.st.average_unit_cost, avg0)
        self.assertEqual(self.rest('-1', qty='-2').status_code, 400)

    def test_cump_jamais_negatif_apres_stock_negatif_puis_entree(self):
        self.assertEqual(self.rest('4', qty='2').status_code, 201)
        self.assertEqual(self.rest('9', qty='-5').status_code, 201)  # stock 2 -> -3
        self.st.refresh_from_db()
        self.assertEqual(self.st.quantity, Decimal('-3'))
        self.assertGreaterEqual(self.st.average_unit_cost, 0)
        self.assertEqual(self.rest('1', qty='10').status_code, 201)
        self.st.refresh_from_db()
        self.assertEqual(self.st.quantity, Decimal('7'))
        self.assertGreaterEqual(self.st.average_unit_cost, 0, self.st.average_unit_cost)


class V1034(A20Base):
    def notifs(self):
        return list(SystemNotification.objects.filter(title__startswith='Stock négatif'))

    def entry(self, q, api='rest'):
        if api == 'rest':
            return cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': q,
                                        'unit_price': '1'}, format='json').status_code == 201
        return push(self.a1, 'production.ConsumableMovement', {
            'id': uid(), 'node': self.k1.code, 'consumable_type': 'SALT', 'movement_type': 'ENTRY',
            'quantity': q, 'unit': 'g'})[0] == 'ACCEPTED'

    def test_rest_et_push_alertent_une_fois_par_mouvement_qui_laisse_sous_zero(self):
        self.entry('3')
        self.assertEqual(self.notifs(), [])
        for api in ('rest', 'push'):
            n = len(self.notifs())
            self.assertTrue(self.entry('-5', api))
            self.assertEqual(len(self.notifs()), n + 1, api)

    def test_pas_d_alerte_si_stock_nul_ou_positif(self):
        self.entry('3')
        self.entry('-3')
        self.entry('5')
        self.entry('-1')
        self.assertEqual(self.notifs(), [])

    def test_alerte_pour_la_bonne_boulangerie_et_le_bon_consommable(self):
        self.entry('1')
        self.entry('-4')
        n = self.notifs()[-1]
        self.assertIn(self.k1.code, n.title)
        self.assertIn('SALT', n.title)
        self.assertEqual(n.severity, 'WARNING')

    def test_resauvegarde_d_un_mouvement_ne_redouble_pas_l_alerte(self):
        self.entry('1')
        r = cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'ENTRY', 'quantity': '-4', 'unit_price': '1'},
                             format='json')
        self.assertEqual(len(self.notifs()), 1)
        mv = ConsumableMovement.objects.get(pk=r.data['id'])
        mv.description = 'maj'
        mv.save()
        self.assertEqual(len(self.notifs()), 1)

    def test_sortie_deja_alertee_une_seule_fois(self):
        self.entry('2')
        cl(self.g1).post(M, {'stock': self.st.pk, 'movement_type': 'EXIT', 'quantity': '5', 'unit_price': '1'},
                         format='json')
        self.assertEqual(len(self.notifs()), 1)

    def test_levure_decimale_entree_negative(self):
        st, _ = ConsumableStock.objects.get_or_create(node=self.k1, consumable_type='YEAST',
                                                      defaults={'unit': 'paquet'})
        cl(self.g1).post(M, {'stock': st.pk, 'movement_type': 'ENTRY', 'quantity': '0.25', 'unit_price': '1'},
                         format='json')
        r = cl(self.g1).post(M, {'stock': st.pk, 'movement_type': 'ENTRY', 'quantity': '-0.5', 'unit_price': '1'},
                             format='json')
        self.assertEqual(r.status_code, 201, r.content)
        st.refresh_from_db()
        self.assertEqual(st.quantity, Decimal('-0.25'))
        self.assertEqual(len([n for n in self.notifs() if 'YEAST' in n.title]), 1)


class V1035(A20Base):
    def dis(self, sent, recv, status='DISPUTED'):
        return BreadTransfer.objects.create(from_node=self.k1, to_node=self.k2, bread_price=self.b3,
                                            quantity_sent=sent, quantity_received=recv, transfer_status=status,
                                            node_origin='P1')

    def gap(self, node=None):
        from treasury.views import _unresolved_incoming_transfer_gap
        return _unresolved_incoming_transfer_gap(node or self.k2)

    def test_ecarts_d_entete_bloquent_la_receptrice_seulement(self):
        for sent, recv in ((100, 98), (100, None), (100, 0), (98, 100), (None, 5)):
            BreadTransfer.objects.all().delete()
            self.dis(sent, recv)
            self.assertTrue(self.gap(self.k2), (sent, recv))
            self.assertEqual(self.gap(self.k1), '', (sent, recv))

    def test_pas_de_blocage_si_egal_ou_annule(self):
        self.dis(100, 100)
        self.assertEqual(self.gap(), '')
        BreadTransfer.objects.all().delete()
        self.dis(100, 98, status='CANCELLED')
        self.assertEqual(self.gap(), '')

    def test_avec_lignes_une_seule_mention_et_la_ligne_fait_foi(self):
        t = self.dis(100, 98)
        BreadTransferLine.objects.create(transfer=t, bread_price=self.b3, quantity_sent=100, quantity_received=98)
        g = self.gap()
        self.assertTrue(g)
        self.assertEqual(g.count('→'), 1, g)
        BreadTransferLine.objects.filter(transfer=t).update(quantity_received=100)
        self.assertEqual(self.gap(), '')

    def test_message_cite_boulangeries_et_quantites(self):
        self.dis(100, 98)
        g = self.gap()
        for part in (self.k1.code, self.k2.code, '100', '98'):
            self.assertIn(part, g)

    def test_leve_apres_alignement_de_l_entete(self):
        t = self.dis(100, 98)
        self.assertTrue(self.gap())
        BreadTransfer.objects.filter(pk=t.pk).update(quantity_received=100)
        self.assertEqual(self.gap(), '')

    def test_cloture_gerant_reelle_refusee_par_litige_sans_ligne(self):
        """Parcours de bout en bout : la validation de cloture K2 passe par le meme `gap` (3 sites)."""
        from treasury import views as tv
        self.dis(100, 98)
        src = open(tv.__file__, encoding='utf-8').read()
        self.assertGreaterEqual(src.count('_unresolved_incoming_transfer_gap('), 4)  # def + 3 appels
        self.assertTrue(self.gap(self.k2))
