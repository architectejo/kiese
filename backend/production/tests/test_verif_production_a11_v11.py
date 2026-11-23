"""Testeur-production (cycle 12 / a11) : verification independante de BUG-938/939/940 (collision en chaine
d'ids de lignes de facture entre 3 postes, id hostiles, mise a jour d'une fournee ouverte, fournee close
intacte, bornes, autre noeud) + cycle sync_now complet sur 3 postes simules + revue des choix d25/d28.
Donnees fictives. Les `@expectedFailure` referencent leur ticket.
"""
import itertools
import uuid
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.utils import timezone

from core.models import BreadPrice
from production.models import (BreadStock, BreadTransfer, BreadTransferLine, ConsumableCount,
                               ConsumableInventory, ProductionSession, ProductionSessionLine)
from production.tests.test_verif_production_a8_v8 import PUSH, PushBase, api_for, push, uid
from production.tests.test_verif_production_a9_v9 import (LBL_I, LBL_IL, LBL_L, LBL_S, LBL_T, LBL_TL, lot)
from sales.models import Invoice, InvoiceLine
from sync.management.commands.sync_now import (apply_pull_response, apply_push_response,
                                               build_outbound_payload)


def ok(res):
    return all(x[0] == 'ACCEPTED' for v in res.values() for x in v)


class V11Base(PushBase):
    def setUp(self):
        super().setUp()
        self.a3 = api_for(self.k3)
        self.b4 = BreadPrice.objects.create(category='MICRO_200', label='P200', unit_price=200)

    def il(self, inv, bp, q, id_=None, **kw):
        r = {'invoice': inv['id'], 'bread_price': bp.pk, 'quantity': q}
        if id_ is not None:
            r['id'] = str(id_)
        r.update(kw)
        return r

    def invs(self):
        """Une facture par poste (K1, K2, K3) poussee."""
        out = []
        for api, node in ((self.a1, self.k1), (self.a2, self.k2), (self.a3, self.k3)):
            i = self.inv(node=node.code)
            self.assertEqual(push(api, LBL_I, i)[0], 'ACCEPTED')
            out.append(i)
        return out

    def lines_of(self, inv):
        return {l.bread_price_id: (l.quantity, l.line_total) for l in InvoiceLine.objects.filter(invoice_id=inv['id'])}

    def post(self, api, payload):
        r = api.post(PUSH, payload, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.data


# --------------------------------------------------------------------------- BUG-938/940 : lignes de facture
class V11InvoiceLineChain(V11Base):
    def _plan(self, i1, i2, i3):
        """Chaque poste a des lignes locales 1..3 : memes ids partout, categories differentes."""
        return [
            (self.a1, [self.il(i1, self.b3, 3, 1), self.il(i1, self.b5, 5, 2)]),
            (self.a2, [self.il(i2, self.b3, 4, 1), self.il(i2, self.b5, 6, 2), self.il(i2, self.b4, 8, 3)]),
            (self.a3, [self.il(i3, self.b3, 7, 1), self.il(i3, self.b5, 9, 2), self.il(i3, self.b4, 2, 3),
                       self.il(i3, self.b3, 1, 4)]),
        ]

    def _expect(self, i1, i2, i3):
        self.assertEqual(self.lines_of(i1), {self.b3.pk: (3, Dc(900)), self.b5.pk: (5, Dc(2500))})
        self.assertEqual(self.lines_of(i2), {self.b3.pk: (4, Dc(1200)), self.b5.pk: (6, Dc(3000)),
                                             self.b4.pk: (8, Dc(1600))})
        # K3 : deux lignes pain 3 (7 puis 1) -> meme categorie : limite connue, au moins l'une est conservee
        got = self.lines_of(i3)
        self.assertEqual(got[self.b5.pk], (9, Dc(4500)))
        self.assertEqual(got[self.b4.pk], (2, Dc(400)))
        self.assertIn(self.b3.pk, got)

    def test_chaine_trois_postes_six_ordres_d_arrivee(self):
        for perm in itertools.permutations(range(3)):
            Invoice.objects.all().delete()
            i1, i2, i3 = self.invs()
            plan = self._plan(i1, i2, i3)
            for k in perm:
                api, lines = plan[k]
                res = lot(api, sales__InvoiceLine=lines)
                self.assertTrue(ok(res), (perm, res))
            self._expect(i1, i2, i3)
            ids = list(InvoiceLine.objects.values_list('pk', flat=True))
            self.assertEqual(len(ids), len(set(ids)))

    def test_chaine_rejeu_complet_n_ajoute_rien(self):
        i1, i2, i3 = self.invs()
        plan = self._plan(i1, i2, i3)
        for api, lines in plan:
            lot(api, sales__InvoiceLine=lines)
        n = InvoiceLine.objects.count()
        snap = {l.pk: (l.invoice_id, l.bread_price_id, l.quantity) for l in InvoiceLine.objects.all()}
        for _ in range(3):
            for api, lines in reversed(plan):
                self.assertTrue(ok(lot(api, sales__InvoiceLine=lines)))
        self.assertEqual(InvoiceLine.objects.count(), n)
        self.assertEqual(snap, {l.pk: (l.invoice_id, l.bread_price_id, l.quantity) for l in InvoiceLine.objects.all()})

    def test_chaine_modification_quantite_apres_collision_vise_la_bonne_ligne(self):
        i1, i2, i3 = self.invs()
        for api, lines in self._plan(i1, i2, i3):
            lot(api, sales__InvoiceLine=lines)
        # K2 corrige sa ligne locale 2 (pain 5) : seule celle-ci bouge
        self.assertEqual(push(self.a2, LBL_IL, self.il(i2, self.b5, 2, 2))[0], 'ACCEPTED')
        self.assertEqual(self.lines_of(i2)[self.b5.pk][0], 2)
        self.assertEqual(self.lines_of(i2)[self.b3.pk][0], 4)
        self.assertEqual(self.lines_of(i1)[self.b5.pk][0], 5)
        self.assertEqual(self.lines_of(i3)[self.b5.pk][0], 9)

    def test_ligne_poussee_sur_facture_autre_noeud_avec_id_collision_ne_touche_rien(self):
        i1, i2, i3 = self.invs()
        lot(self.a1, sales__InvoiceLine=[self.il(i1, self.b3, 3, 1)])
        pk1 = InvoiceLine.objects.get(invoice_id=i1['id']).pk
        for api in (self.a2, self.a3):
            self.assertEqual(push(api, LBL_IL, self.il(i1, self.b3, 99, pk1))[0], 'REJECTED')
            self.assertEqual(push(api, LBL_IL, self.il(i1, self.b5, 99, 55))[0], 'REJECTED')
        self.assertEqual(self.lines_of(i1), {self.b3.pk: (3, Dc(900))})

    def test_ids_hostiles_jamais_500_jamais_de_doublon(self):
        i1, _, _ = self.invs()
        for bad in (None, '', 'abc', '-3', '٧', '7.0', ' 7 ', '9' * 40, 10 ** 30, 2 ** 63, True, 7.0, [7], {'a': 1}):
            InvoiceLine.objects.all().delete()
            rec = {'invoice': i1['id'], 'bread_price': self.b5.pk, 'quantity': 2}
            if bad is not None:
                rec['id'] = bad
            for _ in range(2):
                r = self.a1.post(PUSH, {'batch_id': uid(), 'records': {LBL_IL: [rec]}}, format='json')
                self.assertEqual(r.status_code, 200, (bad, r.content))
            self.assertLessEqual(InvoiceLine.objects.filter(invoice_id=i1['id']).count(), 1, bad)

    def test_id_enorme_motif_explicite(self):
        """Choix a valider : un id numerique hors plage SQLite (10**30) est refuse sans 500. Le motif est-il
        generique (« erreur serveur ») ? Note : acceptable, aucun poste reel n'emet un tel id."""
        i1, _, _ = self.invs()
        r = push(self.a1, LBL_IL, {'invoice': i1['id'], 'bread_price': self.b5.pk, 'quantity': 2, 'id': str(10 ** 30)})
        self.assertIn(r[0], ('ACCEPTED', 'REJECTED'))
        self.assertEqual(InvoiceLine.objects.filter(invoice_id=i1['id']).count(), 1 if r[0] == 'ACCEPTED' else 0)

    def test_BUG_951_reference_facture_malformee_ne_modifie_pas_une_ligne_existante(self):
        """BUG-955 : `invoice` present mais non UUID + id d'une ligne existante du MEME noeud -> la ligne est
        retrouvee par l'id seul (invoice_uuid None) et sa quantite ECRASEE, ACCEPTED, alors que la facture
        citee est invalide. Attendu : rejet (dependance manquante : invoice) sans effet."""
        i1, _, _ = self.invs()
        lot(self.a1, sales__InvoiceLine=[self.il(i1, self.b3, 3, 1)])
        pk1 = InvoiceLine.objects.get(invoice_id=i1['id']).pk
        for garbage in ('pas-un-uuid', 12345, '', ['x']):
            res = push(self.a1, LBL_IL, {'id': str(pk1), 'invoice': garbage, 'bread_price': self.b3.pk,
                                         'quantity': 1})
            self.assertEqual(res[0], 'REJECTED', garbage)
            self.assertEqual(InvoiceLine.objects.get(pk=pk1).quantity, 3, garbage)

    def test_deux_lignes_meme_categorie_prix_differents_sont_distinguees(self):
        """Cle naturelle (facture, categorie, prix net) : une ligne soldee et une ligne pleine du meme pain."""
        i1, _, _ = self.invs()
        a = self.il(i1, self.b3, 3, 1, unit_price=300, full_unit_price=300)
        b = self.il(i1, self.b3, 4, 2, unit_price=225, full_unit_price=300)
        self.assertTrue(ok(lot(self.a1, sales__InvoiceLine=[a, b])))
        rows = sorted((l.unit_price, l.quantity) for l in InvoiceLine.objects.filter(invoice_id=i1['id']))
        self.assertEqual(rows, [(225, 4), (300, 3)])
        for _ in range(2):
            self.assertTrue(ok(lot(self.a1, sales__InvoiceLine=[a, b])))
        self.assertEqual(InvoiceLine.objects.filter(invoice_id=i1['id']).count(), 2)


# --------------------------------------------------------------------------- BUG-939 : fournee ouverte / close
class V11SessionUpdate(V11Base):
    def _open(self, **kw):
        s = self.sess(flour_sacks_used='2.00', sac_value_fc_used=200000, **kw)
        self.assertEqual(push(self.a1, LBL_S, s)[0], 'ACCEPTED')
        push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 100})
        return s

    def test_ouverte_farine_valeur_sac_notes_propages_et_totaux_recalcules(self):
        s = self._open()
        self.assertEqual(push(self.a1, LBL_S, dict(s, flour_sacks_used='3.75', sac_value_fc_used=150000,
                                                   notes='corrige'))[0], 'ACCEPTED')
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertEqual((c.flour_sacks_used, c.sac_value_fc_used, c.notes), (Dc('3.75'), 150000, 'corrige'))
        self.assertEqual(c.theoretical_yield, 562500)           # 3,75 x 150 000
        self.assertEqual(c.total_fc_produced, 30000)
        self.assertEqual(c.yield_gap, 30000 - 562500)           # manquant (negatif)
        self.assertEqual(c.total_breads, 100)

    def test_ouverte_totaux_du_poste_ignores_a_la_mise_a_jour(self):
        s = self._open()
        push(self.a1, LBL_S, dict(s, flour_sacks_used='1.00', total_breads=9999, total_fc_produced=1,
                                  theoretical_yield=7, yield_gap=7))
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertEqual((c.total_breads, c.total_fc_produced, c.theoretical_yield), (100, 30000, 200000))
        self.assertEqual(c.yield_gap, 30000 - 200000)

    def test_ouverte_rejeu_meme_valeur_idempotent(self):
        s = self._open()
        for _ in range(3):
            push(self.a1, LBL_S, dict(s, flour_sacks_used='4.00'))
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertEqual((c.flour_sacks_used, c.theoretical_yield), (Dc('4.00'), 800000))
        self.assertEqual(ProductionSession.objects.filter(pk=s['id']).count(), 1)

    def test_close_jamais_modifiee_ni_rouverte(self):
        s = self._open()
        push(self.a1, LBL_S, dict(s, is_closed=True, closed_at=timezone.now().isoformat()))
        before = ProductionSession.objects.get(pk=s['id'])
        keep = (before.flour_sacks_used, before.sac_value_fc_used, before.notes, before.theoretical_yield,
                before.yield_gap, before.total_breads)
        push(self.a1, LBL_S, dict(s, flour_sacks_used='9.00', sac_value_fc_used=1, notes='x', is_closed=False))
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertTrue(c.is_closed)
        self.assertEqual((c.flour_sacks_used, c.sac_value_fc_used, c.notes, c.theoretical_yield, c.yield_gap,
                          c.total_breads), keep)
        # ligne : refusee sur close
        self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 5})[0],
                         'REJECTED')

    def test_cloture_et_modification_dans_le_meme_envoi(self):
        s = self._open()
        push(self.a1, LBL_S, dict(s, flour_sacks_used='3.00', is_closed=True, closed_at=timezone.now().isoformat()))
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertTrue(c.is_closed)
        self.assertEqual((c.flour_sacks_used, c.theoretical_yield), (Dc('3.00'), 600000))

    def test_bornes_farine_sur_fournee_existante(self):
        s = self._open()
        for val, exp in (('100000', 'ACCEPTED'), ('100000.01', 'REJECTED'), ('-0.01', 'REJECTED'),
                         ('2.001', 'REJECTED'), ('٣', 'REJECTED'), ('abc', 'REJECTED'), ('1e2', 'ACCEPTED'),
                         ('NaN', 'REJECTED'), ('Infinity', 'REJECTED'), (True, 'REJECTED'), ('0', 'ACCEPTED'),
                         ('0.25', 'ACCEPTED')):
            st = push(self.a1, LBL_S, dict(s, flour_sacks_used=val))
            self.assertEqual(st[0], exp, (val, st))
        self.assertEqual(ProductionSession.objects.get(pk=s['id']).flour_sacks_used, Dc('0.25'))

    def test_rejet_ne_modifie_rien(self):
        s = self._open()
        push(self.a1, LBL_S, dict(s, flour_sacks_used='5.00'))
        self.assertEqual(push(self.a1, LBL_S, dict(s, flour_sacks_used='6.00', sac_value_fc_used=-5))[0], 'REJECTED')
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertEqual((c.flour_sacks_used, c.sac_value_fc_used), (Dc('5.00'), 200000))

    def test_bornes_valeur_sac_sur_fournee_existante(self):
        s = self._open()
        for val, exp in ((100_000_000, 'ACCEPTED'), (100_000_001, 'REJECTED'), (-1, 'REJECTED'),
                         ('1e3', 'REJECTED'), ('٣', 'REJECTED'), (1.5, 'REJECTED'), (True, 'REJECTED'),
                         ('abc', 'REJECTED'), ('150000', 'ACCEPTED')):
            st = push(self.a1, LBL_S, dict(s, sac_value_fc_used=val))
            self.assertEqual(st[0], exp, (val, st))
        self.assertEqual(ProductionSession.objects.get(pk=s['id']).sac_value_fc_used, 150000)

    def test_BUG_952_valeur_sac_decimale_en_chaine_ou_flottant_entier(self):
        """BUG-956 : `sac_value_fc_used` = '150000.0' (chaine) ou 150000.0 (flottant JSON entier) passe les
        controles (valeur entiere) mais `int(raw_sac)` (fournee ouverte) leve ValueError sur la chaine, et a la
        creation la chaine fait echouer l'enregistrement : motif generique « erreur serveur » ; le flottant
        150000.0 doit etre accepte comme 150000. Attendu : '150000.0' et 150000.0 acceptes, valeur 150000."""
        s = self._open()
        for val in ('150000.0', 150000.0):
            st = push(self.a1, LBL_S, dict(s, sac_value_fc_used=val))
            self.assertEqual(st[0], 'ACCEPTED', (val, st))
            self.assertEqual(ProductionSession.objects.get(pk=s['id']).sac_value_fc_used, 150000)
        new = self.sess(sac_value_fc_used='120000.0')
        st = push(self.a1, LBL_S, new)
        self.assertEqual(st[0], 'ACCEPTED', st)

    def test_autre_noeud_ne_modifie_pas_la_fournee(self):
        s = self._open()
        for api in (self.a2, self.a3):
            st = push(api, LBL_S, dict(s, flour_sacks_used='9.00', sac_value_fc_used=1, notes='pirate'))
            self.assertEqual(st[0], 'REJECTED')
            st = push(api, LBL_S, {'id': s['id'], 'flour_sacks_used': '9.00'})
            self.assertEqual(st[0], 'REJECTED')
            st = push(api, LBL_S, {'id': s['id'], 'node': self.k2.code, 'flour_sacks_used': '9.00'})
            self.assertEqual(st[0], 'REJECTED')
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertEqual((c.flour_sacks_used, c.sac_value_fc_used, c.notes), (Dc('2.00'), 200000, ''))

    def test_node_origin_forge_refuse(self):
        s = self._open()
        self.assertEqual(push(self.a1, LBL_S, dict(s, node_origin=self.k2.code, flour_sacks_used='8.00'))[0],
                         'REJECTED')
        self.assertEqual(ProductionSession.objects.get(pk=s['id']).flour_sacks_used, Dc('2.00'))

    def test_rejeu_perime_ecrase_la_fournee_ouverte_comportement_documente(self):
        """Choix d25/d28 a valider : dernier ecrivain gagnant sur une fournee ouverte. Un lot ANCIEN rejoue avec
        un NOUVEAU batch_id (build_outbound recalcule l'etat courant : ne se produit pas dans le cycle normal)
        ramene la farine a l'ancienne valeur. Meme batch_id : idempotence du lot, aucun effet. Note, pas ticket."""
        s = self._open()
        old = {'batch_id': uid(), 'records': {LBL_S: [dict(s, flour_sacks_used='2.00')]}}
        new = {'batch_id': uid(), 'records': {LBL_S: [dict(s, flour_sacks_used='5.00')]}}
        self.post(self.a1, old)
        self.post(self.a1, new)
        self.post(self.a1, old)        # meme batch_id : renvoie le resultat enregistre
        self.assertEqual(ProductionSession.objects.get(pk=s['id']).flour_sacks_used, Dc('5.00'))
        self.post(self.a1, dict(old, batch_id=uid()))   # perime avec nouvel id : ecrase (dernier ecrivain)
        self.assertEqual(ProductionSession.objects.get(pk=s['id']).flour_sacks_used, Dc('2.00'))

    def test_BUG_953_valeur_sac_zero_conservee_a_la_creation(self):
        """BUG-957 : `sac_value_fc_used=0` a la creation devient 200000 (`record.get(...) or 200000`) alors que la
        mise a jour d'une fournee ouverte accepte 0 : valeur theorique differente selon le chemin. Attendu :
        meme regle (0 conserve, ou 0 refuse aux deux endroits)."""
        a = self.sess(sac_value_fc_used=0)
        push(self.a1, LBL_S, a)
        b = self._open()
        push(self.a1, LBL_S, dict(b, sac_value_fc_used=0))
        ca = ProductionSession.objects.get(pk=a['id']).sac_value_fc_used
        cb = ProductionSession.objects.get(pk=b['id']).sac_value_fc_used
        self.assertEqual(ca, cb)

    def test_ligne_ouverte_maj_quantite_et_catalogue_categorie_ajoutee_apres(self):
        """Ajout d'une categorie (pain 200) : accepte par la fournee, historique des lignes intact."""
        s = self._open()
        push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b4.pk, 'quantity': 50})
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertEqual((c.total_breads, c.total_fc_produced), (150, 100 * 300 + 50 * 200))
        self.assertEqual(ProductionSessionLine.objects.get(session_id=s['id'], bread_price=self.b3).quantity, 100)


# --------------------------------------------------------------------------- bout en bout 3 postes
class V11ThreePostCycle(V11Base):
    def _poste(self, node, team, flour, sac, inv_lines, sess_lines):
        d = timezone.localdate() - timedelta(days=3)
        invs = []
        for lines in inv_lines:
            total = sum(q * bp.unit_price for _, bp, q in lines)
            inv = Invoice.objects.create(node=node, team=team, status='PENDING', payment_type='CASH',
                                         order_total=Dc(total), payment_amount=Dc(total),
                                         node_origin=node.code)
            for id_, bp, q in lines:
                InvoiceLine.objects.create(id=id_, invoice=inv, bread_price=bp, quantity=q)
            invs.append(inv)
        s = ProductionSession.objects.create(node=node, team=team, date=d, flour_sacks_used=Dc(flour),
                                             sac_value_fc_used=sac, node_origin=node.code)
        for id_, bp, q, src in sess_lines:
            ProductionSessionLine.objects.create(id=id_, session=s, bread_price=bp, quantity=q, source=src)
        return invs, s

    def _export_wipe(self, code):
        payload = build_outbound_payload(code)
        Invoice.objects.filter(node_origin=code).delete()
        ProductionSession.objects.filter(node_origin=code).delete()
        BreadTransfer.objects.filter(node_origin=code).delete()
        ConsumableInventory.objects.filter(node_origin=code).delete()
        ConsumableCount.objects.filter(node__code=code).delete()
        return payload

    def _build_three(self):
        D, C = 'DECLARED', 'CARRYOVER'
        b3, b5, b4 = self.b3, self.b5, self.b4
        out = {}
        self._poste(self.k1, 'A', '2.00', 150000,
                    [[(1, b3, 3), (2, b5, 5)], [(3, b4, 10)]], [(1, b3, 70, D), (2, b3, 20, C), (3, b5, 10, D)])
        # transferts + comptages du poste K1
        t = BreadTransfer.objects.create(from_node=self.k1, to_node=self.k2, node_origin=self.k1.code)
        BreadTransferLine.objects.create(id=1, transfer=t, bread_price=b3, quantity_sent=40)
        BreadTransferLine.objects.create(id=2, transfer=t, bread_price=b5, quantity_sent=10)
        out['t1'] = t
        out['p1'] = self._export_wipe(self.k1.code)

        self._poste(self.k2, 'B', '1.00', 200000,
                    [[(1, b3, 4), (2, b5, 6), (3, b4, 8)]], [(1, b3, 33, D), (2, b4, 5, D)])
        t2 = BreadTransfer.objects.create(from_node=self.k2, to_node=self.k3, node_origin=self.k2.code)
        BreadTransferLine.objects.create(id=1, transfer=t2, bread_price=b3, quantity_sent=15)
        out['t2'] = t2
        out['p2'] = self._export_wipe(self.k2.code)

        self._poste(self.k3, 'A', '3.00', 200000,
                    [[(1, b3, 7), (2, b5, 9), (3, b4, 2)], [(4, b5, 1)]], [(1, b5, 12, D), (2, b3, 1, D)])
        inv = ConsumableInventory.objects.create(node=self.k3, inventory_date=timezone.localdate() - timedelta(days=1),
                                                 node_origin=self.k3.code)
        for ct, sysq, phy in (('SEL', '1000', '990'), ('YEAST', '2.25', '2.00')):
            ConsumableCount.objects.create(node=self.k3, consumable_type=ct, count_date=inv.inventory_date,
                                           system_quantity=Dc(sysq), physical_quantity=Dc(phy),
                                           gap=Dc(phy) - Dc(sysq), inventory=inv)
        out['inv'] = inv
        out['p3'] = self._export_wipe(self.k3.code)
        return out

    def test_trois_postes_cycle_complet_et_coherence_cloud(self):
        stock_before = {(s.node_id, s.bread_price_id): s.qty_available for s in BreadStock.objects.all()}
        out = self._build_three()
        self.assertEqual(Invoice.objects.count(), 0)
        ids_t = (out['t1'].pk, out['t2'].pk)
        self.assertEqual({l['id'] for l in out['p1']['records']['sales.InvoiceLine']}, {'1', '2', '3'})
        order = [(self.a2, out['p2']), (self.a3, out['p3']), (self.a1, out['p1'])]
        responses = []
        for api, payload in order:
            data = self.post(api, payload)
            for label, rows in data['results'].items():
                for r in rows:
                    self.assertEqual(r['status'], 'ACCEPTED', (label, r))
            responses.append(data)
            apply_push_response(data)

        # lignes de facture : une seule par (facture, categorie) hors K3 facture 1 (3 categories distinctes)
        for inv in Invoice.objects.all():
            lines = InvoiceLine.objects.filter(invoice=inv)
            cats = [l.bread_price_id for l in lines]
            self.assertEqual(len(cats), len(set(cats)), inv.pk)
            self.assertEqual(sum(l.line_total for l in lines), inv.order_total, (inv.node.code, inv.pk))
            self.assertEqual(sum(l.line_total for l in lines), sum(l.quantity * l.unit_price for l in lines))
        self.assertEqual(InvoiceLine.objects.count(), 2 + 1 + 3 + 3 + 1)
        # fournees : totaux = lignes
        sK1 = ProductionSession.objects.get(node=self.k1)
        self.assertEqual((sK1.total_breads, sK1.total_fc_produced, sK1.theoretical_yield),
                         (100, 70 * 300 + 10 * 500, 300000))
        self.assertEqual(sK1.yield_gap, 26000 - 300000)
        sK2 = ProductionSession.objects.get(node=self.k2)
        self.assertEqual((sK2.total_breads, sK2.total_fc_produced), (38, 33 * 300 + 5 * 200))
        sK3 = ProductionSession.objects.get(node=self.k3)
        self.assertEqual((sK3.total_breads, sK3.total_fc_produced, sK3.theoretical_yield),
                         (13, 12 * 500 + 300, 600000))
        # transferts : lignes avec quantites propres
        got = {(l.transfer_id, l.bread_price_id): l.quantity_sent for l in BreadTransferLine.objects.all()}
        self.assertEqual(got, {(ids_t[0], self.b3.pk): 40, (ids_t[0], self.b5.pk): 10, (ids_t[1], self.b3.pk): 15})
        # comptages
        inv = ConsumableInventory.objects.get(node=self.k3)
        self.assertEqual({c.consumable_type: c.gap for c in inv.lines.all()}, {'SEL': Dc('-10'), 'YEAST': Dc('-0.25')})
        # stock de pains : le push ne rejoue jamais l'effet de stock
        stock_after = {(s.node_id, s.bread_price_id): s.qty_available for s in BreadStock.objects.all()}
        self.assertEqual(stock_before, stock_after)
        # plus rien a envoyer pour aucun poste (hors ConsumableCount sans is_synced, remontent avec l'inventaire)
        # les enregistrements locaux ont ete effaces : la reconstruction depuis le cloud n'est pas le sujet.

        # pull : 200 pour chaque poste, application sans exception
        for api, code in ((self.a1, 'Q1'), (self.a2, 'Q2'), (self.a3, 'Q3')):
            r = api.get('/api/sync/pull/')
            self.assertEqual(r.status_code, 200, r.content)
            apply_pull_response(r.data)

        # second cycle : le poste K1 a corrige farine/valeur du sac et une quantite de ligne, avec rejeu des ids locaux
        p1 = out['p1']
        s_rec = p1['records']['production.ProductionSession'][0]
        s_rec = dict(s_rec, flour_sacks_used='3.50', sac_value_fc_used=100000)
        lines = [dict(l, quantity=80) if l['source'] == 'DECLARED' and l['bread_price'] == self.b3.pk else l
                 for l in p1['records']['production.ProductionSessionLine']]
        p1b = {'batch_id': uid(), 'node_code': 'Q1', 'records': {
            'production.ProductionSession': [s_rec], 'production.ProductionSessionLine': lines,
            'sales.Invoice': p1['records']['sales.Invoice'], 'sales.InvoiceLine': p1['records']['sales.InvoiceLine']}}
        n_lines = InvoiceLine.objects.count()
        data = self.post(self.a1, p1b)
        for label, rows in data['results'].items():
            for r in rows:
                self.assertEqual(r['status'], 'ACCEPTED', (label, r))
        self.assertEqual(InvoiceLine.objects.count(), n_lines)
        sK1 = ProductionSession.objects.get(node=self.k1)
        self.assertEqual((sK1.flour_sacks_used, sK1.sac_value_fc_used, sK1.theoretical_yield),
                         (Dc('3.50'), 100000, 350000))
        self.assertEqual((sK1.total_breads, sK1.total_fc_produced), (110, 80 * 300 + 10 * 500))
        self.assertEqual(sK1.yield_gap, sK1.total_fc_produced - 350000)

    def test_trois_postes_chaque_ordre_d_arrivee(self):
        out = self._build_three()
        payloads = {'p1': (self.a1, out['p1']), 'p2': (self.a2, out['p2']), 'p3': (self.a3, out['p3'])}
        expected = None
        for perm in itertools.permutations(payloads):
            Invoice.objects.all().delete()
            ProductionSession.objects.all().delete()
            BreadTransfer.objects.all().delete()
            ConsumableInventory.objects.all().delete()
            for key in perm:
                api, payload = payloads[key]
                data = self.post(api, dict(payload, batch_id=uid()))
                for label, rows in data['results'].items():
                    for r in rows:
                        self.assertEqual(r['status'], 'ACCEPTED', (perm, label, r))
            snap = sorted((l.invoice.node.code, l.bread_price_id, l.quantity) for l in InvoiceLine.objects.all())
            snap2 = sorted((s.node.code, s.total_breads, s.total_fc_produced) for s in ProductionSession.objects.all())
            if expected is None:
                expected = (snap, snap2)
            self.assertEqual((snap, snap2), expected, perm)

    def test_BUG_954_transfert_envoi_direct_termine_hors_ligne_est_synchronisable(self):
        """BUG-958. Un transfert cree puis avance (envoi direct : statut deja RESPONDED, ou confirme) avant la premiere
        synchronisation : le poste n'exporte que son etat courant. La creation cloud n'accepte que PENDING."""
        from production.tests.test_verif_a4_testeur_production import T, cl
        r = cl(self.g1).post(f'{T}send/', {'to_node': self.k2.pk, 'lines': [
            {'bread_price': self.b3.pk, 'quantity_sent': 30}]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        t = BreadTransfer.objects.get(pk=r.data['id'])
        payload = build_outbound_payload(self.k1.code)
        rec = [x for x in payload['records']['production.BreadTransfer'] if x['id'] == str(t.pk)]
        self.assertEqual(len(rec), 1, payload['records']['production.BreadTransfer'])
        status_local = rec[0]['transfer_status']
        BreadTransfer.objects.filter(pk=t.pk).delete()
        data = self.post(self.a1, payload)
        res_t = [x for x in data['results'].get('production.BreadTransfer', []) if x['id'] == str(t.pk)]
        self.assertEqual(res_t[0]['status'], 'ACCEPTED', (status_local, res_t))
        self.assertTrue(BreadTransfer.objects.filter(pk=t.pk).exists())
