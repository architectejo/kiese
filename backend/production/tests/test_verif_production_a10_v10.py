"""Testeur-production (cycle 11 / a10) : verification independante de BUG-919 a 928 (contrat d'id
des lignes poussees, cles naturelles, bornes) + cycle sync_now complet sur 2 postes simules.
Donnees fictives. Les `@expectedFailure` referencent leur ticket.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.utils import timezone

from production.models import (BreadDisposal, BreadTransfer, BreadTransferLine, ConsumableStock,
                               ProductionSession, ProductionSessionLine)
from production.tests.test_verif_production_a8_v8 import PUSH, PushBase, api_for, push, uid
from production.tests.test_verif_production_a9_v9 import (LBL_D, LBL_I, LBL_IL, LBL_L, LBL_M, LBL_S,
                                                          LBL_T, LBL_TL, lot)
from sales.models import Invoice, InvoiceLine
from sync.management.commands.sync_now import apply_push_response, build_outbound_payload


def ok(res):
    return all(x[0] == 'ACCEPTED' for v in res.values() for x in v)


class A10Base(PushBase):
    def two_invoices(self):
        i1, i2 = self.inv(), self.inv(node=self.k2.code)
        push(self.a1, LBL_I, i1)
        push(self.a2, LBL_I, i2)
        return i1, i2

    def il(self, inv, bp, q, id_=None):
        r = {'invoice': inv['id'], 'bread_price': bp.pk, 'quantity': q}
        if id_ is not None:
            r['id'] = str(id_)
        return r


# --------------------------------------------------------------------------- BUG-919 : InvoiceLine
class A10InvoiceLineIds(A10Base):
    def test_BUG_919_collision_k1_k2_ligne_7(self):
        i1, i2 = self.two_invoices()
        self.assertEqual(push(self.a1, LBL_IL, self.il(i1, self.b3, 3, 7))[0], 'ACCEPTED')
        self.assertEqual(push(self.a2, LBL_IL, self.il(i2, self.b3, 4, 7))[0], 'ACCEPTED')
        l1 = InvoiceLine.objects.get(invoice_id=i1['id'])
        l2 = InvoiceLine.objects.get(invoice_id=i2['id'])
        self.assertEqual((l1.pk, l1.quantity, l2.quantity), (7, 3, 4))
        self.assertNotEqual(l1.pk, l2.pk)

    def test_BUG_919_rejeu_idempotent_apres_collision(self):
        i1, i2 = self.two_invoices()
        for _ in range(3):
            push(self.a1, LBL_IL, self.il(i1, self.b3, 3, 7))
            push(self.a2, LBL_IL, self.il(i2, self.b3, 4, 7))
        self.assertEqual(InvoiceLine.objects.filter(invoice_id=i1['id']).count(), 1)
        self.assertEqual(InvoiceLine.objects.filter(invoice_id=i2['id']).count(), 1)
        self.assertEqual(InvoiceLine.objects.count(), 2)

    def test_BUG_919_ligne_deja_synchronisee_id_legacy_sans_doublon(self):
        i1, _ = self.two_invoices()
        InvoiceLine.objects.create(id=50, invoice_id=i1['id'], bread_price=self.b3, quantity=3)
        self.assertEqual(push(self.a1, LBL_IL, self.il(i1, self.b3, 3, 50))[0], 'ACCEPTED')
        self.assertEqual(InvoiceLine.objects.filter(invoice_id=i1['id']).count(), 1)

    def test_BUG_919_id_absent_ou_non_numerique(self):
        i1, _ = self.two_invoices()
        self.assertEqual(push(self.a1, LBL_IL, self.il(i1, self.b3, 3))[0], 'ACCEPTED')
        for bad in ('abc', '٧', '-3', '7.0'):
            st = push(self.a1, LBL_IL, self.il(i1, self.b5, 2, bad))[0]
            self.assertIn(st, ('ACCEPTED', 'REJECTED'), bad)  # jamais 500

    @expectedFailure
    def test_BUG_940_id_non_numerique_rejoue_ne_duplique_pas_la_ligne(self):
        i1, _ = self.two_invoices()
        for bad in ('abc', '7.0', '-3', None):
            for _ in range(2):
                push(self.a1, LBL_IL, self.il(i1, self.b5, 2, bad))
            n = InvoiceLine.objects.filter(invoice_id=i1['id'], bread_price=self.b5).count()
            InvoiceLine.objects.filter(invoice_id=i1['id']).delete()
            self.assertLessEqual(n, 1, bad)

    def test_BUG_919_ligne_poussee_par_k2_sur_facture_k1_refusee_meme_si_id_libre(self):
        i1, _ = self.two_invoices()
        self.assertEqual(push(self.a2, LBL_IL, self.il(i1, self.b3, 3, 900))[0], 'REJECTED')
        self.assertEqual(InvoiceLine.objects.count(), 0)

    def test_BUG_919_id_designe_ligne_autre_facture_autre_poste_pas_modifiee(self):
        """K2 envoie id=7 (celui de K1) pour une facture inexistante : ne modifie pas la ligne de K1."""
        i1, i2 = self.two_invoices()
        push(self.a1, LBL_IL, self.il(i1, self.b3, 3, 7))
        ghost = {'invoice': uid(), 'bread_price': self.b3.pk, 'quantity': 99, 'id': '7'}
        push(self.a2, LBL_IL, ghost)
        self.assertEqual(InvoiceLine.objects.get(pk=7).quantity, 3)
        # sans champ invoice : ancien payload, ligne de K1 -> refus (autre boulangerie)
        st = push(self.a2, LBL_IL, {'bread_price': self.b3.pk, 'quantity': 99, 'id': '7'})[0]
        self.assertEqual(st, 'REJECTED')
        self.assertEqual(InvoiceLine.objects.get(pk=7).quantity, 3)

    @expectedFailure
    def test_BUG_938_deux_categories_meme_facture_collision_id_ne_se_melangent_pas(self):
        """K1 a la ligne 7 (facture A). K2 pousse, pour sa facture B, la ligne locale 7 (pain 3) puis la ligne
        locale 8 (pain 5). La ligne 7 de K2 recoit la PK cloud auto (8) ; la ligne locale 8 est alors prise
        pour la ligne cloud 8 (meme facture) : sa quantite ECRASE celle du pain 3 et la ligne pain 5 n'est
        jamais creee, le tout ACCEPTED (BUG-938)."""
        i1, i2 = self.two_invoices()
        push(self.a1, LBL_IL, self.il(i1, self.b3, 3, 7))
        res = lot(self.a2, sales__InvoiceLine=[self.il(i2, self.b3, 4, 7), self.il(i2, self.b5, 5, 8)])
        self.assertTrue(ok(res), res)
        got = {l.bread_price_id: l.quantity for l in InvoiceLine.objects.filter(invoice_id=i2['id'])}
        self.assertEqual(got, {self.b3.pk: 4, self.b5.pk: 5})

    def test_limite_connue_deux_lignes_meme_categorie_et_collision_documentee(self):
        """Limite signalee par le dev (rapport d28) : non ticketee, on verifie seulement l'absence de 500."""
        i1, i2 = self.two_invoices()
        push(self.a1, LBL_IL, self.il(i1, self.b3, 3, 7))
        res = lot(self.a2, sales__InvoiceLine=[self.il(i2, self.b3, 4, 7), self.il(i2, self.b3, 6, 8)])
        self.assertTrue(ok(res), res)
        self.assertGreaterEqual(InvoiceLine.objects.filter(invoice_id=i2['id']).count(), 1)


# --------------------------------------------------------------------------- BUG-919/920/924 : fournees
class A10SessionLines(A10Base):
    def test_collision_ligne_5_k1_k2(self):
        s1, s2 = self.sess(), self.sess(node=self.k2.code)
        push(self.a1, LBL_S, s1)
        push(self.a2, LBL_S, s2)
        for _ in range(2):
            push(self.a1, LBL_L, {'id': '5', 'session': s1['id'], 'bread_price': self.b3.pk, 'quantity': 11})
            push(self.a2, LBL_L, {'id': '5', 'session': s2['id'], 'bread_price': self.b3.pk, 'quantity': 22})
        self.assertEqual(ProductionSessionLine.objects.get(session_id=s1['id']).quantity, 11)
        self.assertEqual(ProductionSessionLine.objects.get(session_id=s2['id']).quantity, 22)

    def test_carryover_et_declared_coexistent_sans_ecrasement(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        lot(self.a1, production__ProductionSessionLine=[
            {'id': '1', 'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 70, 'source': 'DECLARED'},
            {'id': '2', 'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 20, 'source': 'CARRYOVER'}])
        got = {l.source: l.quantity for l in ProductionSessionLine.objects.filter(session_id=s['id'])}
        self.assertEqual(got, {'DECLARED': 70, 'CARRYOVER': 20})
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertEqual(c.total_breads, 90)
        self.assertEqual(c.total_fc_produced, 70 * self.b3.unit_price)  # CARRYOVER exclu du rendement

    def test_source_invalide_refusee_source_absente_vaut_declared(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 5,
                                               'source': 'FOO'})[0], 'REJECTED')
        self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 5,
                                               'source': ''})[0], 'ACCEPTED')
        self.assertEqual(ProductionSessionLine.objects.get(session_id=s['id']).source, 'DECLARED')

    def test_poste_non_mis_a_jour_sans_source_ecrase_declared_pas_carryover(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        lot(self.a1, production__ProductionSessionLine=[
            {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 70},
            {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 20, 'source': 'CARRYOVER'}])
        push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 75})
        got = {l.source: l.quantity for l in ProductionSessionLine.objects.filter(session_id=s['id'])}
        self.assertEqual(got, {'DECLARED': 75, 'CARRYOVER': 20})

    def test_maj_ligne_fournee_ouverte_et_totaux_recalcules(self):
        s = self.sess(flour_sacks_used='2.00', sac_value_fc_used=150000)
        push(self.a1, LBL_S, s)
        push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 10})
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertEqual(c.total_fc_produced, 10 * self.b3.unit_price)
        self.assertEqual(c.theoretical_yield, 300000)
        self.assertEqual(c.yield_gap, c.total_fc_produced - 300000)
        self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 40})[0],
                         'ACCEPTED')
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertEqual(c.total_fc_produced, 40 * self.b3.unit_price)
        self.assertEqual(c.yield_gap, c.total_fc_produced - 300000)
        self.assertEqual(c.total_breads, 40)

    def test_maj_ligne_fournee_close_refusee_rejeu_meme_valeur_accepte(self):
        s = self.sess()
        lot(self.a1, production__ProductionSession=[dict(s, is_closed=True, closed_at=timezone.now().isoformat())],
            production__ProductionSessionLine=[{'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 10}])
        self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 10})[0],
                         'ACCEPTED')
        self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 11})[0],
                         'REJECTED')
        self.assertEqual(ProductionSessionLine.objects.get(session_id=s['id']).quantity, 10)

    def test_totaux_recopies_du_poste_ignores(self):
        s = self.sess(total_breads=9999, total_fc_produced=9_999_999, theoretical_yield=1, yield_gap=5,
                      breads_300=7)
        push(self.a1, LBL_S, s)
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertEqual((c.total_breads, c.total_fc_produced, c.breads_300), (0, 0, 0))
        self.assertEqual(c.theoretical_yield, 2 * 200000)
        self.assertEqual(c.yield_gap, -400000)

    def test_sac_value_bornes(self):
        self.assertEqual(self.push_sess(sac_value_fc_used=100_000_000)[1][0], 'ACCEPTED')
        self.assertEqual(self.push_sess(sac_value_fc_used=100_000_001)[1][0], 'REJECTED')
        self.assertEqual(self.push_sess(sac_value_fc_used=-1)[1][0], 'REJECTED')
        self.assertEqual(self.push_sess(sac_value_fc_used='1e3')[1][0], 'REJECTED')

    def test_session_sans_ligne_zero_fc(self):
        rec, _ = self.push_sess()
        c = ProductionSession.objects.get(pk=rec['id'])
        self.assertEqual((c.total_fc_produced, c.total_breads), (0, 0))

    def test_ligne_quantite_zero_et_negatifs(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b3.pk, 'quantity': 0})[0],
                         'ACCEPTED')
        for q in (-1, None, '١'):
            self.assertEqual(push(self.a1, LBL_L, {'session': s['id'], 'bread_price': self.b5.pk, 'quantity': q})[0],
                             'REJECTED', q)

    @expectedFailure
    def test_BUG_939_flour_sacks_used_modifie_localement_propage_au_cloud(self):
        """Une fournee ouverte deja synchronisee voit sa farine corrigee/augmentee sur le poste (declaration
        additionnelle du jour) : le cloud garde l'ancienne valeur (seule la cloture est appliquee) alors que
        les lignes, elles, sont mises a jour (BUG-920) : le rendement theorique cloud est faux."""
        s = self.sess(flour_sacks_used='2.00')
        push(self.a1, LBL_S, s)
        res = push(self.a1, LBL_S, dict(s, flour_sacks_used='5.00'))
        c = ProductionSession.objects.get(pk=s['id'])
        self.assertTrue(res[0] == 'REJECTED' or c.flour_sacks_used == Dc('5.00'),
                        (res, c.flour_sacks_used))


# --------------------------------------------------------------------------- BUG-921/922/928 : transferts
class A10Transfers(A10Base):
    def mk(self, **kw):
        t = dict({'id': uid(), 'from_node': self.k1.code, 'to_node': self.k2.code}, **kw)
        self.assertEqual(push(self.a1, LBL_T, t)[0], 'ACCEPTED')
        return t

    def tl(self, t, bp, sent=None, recv=None):
        r = {'transfer': t['id'], 'bread_price': bp.pk}
        if sent is not None:
            r['quantity_sent'] = sent
        if recv is not None:
            r['quantity_received'] = recv
        return r

    def test_collision_ligne_7_k1_k2(self):
        t1 = self.mk()
        t2 = {'id': uid(), 'from_node': self.k2.code, 'to_node': self.k1.code}
        push(self.a2, LBL_T, t2)
        for _ in range(2):
            self.assertEqual(push(self.a1, LBL_TL, dict(self.tl(t1, self.b3, 100), id='7'))[0], 'ACCEPTED')
            self.assertEqual(push(self.a2, LBL_TL, dict(self.tl(t2, self.b3, 40), id='7'))[0], 'ACCEPTED')
        self.assertEqual(BreadTransferLine.objects.get(transfer_id=t1['id']).quantity_sent, 100)
        self.assertEqual(BreadTransferLine.objects.get(transfer_id=t2['id']).quantity_sent, 40)

    def test_k1_vers_k1_refuse_dans_tous_les_cas(self):
        for to in (self.k1.code, self.k1.code.lower()):
            t = {'id': uid(), 'from_node': self.k1.code, 'to_node': to}
            self.assertEqual(push(self.a1, LBL_T, t)[0], 'REJECTED', to)
        # K2 ne peut pas creer K1 -> K1
        self.assertEqual(push(self.a2, LBL_T, {'id': uid(), 'from_node': self.k1.code,
                                               'to_node': self.k1.code})[0], 'REJECTED')
        self.assertEqual(BreadTransfer.objects.count(), 0)

    def test_ligne_sur_transfert_confirme_refusee_et_recue_figee(self):
        t = self.mk()
        push(self.a1, LBL_TL, self.tl(t, self.b3, 100))
        # premier remplissage par la receptrice : permis
        self.assertEqual(push(self.a2, LBL_TL, self.tl(t, self.b3, recv=98))[0], 'ACCEPTED')
        BreadTransfer.objects.filter(pk=t['id']).update(transfer_status='CONFIRMED')
        self.assertEqual(push(self.a1, LBL_TL, self.tl(t, self.b5, 10))[0], 'REJECTED')
        self.assertEqual(push(self.a2, LBL_TL, self.tl(t, self.b5, 10))[0], 'REJECTED')
        # reecriture refusee, meme valeur acceptee (rejeu)
        self.assertEqual(push(self.a2, LBL_TL, self.tl(t, self.b3, recv=50))[0], 'REJECTED')
        self.assertEqual(push(self.a2, LBL_TL, self.tl(t, self.b3, recv=98))[0], 'ACCEPTED')
        self.assertEqual(push(self.a2, LBL_TL, self.tl(t, self.b3, recv='98'))[0], 'ACCEPTED')
        self.assertEqual(BreadTransferLine.objects.get(transfer_id=t['id']).quantity_received, 98)
        self.assertEqual(BreadTransferLine.objects.filter(transfer_id=t['id']).count(), 1)

    def test_recue_zero_figee_aussi(self):
        t = self.mk()
        push(self.a1, LBL_TL, self.tl(t, self.b3, 100))
        push(self.a2, LBL_TL, self.tl(t, self.b3, recv=0))
        BreadTransfer.objects.filter(pk=t['id']).update(transfer_status='CONFIRMED')
        self.assertEqual(push(self.a2, LBL_TL, self.tl(t, self.b3, recv=100))[0], 'REJECTED')
        self.assertEqual(BreadTransferLine.objects.get(transfer_id=t['id']).quantity_received, 0)

    def test_transfert_annule_immuable(self):
        t = self.mk()
        push(self.a1, LBL_TL, self.tl(t, self.b3, 100))
        BreadTransfer.objects.filter(pk=t['id']).update(transfer_status='CANCELLED')
        self.assertEqual(push(self.a1, LBL_TL, self.tl(t, self.b5, 1))[0], 'REJECTED')

    def test_lot_qui_confirme_peut_pousser_ses_lignes_recues(self):
        t = self.mk()
        push(self.a1, LBL_TL, self.tl(t, self.b3, 100))
        BreadTransfer.objects.filter(pk=t['id']).update(transfer_status='RESPONDED')
        res = lot(self.a2, production__BreadTransfer=[dict(t, transfer_status='CONFIRMED')],
                  production__BreadTransferLine=[self.tl(t, self.b3, recv=100)])
        self.assertTrue(ok(res), res)
        self.assertEqual(BreadTransferLine.objects.get(transfer_id=t['id']).quantity_received, 100)
        self.assertEqual(BreadTransfer.objects.get(pk=t['id']).transfer_status, 'CONFIRMED')

    def test_emettrice_ne_confirme_pas_ni_ne_renseigne_recue(self):
        t = self.mk()
        push(self.a1, LBL_TL, self.tl(t, self.b3, 100))
        BreadTransfer.objects.filter(pk=t['id']).update(transfer_status='RESPONDED')
        self.assertEqual(push(self.a1, LBL_T, dict(t, transfer_status='CONFIRMED'))[0], 'REJECTED')
        push(self.a1, LBL_TL, self.tl(t, self.b3, 100, recv=100))
        self.assertIsNone(BreadTransferLine.objects.get(transfer_id=t['id']).quantity_received)

    def test_emettrice_autre_quantite_envoyee_rejetee_receptrice_ignoree(self):
        t = self.mk()
        push(self.a1, LBL_TL, self.tl(t, self.b3, 100))
        self.assertEqual(push(self.a1, LBL_TL, self.tl(t, self.b3, 55))[0], 'REJECTED')
        self.assertEqual(push(self.a1, LBL_TL, self.tl(t, self.b3, 100))[0], 'ACCEPTED')
        push(self.a2, LBL_TL, self.tl(t, self.b3, 7))
        self.assertEqual(BreadTransferLine.objects.get(transfer_id=t['id']).quantity_sent, 100)

    def test_bornes_quantites(self):
        t = self.mk()
        for q, exp in ((2_000_000_000, 'ACCEPTED'), (2_000_000_001, 'REJECTED'), (-1, 'REJECTED'),
                       ('2e9', 'REJECTED'), ('٣', 'REJECTED'), (True, 'REJECTED')):
            self.assertEqual(push(self.a1, LBL_TL, self.tl(t, self.b4 if hasattr(self, 'b4') else self.b5, q))[0],
                             exp, q)

    def test_transfert_multilignes_et_quantites_distinctes(self):
        t = self.mk()
        res = lot(self.a1, production__BreadTransferLine=[self.tl(t, self.b3, 100), self.tl(t, self.b5, 40)])
        self.assertTrue(ok(res), res)
        got = {l.bread_price_id: l.quantity_sent for l in BreadTransferLine.objects.filter(transfer_id=t['id'])}
        self.assertEqual(got, {self.b3.pk: 100, self.b5.pk: 40})


# --------------------------------------------------------------------------- BUG-925/926/927/928
class A10Bounds(A10Base):
    def disp(self, s, qty, price, dtype='SOLD_DISCOUNT', bp=None):
        return {'id': uid(), 'session': s['id'], 'bread_price': (bp or self.b3).pk, 'disposal_type': dtype,
                'quantity': qty, 'unit_price_sold': price}

    def test_dispositions_bornes(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        cases = [(1_000_000, 9999, 'ACCEPTED'), (1_000_000, 10_000, 'REJECTED'), (1_000_001, 0, 'REJECTED'),
                 (1_000_000, 0, 'ACCEPTED'), (1, 2_000_000_000, 'ACCEPTED'), (5, 2_000_000_001, 'REJECTED'),
                 (-1, 100, 'REJECTED'), (5, -1, 'REJECTED'),
                 ('٣', 100, 'REJECTED'), (1.5, 100, 'REJECTED')]
        for q, p, exp in cases:
            d = self.disp(s, q, p)
            st = push(self.a1, LBL_D, d)
            self.assertEqual(st[0], exp, (q, p, st))
            if exp == 'ACCEPTED':
                self.assertEqual(BreadDisposal.objects.get(pk=d['id']).total_value, Dc(q) * Dc(p))

    def test_disposition_remaining_negative_et_type_invalide(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        self.assertEqual(push(self.a1, LBL_D, self.disp(s, -1_000_000, 0, 'REMAINING'))[0], 'ACCEPTED')
        self.assertEqual(push(self.a1, LBL_D, self.disp(s, -1_000_001, 0, 'REMAINING'))[0], 'REJECTED')
        self.assertEqual(push(self.a1, LBL_D, self.disp(s, 1, 0, 'XXX'))[0], 'REJECTED')
        self.assertEqual(push(self.a1, LBL_D, self.disp(s, 1, 0, None))[0], 'REJECTED')

    def test_disposition_session_autre_poste_refusee(self):
        s = self.sess()
        push(self.a1, LBL_S, s)
        self.assertEqual(push(self.a2, LBL_D, self.disp(s, 1, 0))[0], 'REJECTED')

    def test_consumable_type_et_unit(self):
        base = {'node': self.k1.code, 'movement_type': 'ENTRY', 'quantity': '1'}
        for ct, exp in (('SEL', 'ACCEPTED'), ('A-b_1', 'ACCEPTED'), ('X' * 10, 'ACCEPTED'), ('X' * 11, 'REJECTED'),
                        ('SALT\n', 'REJECTED'), ('SA LT', 'REJECTED'), ('é', 'REJECTED'), ('٣', 'REJECTED'),
                        ('SALT;', 'REJECTED'), (['SALT'], 'REJECTED'), ({'a': 1}, 'REJECTED'), (7, 'REJECTED')):
            self.assertEqual(push(self.a1, LBL_M, dict(base, id=uid(), consumable_type=ct))[0], exp, ct)
        for unit, exp in (('g', 'ACCEPTED'), ('x' * 20, 'ACCEPTED'), ('x' * 21, 'REJECTED'), (5, 'REJECTED')):
            self.assertEqual(push(self.a1, LBL_M, dict(base, id=uid(), consumable_type='SALT', unit=unit))[0], exp, unit)
        self.assertFalse(ConsumableStock.objects.filter(node=self.k1, consumable_type__regex=r'[^A-Za-z0-9_-]').exists())

    def test_consumable_movement_autre_poste_et_sans_type(self):
        rec = {'id': uid(), 'node': self.k2.code, 'consumable_type': 'SALT', 'movement_type': 'ENTRY', 'quantity': '1'}
        self.assertEqual(push(self.a1, LBL_M, rec)[0], 'REJECTED')
        self.assertEqual(push(self.a1, LBL_M, dict(rec, node=self.k1.code, consumable_type=''))[0], 'REJECTED')

    def test_invoice_team(self):
        for team, exp in (('', 'ACCEPTED'), ('A', 'ACCEPTED'), ('B', 'ACCEPTED'), ('a', 'REJECTED'), (' A', 'REJECTED'),
                          ('A\n', 'REJECTED'), ('C', 'REJECTED'), ('JOUR', 'REJECTED'), ('NUIT', 'REJECTED')):
            self.assertEqual(push(self.a1, LBL_I, self.inv(team=team))[0], exp, team)
        r = push(self.a1, LBL_I, {k: v for k, v in self.inv().items() if k != 'team'})
        self.assertEqual(r[0], 'ACCEPTED')

    def test_invoice_team_liste_ou_nombre_sans_500(self):
        for team in (['A'], 1, {'x': 1}, True):
            self.assertEqual(push(self.a1, LBL_I, self.inv(team=team))[0], 'REJECTED', team)

    def test_closed_at_futur_et_limite(self):
        t = self.today() if hasattr(self, 'today') else None
        s = self.sess()
        self.assertEqual(push(self.a1, LBL_S, dict(s, is_closed=True, closed_at='2099-01-01T00:00:00Z'))[0], 'REJECTED')
        self.assertEqual(push(self.a1, LBL_S, dict(s, is_closed=True,
                                                   closed_at=(timezone.now() - timedelta(days=1)).isoformat()))[0],
                         'ACCEPTED')
        self.assertIsNone(t) if t is None else None


# --------------------------------------------------------------------------- cycle sync_now de bout en bout
class A10SyncNowCycle(A10Base):
    """Deux postes simules : chaque poste fabrique ses lignes avec des PK entieres locales identiques (7),
    `build_outbound_payload` les exporte, puis on efface la copie locale (le poste n'est pas dans la base
    cloud), on pousse, et `apply_push_response` marque ce qui a ete accepte."""

    def _poste_k1(self):
        from production.models import BreadTransfer as BT
        d = timezone.localdate() - timedelta(days=3)
        inv = Invoice.objects.create(node=self.k1, team='A', status='PENDING', payment_type='CASH',
                                     node_origin=self.k1.code)
        InvoiceLine.objects.create(id=7, invoice=inv, bread_price=self.b3, quantity=3)
        s = ProductionSession.objects.create(node=self.k1, team='A', date=d, flour_sacks_used=Dc('2.00'),
                                             sac_value_fc_used=150000, node_origin=self.k1.code)
        ProductionSessionLine.objects.create(id=7, session=s, bread_price=self.b3, quantity=70, source='DECLARED')
        ProductionSessionLine.objects.create(id=8, session=s, bread_price=self.b3, quantity=20, source='CARRYOVER')
        t = BT.objects.create(from_node=self.k1, to_node=self.k2, node_origin=self.k1.code)
        BreadTransferLine.objects.create(id=7, transfer=t, bread_price=self.b3, quantity_sent=100)
        return inv, s, t

    def _poste_k2(self):
        d = timezone.localdate() - timedelta(days=3)
        inv = Invoice.objects.create(node=self.k2, team='B', status='PENDING', payment_type='CASH',
                                     node_origin=self.k2.code)
        InvoiceLine.objects.create(id=7, invoice=inv, bread_price=self.b3, quantity=4)
        s = ProductionSession.objects.create(node=self.k2, team='B', date=d, flour_sacks_used=Dc('1.00'),
                                             sac_value_fc_used=200000, node_origin=self.k2.code)
        ProductionSessionLine.objects.create(id=7, session=s, bread_price=self.b3, quantity=33, source='DECLARED')
        t = BreadTransfer.objects.create(from_node=self.k2, to_node=self.k1, node_origin=self.k2.code)
        BreadTransferLine.objects.create(id=7, transfer=t, bread_price=self.b3, quantity_sent=40)
        return inv, s, t

    def _export_and_wipe(self, code, objs):
        payload = build_outbound_payload(code)
        pks = [o.pk for o in objs]
        for o in objs:
            o.delete()
        for o, pk in zip(objs, pks):   # delete() remet pk a None : on le restitue pour les assertions
            o.pk = pk
        return payload

    def _post(self, api, payload):
        r = api.post(PUSH, payload, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.data

    def test_cycle_complet_deux_postes_collision_ids(self):
        i1, s1, t1 = self._poste_k1()
        p1 = self._export_and_wipe(self.k1.code, (i1, s1, t1))
        i2, s2, t2 = self._poste_k2()
        p2 = self._export_and_wipe(self.k2.code, (i2, s2, t2))
        # le payload porte bien l'id entier 7 et la source
        self.assertEqual({l['id'] for l in p1['records']['production.ProductionSessionLine']}, {'7', '8'})
        self.assertEqual({l['source'] for l in p1['records']['production.ProductionSessionLine']},
                         {'DECLARED', 'CARRYOVER'})
        self.assertEqual(Invoice.objects.count() + ProductionSession.objects.count(), 0)

        d1 = self._post(self.a1, p1)
        d2 = self._post(self.a2, p2)
        for d in (d1, d2):
            for label, rows in d['results'].items():
                for r in rows:
                    self.assertEqual(r['status'], 'ACCEPTED', (label, r))

        # cloud : rien perdu, rien melange
        self.assertEqual(InvoiceLine.objects.get(invoice_id=i1.pk).quantity, 3)
        self.assertEqual(InvoiceLine.objects.get(invoice_id=i2.pk).quantity, 4)
        got = {(l.session_id, l.source): l.quantity for l in ProductionSessionLine.objects.all()}
        self.assertEqual(got, {(s1.pk, 'DECLARED'): 70, (s1.pk, 'CARRYOVER'): 20, (s2.pk, 'DECLARED'): 33})
        self.assertEqual(BreadTransferLine.objects.get(transfer_id=t1.pk).quantity_sent, 100)
        self.assertEqual(BreadTransferLine.objects.get(transfer_id=t2.pk).quantity_sent, 40)
        c1 = ProductionSession.objects.get(pk=s1.pk)
        self.assertEqual((c1.total_breads, c1.total_fc_produced, c1.theoretical_yield),
                         (90, 70 * self.b3.unit_price, 300000))
        self.assertEqual(c1.yield_gap, 70 * self.b3.unit_price - 300000)

        # apply_push_response : tout est marque synchronise, plus rien a envoyer
        apply_push_response(d1)
        apply_push_response(d2)
        for code in (self.k1.code, self.k2.code):
            left = {k: v for k, v in build_outbound_payload(code)['records'].items() if v}
            self.assertEqual(left, {}, code)

    def test_cycle_rejeu_reponse_perdue_idempotent(self):
        i1, s1, t1 = self._poste_k1()
        p1 = self._export_and_wipe(self.k1.code, (i1, s1, t1))
        self._post(self.a1, p1)
        n = (InvoiceLine.objects.count(), ProductionSessionLine.objects.count(), BreadTransferLine.objects.count())
        for _ in range(2):  # le poste n'a jamais recu la reponse : meme lot rejoue
            d = self._post(self.a1, dict(p1, batch_id=str(uuid.uuid4())))
            self.assertTrue(all(r['status'] == 'ACCEPTED' for v in d['results'].values() for r in v), d['results'])
        self.assertEqual(n, (InvoiceLine.objects.count(), ProductionSessionLine.objects.count(),
                             BreadTransferLine.objects.count()))
        self.assertEqual(ProductionSession.objects.get(pk=s1.pk).total_breads, 90)

    def test_cycle_poste_ancien_sans_source_ne_cree_pas_de_doublon(self):
        i1, s1, t1 = self._poste_k1()
        p1 = self._export_and_wipe(self.k1.code, (i1, s1, t1))
        for l in p1['records']['production.ProductionSessionLine']:
            l.pop('source')
        d = self._post(self.a1, p1)
        # sans source : les deux lignes (id 7, 8) visent (session, pain 3, DECLARED) : derniere valeur retenue
        self.assertEqual(ProductionSessionLine.objects.filter(session_id=s1.pk).count(), 1)
        self.assertTrue(all(r['status'] == 'ACCEPTED' for v in d['results'].values() for r in v))

    def test_cycle_apply_response_hostile_sans_crash(self):
        for bad in (None, [], {'results': None}, {'results': {'production.ProductionSessionLine': 'x'}},
                    {'results': {'sales.Invoice': [{'status': 'ACCEPTED', 'id': '7'}, 5, None]}},
                    {'results': {'nope.Model': [{'status': 'ACCEPTED', 'id': uid()}]}}):
            apply_push_response(bad)
