"""Auditeur comptable (Dev A, 2026-11-23 a) : recoupement de la cloture journaliere.

AUCUNE donnee reelle : jeu fictif reproduisant les regles de CLAUDE.md 5.4 / 5.5 et de la formule BUG-319 :
    produit = vendus + reste du jour - reste d'hier + (soldes/declasses/invendus/gratuits) + envoyes - recus.
Prix fictifs : MINI 300 FC, MOYEN 500 FC (BreadPrice de test). Les `expectedFailure` referencent leur ticket.
"""
from datetime import date as ddate, timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from core.testing import make_client
from production.models import (BreadDisposal, DailyBreadStockSnapshot, ProductionSession)
from production.tests.test_verif_a4_testeur_production import TBase, cl

TODAY = ddate.today()


def _cat(data, bp):
    return next(c for c in data['categories'] if c['bread_price'] == bp.pk)


class ClotureIdentite(TBase):
    """Jour complet K1 (equipe A) : tous les flux de la formule, chiffres calcules a la main."""

    def _sale(self, qty, soldee=False, bp=None):
        bp = bp or self.b3
        unit = 225 if (soldee and bp.unit_price == 300) else bp.unit_price
        client = make_client(self.k1, credit_limit=Dc('9000000'))
        body = {'payment_type': 'CASH', 'payment_amount': str(qty * unit), 'client': str(client.pk),
                'lines': [{'bread_price': bp.pk, 'quantity': qty}]}
        if soldee:
            body['is_soldee'] = True
        r = cl(self.fac).post('/api/sales/invoices/', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        d = cl(self.liv).post(f"/api/sales/invoices/{r.data['id']}/deliver/")
        self.assertEqual(d.status_code, 200, d.content)

    def _day(self, with_free=True, with_sold_discount=False, closed=True):
        """Veille : reste 20 MINI. Aujourd'hui : 40 vendus normal, 10 soldes (75 %), 3 invendus, 2 declasses,
        4 gratuits, 5 envoyes a K2, reste 8."""
        yest = TODAY - timedelta(days=1)
        DailyBreadStockSnapshot.objects.create(node=self.k1, bread_price=self.b3, date=yest, team='A', qty_at_close=20)
        s = ProductionSession.objects.create(
            node=self.k1, date=TODAY, team='A', flour_sacks_used=Dc('1'), auto_track=True, is_closed=False)
        self._sale(40)
        self._sale(10, soldee=True)
        mk = lambda t, q, p=0: BreadDisposal.objects.create(node=self.k1, session=s, bread_price=self.b3,
                                                            disposal_type=t, quantity=q, unit_price_sold=p)
        mk('UNSOLD', 3)
        mk('DECLASSED', 2)
        if with_free:
            mk('FREE_DIST', 4)
        if with_sold_discount:
            mk('SOLD_DISCOUNT', 6, 225)
        t = cl(self.g1).post('/api/production/transfers/send/',
                             {'to_node': self.k2.pk, 'lines': [{'bread_price': self.b3.pk, 'quantity_sent': 5}]},
                             format='json')
        self.assertEqual(t.status_code, 201, t.content)
        c = cl(self.g2).post(f"/api/production/transfers/{t.data['id']}/confirm_reception/",
                             {'lines': [{'bread_price': self.b3.pk, 'quantity_received': 5}]}, format='json')
        self.assertEqual(c.status_code, 200, c.content)
        BreadDisposal.objects.create(node=self.k1, session=s, bread_price=self.b3,
                                     disposal_type='REMAINING', quantity=8, unit_price_sold=0)
        DailyBreadStockSnapshot.objects.create(node=self.k1, bread_price=self.b3, date=TODAY, team='A', qty_at_close=8)
        if closed:
            ProductionSession.objects.filter(pk=s.pk).update(is_closed=True)
        return s

    def _rep(self, user=None):
        r = cl(user or self.g1).get('/api/production/daily-closure/', {'date': str(TODAY)})
        self.assertEqual(r.status_code, 200, r.content)
        return r.data

    def test_produit_derive_formule_a_la_main(self):
        self._day()
        row = _cat(self._rep(), self.b3)
        # 40 + 10 vendus + 8 reste - 20 reste d'hier + (3+2+4) + 5 envoyes - 0 recus = 52
        self.assertEqual(row['produit']['quantity'], 52)
        self.assertEqual(row['produit']['fc'], '15600.00')

    def test_total_du_jour_et_ecart_avec_valeur_produite(self):
        """Caracterise le rapprochement valeur produite / total du jour sur le jeu fictif.
        Les dispositions sont valorisees a `unit_price_sold` (0 pour invendus/declasses/gratuits saisis sans prix).
        total_du_jour = facture 12 000 + mvm (reste jour 2 400 - reste hier 6 000 + envoyes 1 500 + soldee 2 250)
        = 12 150. Produit = 15 600. Ecart = 3 450 = invendus 900 + declasses 600 + gratuits 1 200 + perte soldee 750."""
        self._day()
        d = self._rep()
        row = _cat(d, self.b3)
        self.assertEqual(row['facture_mvm_interne']['fc'], '150.00')
        self.assertEqual(d['totals']['total_du_jour_fc'], '12150.00')
        self.assertEqual(row['vente_cash_soldee']['perte_fc'], '750.00')   # 10 x (300 - 225)
        self.assertEqual(row['sorties_gratuites'], {'quantity': 4, 'fc': '0.00'})
        ecart = Dc(row['produit']['fc']) - Dc(d['totals']['total_du_jour_fc'])
        self.assertEqual(ecart, Dc('3450'))

    @expectedFailure
    def test_total_du_jour_inclut_les_sorties_gratuites(self):
        """A CLARIFIER (BUG-1200 / Q-043) : les sorties gratuites sont dans le produit derive mais pas dans
        la somme FACTURE MVM INTERNE (le classeur est inconnu sur ce point). Si le client veut l'identite
        stricte, total_du_jour + perte soldee = valeur produite."""
        self._day()
        d = self._rep()
        row = _cat(d, self.b3)
        self.assertEqual(Dc(d['totals']['total_du_jour_fc']) + Dc(row['vente_cash_soldee']['perte_fc']),
                         Dc(row['produit']['fc']))

    def test_soldes_declares_en_disposition_comptes_dans_le_total(self):
        """BUG-1201 : une disposition SOLD_DISCOUNT (soldes) entre dans le produit derive (R5) mais dans
        aucune rubrique de FACTURE MVM INTERNE : la valeur disparait du total du jour."""
        self._day(with_free=False, with_sold_discount=True)
        d = self._rep()
        row = _cat(d, self.b3)
        # produit = 40+10+8-20+(3+2+6)+5 = 54 -> 16 200 ; total = 12 000 + 1 650 + 6 x 225 (ou 300)
        self.assertEqual(row['produit']['quantity'], 54)
        mvm = Dc(row['facture_mvm_interne']['fc'])
        self.assertGreater(mvm, Dc('150'))  # + 6 x 225 = 1 350 attendus

    def test_somme_nulle_du_groupe_sur_les_transferts(self):
        self._day()
        k1 = _cat(self._rep(self.g1), self.b3)
        k2 = _cat(self._rep(self.g2), self.b3)
        self.assertEqual(k1['appro_effectue']['quantity'], 5)
        self.assertEqual(k2['appro_recu']['quantity'], 5)
        self.assertEqual(Dc(k1['appro_effectue']['fc']) - Dc(k2['appro_recu']['fc']), 0)
        # contribution au total du jour : +1 500 emettrice, -1 500 receptrice
        self.assertEqual(Dc(k2['facture_mvm_interne']['fc']), Dc('-1500'))

    def test_repli_repartition_jour_non_cloture(self):
        """BUG-676 : journee non cloturee, repli sur vendus ; 40 normal + 10 soldee = 50 pains."""
        self._day(closed=False)
        d = self._rep()
        self.assertEqual(d['totals']['repartition_base'], 'vendu_jour')
        pcts = {x['bread_price']: Dc(x['pct']) for x in d['totals']['repartition_pct_par_quantite']}
        self.assertEqual(pcts[self.b3.pk], Dc('100.00'))

    def test_perte_soldee_utilise_le_prix_plein_fige(self):
        """full_unit_price fige : un changement de tarif apres la vente ne change pas la perte du jour."""
        self._day()
        self.b3.unit_price = 400
        self.b3.save()
        row = _cat(self._rep(), self.b3)
        self.assertEqual(row['vente_cash_soldee']['perte_fc'], '750.00')


class ClotureDeuxEquipesMemeJour(TBase):
    """Hors rotation, deux equipes clotures le meme jour : le reste du jour est celui du DERNIER instantane
    (le tas de pains est partage). BUG-1202 : la somme par equipe double le compte dans FACTURE MVM INTERNE."""

    @expectedFailure
    def test_reste_du_jour_deux_equipes(self):
        yest = TODAY - timedelta(days=1)
        for team, q in (('A', 10), ('B', 3)):   # B cloture en dernier la veille
            snap = DailyBreadStockSnapshot.objects.create(node=self.k1, bread_price=self.b3, date=yest, team=team, qty_at_close=q)
        for team, q in (('A', 12), ('B', 8)):   # B cloture en dernier aujourd'hui
            s = ProductionSession.objects.create(node=self.k1, date=TODAY, team=team, flour_sacks_used=Dc('1'),
                                                 auto_track=True, is_closed=True)
            DailyBreadStockSnapshot.objects.create(node=self.k1, bread_price=self.b3, date=TODAY, team=team, qty_at_close=q)
        r = cl(self.g1).get('/api/production/daily-closure/', {'date': str(TODAY)})
        self.assertEqual(r.status_code, 200, r.content)
        row = _cat(r.data, self.b3)
        self.assertEqual(row['reste_du_jour_jour'], 8)
        mvm = Dc(row['facture_mvm_interne']['fc'])
        # journalier (derive de la production) : reste du jour 8 - reste d'hier 3 = 5 pains = 1 500 FC
        jour = Dc(row['reste_du_jour_jour']) * 300 + Dc(row['reste_du_hier_jour']) * 300
        self.assertEqual(mvm, jour)

    def test_champs_jour_et_totaux_coherents(self):
        yest = TODAY - timedelta(days=1)
        DailyBreadStockSnapshot.objects.create(node=self.k1, bread_price=self.b3, date=yest, team='A', qty_at_close=10)
        ProductionSession.objects.create(node=self.k1, date=TODAY, team='A', flour_sacks_used=Dc('1'),
                                         auto_track=True, is_closed=True)
        DailyBreadStockSnapshot.objects.create(node=self.k1, bread_price=self.b3, date=TODAY, team='A', qty_at_close=7)
        r = cl(self.g1).get('/api/production/daily-closure/', {'date': str(TODAY)})
        row = _cat(r.data, self.b3)
        self.assertEqual(Dc(row['facture_mvm_interne']['fc']), Dc('7') * 300 - Dc('10') * 300)
        self.assertEqual(r.data['totals']['reste_du_jour_jour_fc'], '2100.00')
        self.assertEqual(r.data['totals']['reste_du_hier_jour_fc'], '-3000.00')
