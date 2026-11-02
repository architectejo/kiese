"""
BUG-120 (docs/qa/REGISTRE_BUGS.md), Chantier C (2026-11-02) : rapport de
clôture journalier CONSOLIDÉ, par boulangerie et par jour, décomposé par
catégorie de pain — réunit Production (`ProductionSession`,
`DailyBreadStockSnapshot`, `BreadDisposal`, `BreadTransfer`) et Ventes
(`sales.Invoice`/`InvoiceLine`) en un seul document, conformément au vrai
rapport de clôture du client (`data_kiese/EXTRAIT RAPPORT DE
CLOTUREOCTOBRE 2026.xlsx`).

Scénario couvert : deux catégories de pain (300 FC / 500 FC), les deux
équipes A et B, une régularisation (`Invoice.is_adjustment`) et un transfert
inter-boulangeries confirmé — tous les totaux dérivés sont recalculés à la
main en `Decimal` dans ce test pour vérifier l'exactitude de l'agrégation
(jamais de constante arbitraire recopiée depuis la vue).
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import ProductionSession, DailyBreadStockSnapshot


def _q2(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class DailyClosureReportTests(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.other_node = make_node()

        self.gerant = make_user(role='GERANT', node=self.node)
        self.facturier = make_user(role='FACTURIER', node=self.node, team='A')
        self.other_gerant = make_user(role='GERANT', node=self.other_node)

        self.bp300 = make_bread_price(category='BUG120_300', label='Pain 300 FC', unit_price=300)
        self.bp500 = make_bread_price(category='BUG120_500', label='Pain 500 FC', unit_price=500)

        self.client1 = make_client(self.node, credit_limit=Decimal('500000.00'))

        self.gerant_api = APIClient()
        self.gerant_api.force_authenticate(self.gerant)
        self.facturier_api = APIClient()
        self.facturier_api.force_authenticate(self.facturier)
        self.other_gerant_api = APIClient()
        self.other_gerant_api.force_authenticate(self.other_gerant)

        self.today = timezone.localdate()
        self.yesterday = self.today - timedelta(days=1)

    # ---- fabriques de scénario -------------------------------------------------

    def _declare_session(self, api, team, date, flour, lines):
        resp = api.post('/api/production/sessions/', {
            'team': team, 'date': str(date), 'flour_sacks_used': str(flour),
            'lines': [{'bread_price': bp.pk, 'quantity': qty} for bp, qty in lines],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data['id']

    def _dispose(self, api, session_id, bp, disposal_type, qty, unit_price_sold=0):
        resp = api.post('/api/production/disposals/', {
            'session': session_id, 'bread_price': bp.pk,
            'disposal_type': disposal_type, 'quantity': qty,
            'unit_price_sold': unit_price_sold,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)

    def _close(self, api, session_id):
        resp = api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(resp.status_code, 200, resp.data)

    def _create_invoice(self, api, **payload):
        resp = api.post('/api/sales/invoices/', payload, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def _deliver(self, api, invoice_id):
        resp = api.post(f'/api/sales/invoices/{invoice_id}/deliver/')
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data

    def _build_scenario(self):
        # --- Veille : l'équipe A clôture avec un reste de 15 pains 300 FC,
        # pour que RESTE DU HIER soit non-nul le jour du rapport.
        prev_session = self._declare_session(
            self.gerant_api, 'A', self.yesterday, '1.00', [(self.bp300, 50)]
        )
        self._dispose(self.gerant_api, prev_session, self.bp300, 'REMAINING', 15)
        self._close(self.gerant_api, prev_session)

        # --- Jour du rapport : deux sessions (équipes A et B).
        session_a = self._declare_session(
            self.gerant_api, 'A', self.today, '2.00',
            [(self.bp300, 100), (self.bp500, 50)],
        )
        session_b = self._declare_session(
            self.gerant_api, 'B', self.today, '1.00', [(self.bp300, 40)],
        )

        self._dispose(self.gerant_api, session_a, self.bp300, 'REMAINING', 20)
        self._dispose(self.gerant_api, session_a, self.bp500, 'REMAINING', 10)
        self._dispose(self.gerant_api, session_a, self.bp300, 'DECLASSED', 5)
        self._dispose(self.gerant_api, session_b, self.bp300, 'REMAINING', 10)

        self._close(self.gerant_api, session_a)
        self._close(self.gerant_api, session_b)

        # --- Vente normale (client régulier, CM 25 %).
        invoice1 = self._create_invoice(
            self.facturier_api,
            client=str(self.client1.pk), payment_type='CASH',
            payment_amount='19000.00', commission_rate='0.25',
            lines=[
                {'bread_price': self.bp300.pk, 'quantity': 30},
                {'bread_price': self.bp500.pk, 'quantity': 20},
            ],
        )
        self._deliver(self.facturier_api, invoice1['id'])

        # --- Vente soldée (prix à 75 %, CM = 0, pas de client).
        invoice2 = self._create_invoice(
            self.facturier_api,
            payment_type='CASH', payment_amount='2250.00', is_soldee=True,
            lines=[{'bread_price': self.bp300.pk, 'quantity': 10}],
        )
        self._deliver(self.facturier_api, invoice2['id'])

        # --- Régularisation (BUG-097) : +10 pains 300 FC sur la facture 1.
        adjust_resp = self.gerant_api.post(
            f"/api/sales/invoices/{invoice1['id']}/adjust/", {
                'adjustment_sign': 1, 'payment_amount': '0.00',
                'lines': [{'bread_price': self.bp300.pk, 'quantity': 10}],
            }, format='json'
        )
        self.assertEqual(adjust_resp.status_code, 201, adjust_resp.data)

        # --- Transfert inter-boulangeries confirmé le jour du rapport :
        # other_node envoie 15 pains 300 FC à node.
        create_resp = self.gerant_api.post('/api/production/transfers/', {
            'from_node': self.other_node.pk,
            'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 15}],
        }, format='json')
        self.assertEqual(create_resp.status_code, 201, create_resp.data)
        transfer_id = create_resp.data['id']

        respond_resp = self.other_gerant_api.post(
            f'/api/production/transfers/{transfer_id}/respond_to_request/', {
                'approved': True,
                'lines': [{'bread_price': self.bp300.pk, 'quantity_sent': 15}],
            }, format='json'
        )
        self.assertEqual(respond_resp.status_code, 200, respond_resp.data)

        confirm_resp = self.gerant_api.post(
            f'/api/production/transfers/{transfer_id}/confirm_reception/', {
                'lines': [{'bread_price': self.bp300.pk, 'quantity_received': 15}],
            }, format='json'
        )
        self.assertEqual(confirm_resp.status_code, 200, confirm_resp.data)
        self.assertEqual(confirm_resp.data['transfer_status'], 'CONFIRMED')

    # ---- le test ----------------------------------------------------------------

    def test_daily_closure_report_aggregates_exact_totals(self):
        self._build_scenario()

        resp = self.gerant_api.get(
            '/api/production/daily-closure/', {'date': str(self.today)}
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        data = resp.data

        self.assertEqual(data['node'], self.node.code)
        self.assertEqual(data['date'], str(self.today))

        by_bp = {row['bread_price']: row for row in data['categories']}
        row300 = by_bp[self.bp300.pk]
        row500 = by_bp[self.bp500.pk]

        # --- Production déclarée par catégorie, jour du rapport uniquement.
        self.assertEqual(row300['produit']['quantity'], 140)  # 100 (A) + 40 (B)
        self.assertEqual(row500['produit']['quantity'], 50)
        self.assertEqual(row300['produit']['fc'], str(_q2(Decimal(140) * Decimal(300))))
        self.assertEqual(row500['produit']['fc'], str(_q2(Decimal(50) * Decimal(500))))

        # --- FACTURE/JR + COMMISSION/JR (vente normale uniquement).
        self.assertEqual(row300['facture_jr'], {'quantity': 30, 'fc': '9000.00'})
        self.assertEqual(row500['facture_jr'], {'quantity': 20, 'fc': '10000.00'})
        self.assertEqual(row300['commission_jr']['fc'], str(_q2(Decimal('9000') * Decimal('0.25'))))
        self.assertEqual(row500['commission_jr']['fc'], str(_q2(Decimal('10000') * Decimal('0.25'))))

        # --- RESTE DU JOUR / RESTE DU HIER par équipe (Chantier B, repris).
        self.assertEqual(row300['reste_du_jour'], {'A': 20, 'B': 10})
        self.assertEqual(row500['reste_du_jour'], {'A': 10, 'B': None})
        self.assertEqual(row300['reste_du_hier'], {'A': -15, 'B': 0})
        self.assertEqual(row500['reste_du_hier'], {'A': 0, 'B': 0})

        # Recoupement direct avec les primitives du Chantier B (même source).
        self.assertEqual(
            DailyBreadStockSnapshot.reste_du_jour(self.node, self.bp300, self.today, 'A'), 20
        )
        self.assertEqual(
            DailyBreadStockSnapshot.reste_du_hier(self.node, self.bp300, self.today, 'A'), -15
        )

        # --- Vente soldée (prix à 75 %, perte = 25 % du catalogue).
        self.assertEqual(row300['vente_cash_soldee']['quantity'], 10)
        self.assertEqual(row300['vente_cash_soldee']['fc'], '2250.00')
        self.assertEqual(row300['vente_cash_soldee']['perte_fc'], '750.00')
        self.assertEqual(row500['vente_cash_soldee']['quantity'], 0)

        # --- Régularisation (+10 pains 300 FC, signée).
        self.assertEqual(row300['regularisation'], {'quantity': 10, 'fc': '3000.00'})
        self.assertEqual(row500['regularisation'], {'quantity': 0, 'fc': '0.00'})

        # --- Non servi : aucune facture NS dans ce scénario → zéro partout.
        self.assertEqual(row300['non_servi'], {'quantity': 0, 'fc': '0.00'})

        # --- Dispositions (hors REMAINING, qui alimente le snapshot ci-dessus).
        # `unit_price_sold=0` dans `_dispose()` (fabrique du test) → valeur en
        # FC nulle pour ces dispositions, indépendamment de la quantité.
        self.assertEqual(row300['declasses']['quantity'], 5)
        self.assertEqual(row300['declasses']['fc'], '0.00')
        self.assertEqual(row300['non_vendu_nv']['quantity'], 0)
        self.assertEqual(row300['non_vendu_nv']['fc'], '0.00')
        self.assertEqual(row500['declasses']['quantity'], 0)

        # --- Transfert confirmé ce jour (other_node → node) — valorisé au
        # prix catalogue de la catégorie (aucun autre prix n'est porté par
        # `BreadTransferLine`).
        self.assertEqual(row300['appro_recu']['quantity'], 15)
        self.assertEqual(row300['appro_recu']['fc'], str(_q2(Decimal(15) * Decimal(300))))
        self.assertEqual(row300['appro_effectue']['quantity'], 0)
        self.assertEqual(row300['appro_effectue']['fc'], '0.00')
        self.assertEqual(row500['appro_recu']['quantity'], 0)
        self.assertEqual(row500['appro_recu']['fc'], '0.00')

        # --- FACTURE MVM INTERNE (Q-006, réponse client) : somme en FC de
        # RESTE DU JOUR + RESTE DU HIER + APPRO EFFECTUE + APPRO REÇU +
        # NON SERVI + RÉGULARISATION + VENTE CASH/SOLDE + NON VENDU +
        # DÉCLASSÉS (EXCÉDENT/MANQUANT par catégorie non modélisés → 0),
        # recalculée à la main pour la catégorie 300 FC :
        #   reste_du_jour_fc  = (20 + 10) × 300 =  9 000
        #   reste_du_hier_fc  = (-15 + 0) × 300 = -4 500
        #   appro_effectue_fc = 0 × 300         =      0
        #   appro_recu_fc     = 15 × 300        =  4 500
        #   non_servi_fc      =                 =      0
        #   regularisation_fc =                 =  3 000
        #   vente_cash_soldee_fc =               =  2 250
        #   non_vendu_nv_fc + declasses_fc      =      0
        mvm_300_fc = Decimal('9000') - Decimal('4500') + Decimal('0') + Decimal('4500') \
            + Decimal('0') + Decimal('3000') + Decimal('2250') + Decimal('0') + Decimal('0')
        self.assertEqual(mvm_300_fc, Decimal('14250'))
        self.assertEqual(row300['facture_mvm_interne'], {'fc': str(_q2(mvm_300_fc))})

        # Catégorie 500 FC : seul RESTE DU JOUR est non nul (10 × 500).
        mvm_500_fc = Decimal('5000')
        self.assertEqual(row500['facture_mvm_interne'], {'fc': str(_q2(mvm_500_fc))})

        # --- Totaux dérivés — recalculés à la main en Decimal.
        totals = data['totals']

        net_produit_fc = Decimal('55000') + Decimal('12000')  # 100*300+50*500, 40*300
        self.assertEqual(totals['net_produit_fc'], str(_q2(net_produit_fc)))
        self.assertEqual(net_produit_fc, Decimal('67000'))

        total_facture_fc = Decimal('9000') + Decimal('10000')
        # TOTAL DU JOUR (Q-006, réponse client) = facturation normale +
        # FACTURE MVM INTERNE (sous-total ci-dessus, par catégorie).
        total_mvm_interne_fc = mvm_300_fc + mvm_500_fc
        total_du_jour_fc = total_facture_fc + total_mvm_interne_fc
        self.assertEqual(totals['total_du_jour_fc'], str(_q2(total_du_jour_fc)))
        self.assertEqual(total_du_jour_fc, Decimal('38250'))

        # ECART/FACTURE (Q-007.1, réponse client) = valeur commandée du jour
        # (toutes factures livrées ce jour) − paiements reçus sur ces
        # commandes. Factures livrées aujourd'hui pour ce nœud :
        #   invoice1 (normale)       : order_total=19000, payment_amount=19000
        #   invoice2 (soldée)        : order_total= 2250, payment_amount= 2250
        #   ajustement de invoice1   : order_total= 3000, payment_amount=    0
        commande_du_jour = Decimal('19000') + Decimal('2250') + Decimal('3000')
        paye_du_jour = Decimal('19000') + Decimal('2250') + Decimal('0')
        ecart_facture_fc = commande_du_jour - paye_du_jour
        self.assertEqual(totals['ecart_facture_fc'], str(_q2(ecart_facture_fc)))
        self.assertEqual(ecart_facture_fc, Decimal('3000'))

        sacs_produits = Decimal('2.00') + Decimal('1.00')
        self.assertEqual(totals['nombre_sacs_produits'], str(sacs_produits))

        moyenne_produit_par_sac_fc = (net_produit_fc / sacs_produits).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        self.assertEqual(totals['moyenne_produit_par_sac_fc'], str(moyenne_produit_par_sac_fc))

        total_breads_billed = (30 + 20) + 10 + 10  # facture normale + soldée + régularisation
        self.assertEqual(totals['total_breads_billed'], total_breads_billed)

        # Tarif vente (Q-007.2, réponse client) : valeur FIXE saisie par
        # boulangerie (`Node.sac_value_fc`, 200 000 FC dans `setUp`), jamais
        # une moyenne recalculée à partir des ventes du jour.
        self.assertEqual(totals['tarif_vente_fc'], '200000')

        yield_gap_a = Decimal('55000') - Decimal('2.00') * Decimal('200000')
        yield_gap_b = Decimal('12000') - Decimal('1.00') * Decimal('200000')
        ecart_production_fc = yield_gap_a + yield_gap_b
        self.assertEqual(totals['ecart_production_fc'], str(int(ecart_production_fc)))
        self.assertEqual(ecart_production_fc, Decimal('-533000'))

        total_breads_produced = 140 + 50
        self.assertEqual(totals['total_breads_produced'], total_breads_produced)

        # Répartition de pains EN % (Q-007.3, réponse client) : les deux
        # variantes (quantité et valeur) sont exposées simultanément.
        repartition_qty = {row['bread_price']: Decimal(row['pct']) for row in totals['repartition_pct_par_quantite']}
        pct_300_qty = (Decimal(140) * Decimal('100') / Decimal(total_breads_produced)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        pct_500_qty = (Decimal(50) * Decimal('100') / Decimal(total_breads_produced)).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        self.assertEqual(repartition_qty[self.bp300.pk], pct_300_qty)
        self.assertEqual(repartition_qty[self.bp500.pk], pct_500_qty)
        self.assertEqual(pct_300_qty + pct_500_qty, Decimal('100.00'))

        total_produced_value_fc = Decimal(140) * Decimal(300) + Decimal(50) * Decimal(500)
        self.assertEqual(total_produced_value_fc, net_produit_fc)  # même base (catalogue × quantité)
        repartition_val = {row['bread_price']: Decimal(row['pct']) for row in totals['repartition_pct_par_valeur']}
        pct_300_val = (
            Decimal(140) * Decimal(300) * Decimal('100') / total_produced_value_fc
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        pct_500_val = (
            Decimal(50) * Decimal(500) * Decimal('100') / total_produced_value_fc
        ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.assertEqual(repartition_val[self.bp300.pk], pct_300_val)
        self.assertEqual(repartition_val[self.bp500.pk], pct_500_val)
        self.assertEqual(pct_300_val + pct_500_val, Decimal('100.00'))

    def test_non_hq_user_cannot_override_node_query_param(self):
        """
        BUG-120 : un GERANT (non-HQ) ne doit jamais pouvoir consulter le
        rapport d'une autre boulangerie en forgeant `?node=` — même motif que
        `get_queryset()` partout ailleurs dans ce module (BUG-056/BUG-025).
        """
        self._declare_session(self.gerant_api, 'A', self.today, '1.00', [(self.bp300, 10)])
        resp = self.gerant_api.get('/api/production/daily-closure/', {
            'node': self.other_node.pk, 'date': str(self.today),
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        # Toujours sa propre boulangerie, jamais celle demandée dans le payload.
        self.assertEqual(resp.data['node'], self.node.code)

    def test_headquarters_can_select_any_node(self):
        hq = make_user(role='DIRECTION', node=None)
        hq_api = APIClient()
        hq_api.force_authenticate(hq)

        self._declare_session(self.gerant_api, 'A', self.today, '1.00', [(self.bp300, 10)])

        resp = hq_api.get('/api/production/daily-closure/', {
            'node': self.node.code, 'date': str(self.today),
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['node'], self.node.code)
        self.assertEqual(
            {row['bread_price']: row['produit']['quantity'] for row in resp.data['categories']}[self.bp300.pk],
            10,
        )

    def test_missing_date_param_returns_400(self):
        resp = self.gerant_api.get('/api/production/daily-closure/')
        self.assertEqual(resp.status_code, 400)

    def test_headquarters_without_node_param_returns_400(self):
        hq = make_user(role='DIRECTION', node=None)
        hq_api = APIClient()
        hq_api.force_authenticate(hq)
        resp = hq_api.get('/api/production/daily-closure/', {'date': str(self.today)})
        self.assertEqual(resp.status_code, 400)
