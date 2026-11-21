"""
Vérification indépendante (testeur-production, 2026-11-20) de :
  - BUG-325 : hors rotation, « Stock de départ » proposé = dernier reste DÉCLARÉ
    (instantané), borné à 0 ; sans instantané, stock courant ;
  - BUG-327 (backend) : GET /api/production/daily-closure/clients/.

Valeurs calculées à la main. Données fictives (`core.testing`). Aucune
modification du code applicatif.
"""
from datetime import date, datetime
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import (
    BreadStock, DailyBreadStockSnapshot, DailyOpeningConfirmationLine,
)
from sales.models import Invoice

OPENING = '/api/production/opening-confirmation/'
URL = '/api/production/daily-closure/clients/'
CLOSURE = '/api/production/daily-closure/'
D1 = date(2026, 10, 14)
D2 = date(2026, 10, 15)


def _api(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def _aware(d, hour=10, minute=0):
    return timezone.make_aware(datetime(d.year, d.month, d.day, hour, minute), timezone.get_current_timezone())


# ---------------------------------------------------------------------------
# BUG-325
# ---------------------------------------------------------------------------
class Bug325Tests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.g = _api(make_user('GERANT', node=self.node))
        self.f = _api(make_user('FACTURIER', node=self.node))
        self.bp = make_bread_price('V325T_500', 'Pain 500 V325T', 500)

    def snap(self, d, qty, team='A'):
        return DailyBreadStockSnapshot.objects.create(
            node=self.node, bread_price=self.bp, date=d, team=team, qty_at_close=qty)

    def proposed(self, d=D2, api=None):
        r = (api or self.g).get(OPENING, {'date': str(d)})
        self.assertEqual(r.status_code, 200, r.data)
        return {c['bread_price']: c['qty_proposed'] for c in r.data['categories']}[self.bp.pk]

    def test_hors_rotation_ignore_stock_courant_quand_snapshot(self):
        self.assertFalse(self.node.team_rotation_enabled)
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=-100)
        self.snap(D1, 30)
        self.assertEqual(self.proposed(), 30)

    def test_hors_rotation_stock_positif_ignore_au_profit_du_snapshot(self):
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=999)
        self.snap(D1, 7)
        self.assertEqual(self.proposed(), 7)

    def test_snapshot_le_plus_recent_gagne(self):
        self.snap(date(2026, 10, 12), 5)
        self.snap(D1, 11)
        self.assertEqual(self.proposed(), 11)

    def test_snapshot_posterieur_a_la_date_ignore(self):
        self.snap(date(2026, 10, 20), 50)
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=4)
        self.assertEqual(self.proposed(D2), 4)

    def test_snapshot_negatif_borne_a_zero(self):
        self.snap(D1, -20)
        self.assertEqual(self.proposed(), 0)

    def test_sans_snapshot_stock_courant_positif(self):
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=12)
        self.assertEqual(self.proposed(), 12)

    def test_sans_snapshot_sans_stock_zero(self):
        self.assertEqual(self.proposed(), 0)

    def test_sans_snapshot_stock_courant_negatif_expose_tel_quel(self):
        # BUG-330 : changement de spécification voulu (règle « plus de
        # négatifs » BUG-317, remarque.md l.441) : proposition bornée à 0,
        # le stock réel reste inchangé.
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=-20)
        self.assertEqual(self.proposed(), 0)
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available, -20)

    def test_bug330_rotation_sans_snapshot_stock_negatif_borne(self):
        self.node.team_rotation_enabled = True
        self.node.save()
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=-20)
        self.assertEqual(self.proposed(), 0)

    def test_rotation_inchangee_snapshot_prime(self):
        self.node.team_rotation_enabled = True
        self.node.save()
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=99)
        self.snap(D1, 7)
        self.assertEqual(self.proposed(), 7)

    def test_rotation_sans_snapshot_stock_courant(self):
        self.node.team_rotation_enabled = True
        self.node.save()
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=13)
        self.assertEqual(self.proposed(), 13)

    def test_isolation_snapshot_autre_noeud(self):
        k2 = make_node(code='K2')
        DailyBreadStockSnapshot.objects.create(node=k2, bread_price=self.bp, date=D1, team='A', qty_at_close=77)
        self.assertEqual(self.proposed(), 0)

    def test_bug317_quantite_negative_refusee_a_la_confirmation(self):
        r = self.f.post(OPENING, {'team': 'A', 'date': str(D2),
                                  'lines': [{'bread_price': self.bp.pk, 'qty': -5}]}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(DailyOpeningConfirmationLine.objects.filter(bread_price=self.bp).exists())

    def test_bug317_proposition_bornee_acceptee_a_la_confirmation(self):
        self.snap(D1, -20)
        q = self.proposed()
        r = self.f.post(OPENING, {'team': 'A', 'date': str(D2),
                                  'lines': [{'bread_price': self.bp.pk, 'qty': q}]}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)

    def test_proposition_ne_modifie_pas_le_stock(self):
        BreadStock.objects.create(node=self.node, bread_price=self.bp, qty_adjusted=3)
        self.snap(D1, 30)
        self.proposed()
        self.assertEqual(BreadStock.objects.get(node=self.node, bread_price=self.bp).qty_available, 3)


# ---------------------------------------------------------------------------
# BUG-327
# ---------------------------------------------------------------------------
class _Base(TestCase):
    _seq = 0

    def setUp(self):
        self.node = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.gerant = make_user('GERANT', node=self.node)
        self.api = _api(self.gerant)
        self.alice = make_client(self.node, last_name='Alpha', first_name='Anne', current_debt=Decimal('7000'))
        self.bob = make_client(self.node, last_name='Beta', first_name='Bob', current_debt=Decimal('-500'))

    def inv(self, client, order='1000', paid='0', before='0', hour=10, day=D1, status=Invoice.Status.DELIVERED,
            node=None, team='A', rate='0.25', delivered=None, **kw):
        _Base._seq += 1
        node = node or self.node
        if delivered is None:
            delivered = _aware(day, hour) if status == Invoice.Status.DELIVERED else None
        return Invoice.objects.create(
            node=node, node_origin=node.code, client=client, team=team, status=status,
            order_total=Decimal(order), payment_amount=Decimal(paid), debt_before=Decimal(before),
            debt_after=Decimal(before) + Decimal(order) - Decimal(paid), commission_rate=Decimal(rate),
            invoice_date=day, delivered_at=delivered, receipt_number=f'V327T-{_Base._seq}', **kw)

    def get(self, api=None, **params):
        params.setdefault('date', str(D1))
        return (api or self.api).get(URL, params)


class Bug327ContenuTests(_Base):
    def test_commission_25_et_30_pour_cent(self):
        self.inv(self.alice, '10000', '0', rate='0.25')
        self.inv(self.bob, '10000', '0', rate='0.30')
        rows = {x['client_name']: x for x in self.get().data['results']}
        self.assertEqual(rows['Anne Alpha']['commission'], Decimal('2500.00'))
        self.assertEqual(rows['Bob Beta']['commission'], Decimal('3000.00'))
        self.assertEqual(self.get().data['totals']['commission'], Decimal('5500.00'))

    def test_commission_arrondie_a_deux_decimales(self):
        self.inv(self.alice, '1001', '0', rate='0.25')  # 250,25
        self.assertEqual(self.get().data['results'][0]['commission'], Decimal('250.25'))

    def test_commission_zero_solde_cash_epargne(self):
        c = make_client(self.node, last_name='Gamma')
        self.inv(c, '4000', '4000', is_soldee=True, rate='0.25')   # solde : CM forcée à 0 même si taux 25
        self.inv(c, '2000', '2000', commission_exempt=True)
        self.inv(c, '0', '3000')                                    # épargne
        r = self.get().data['results'][0]
        self.assertEqual(r['commission'], Decimal('0.00'))
        self.assertEqual(r['order_value'], Decimal('6000.00'))
        self.assertEqual(r['paid'], Decimal('9000.00'))
        self.assertEqual(r['tours'], 3)
        self.assertEqual(r['sale_types'], ['SOLDE', 'CASH', 'EPARGNE'])

    def test_bp_before_est_la_premiere_facture_chronologique(self):
        # Créée dans le désordre : la livraison de 8h porte le BP avant du jour.
        self.inv(self.alice, '1000', '0', before='3000', hour=15)
        self.inv(self.alice, '2000', '0', before='1000', hour=8)
        r = self.get().data['results'][0]
        self.assertEqual(r['bp_before'], Decimal('1000.00'))
        self.assertEqual(r['bp_current'], Decimal('7000.00'))

    def test_bp_negatif_et_bp_current_reflete_la_fiche_client(self):
        self.inv(self.bob, '500', '0', before='-1500')
        self.bob.current_debt = Decimal('-1000')
        self.bob.save()
        r = self.get().data['results'][0]
        self.assertEqual(r['bp_before'], Decimal('-1500.00'))
        self.assertEqual(r['bp_current'], Decimal('-1000.00'))

    def test_types_de_vente_regulier_et_remboursement(self):
        self.inv(self.alice, '1000', '1000')
        self.inv(self.alice, '0', '500', before='7000', is_debt_repayment=True, rate='0.00')
        r = self.get().data['results'][0]
        self.assertEqual(r['sale_types'], ['REGULIER', 'REMBOURSEMENT'])
        self.assertEqual(r['tours'], 1)
        self.assertEqual(r['paid'], Decimal('1500.00'))
        self.assertEqual(r['order_value'], Decimal('1000.00'))
        self.assertEqual(r['commission'], Decimal('250.00'))

    def test_remboursement_seul_pas_un_tour(self):
        self.inv(self.alice, '0', '800', is_debt_repayment=True, rate='0.00')
        r = self.get()
        row = r.data['results'][0]
        self.assertEqual(row['tours'], 0)
        self.assertEqual(row['paid'], Decimal('800.00'))
        self.assertEqual(r.data['totals']['tours'], 0)
        self.assertEqual(r.data['totals']['paid'], Decimal('800.00'))

    def test_regularisation_et_mouvement_interne_sans_commission(self):
        self.inv(self.alice, '3000', '0', special_code='RG')
        self.inv(self.bob, '5000', '0', special_code='K2', rate='0.25')
        rows = {x['client_name']: x for x in self.get().data['results']}
        self.assertEqual(rows['Anne Alpha']['sale_types'], ['REGULARISATION'])
        self.assertEqual(rows['Anne Alpha']['commission'], Decimal('0.00'))
        self.assertEqual(rows['Bob Beta']['sale_types'], ['MOUVEMENT_INTERNE'])
        self.assertEqual(rows['Bob Beta']['commission'], Decimal('0.00'))

    def test_nv_traite_comme_vente_normale(self):
        self.inv(self.alice, '4000', '0', special_code='NV')
        r = self.get().data['results'][0]
        self.assertEqual(r['sale_types'], ['REGULIER'])
        self.assertEqual(r['commission'], Decimal('1000.00'))

    def test_not_served_et_ns_hors_totaux(self):
        self.inv(self.alice, '3000', '0')
        ns = self.inv(self.bob, '9999', '0', status=Invoice.Status.NOT_SERVED)
        Invoice.objects.filter(pk=ns.pk).update(not_served_at=_aware(D1, 11))
        self.inv(self.bob, '7777', '7777', status=Invoice.Status.PENDING, special_code='NS')
        self.inv(self.bob, '5555', '0', special_code='NS')  # NS livrée : exclue des servis
        r = self.get()
        self.assertEqual([x['client_name'] for x in r.data['results']], ['Anne Alpha'])
        t = r.data['totals']
        self.assertEqual((t['clients'], t['tours'], t['order_value'], t['paid']),
                         (1, 1, Decimal('3000.00'), Decimal('0.00')))
        self.assertEqual(r.data['non_servis']['count'], 3)
        self.assertEqual(r.data['non_servis']['results'][0]['count'], 3)

    def test_ns_annulee_non_comptee(self):
        self.inv(self.bob, '1000', '0', status=Invoice.Status.CANCELLED, special_code='NS')
        self.assertEqual(self.get().data['non_servis']['count'], 0)

    def test_non_servi_autre_jour_ou_autre_equipe(self):
        a = self.inv(self.bob, '0', '0', status=Invoice.Status.NOT_SERVED, team='A')
        Invoice.objects.filter(pk=a.pk).update(not_served_at=_aware(D1, 9))
        b = self.inv(self.alice, '0', '0', status=Invoice.Status.NOT_SERVED, team='B')
        Invoice.objects.filter(pk=b.pk).update(not_served_at=_aware(D1, 9))
        self.assertEqual(self.get(team='B').data['non_servis']['count'], 1)
        self.assertEqual(self.get(team='A').data['non_servis']['count'], 1)
        self.assertEqual(self.get(date=str(D2)).data['non_servis']['count'], 0)

    def test_client_de_passage_regroupe(self):
        self.inv(None, '1000', '1000')
        self.inv(None, '2000', '2000')
        r = self.get()
        self.assertEqual(len(r.data['results']), 1)
        row = r.data['results'][0]
        self.assertIsNone(row['client'])
        self.assertEqual(row['client_name'], 'Client de passage')
        self.assertEqual(row['client_code'], '')
        self.assertEqual(row['tours'], 2)
        self.assertEqual(row['order_value'], Decimal('3000.00'))
        self.assertIsNone(row['bp_current'])

    def test_tri_par_nom_puis_prenom(self):
        z = make_client(self.node, last_name='Alpha', first_name='Zed')
        for c in (self.bob, z, self.alice):
            self.inv(c, '100')
        self.assertEqual([x['client_name'] for x in self.get().data['results']],
                         ['Anne Alpha', 'Zed Alpha', 'Bob Beta'])

    def test_filtre_equipe_minuscule_et_totaux(self):
        self.inv(self.alice, '1000', team='A')
        self.inv(self.alice, '2000', team='B')
        r = self.get(team='b')
        self.assertEqual(r.data['team'], 'B')
        self.assertEqual(r.data['totals']['order_value'], Decimal('2000.00'))
        self.assertEqual(self.get().data['totals']['order_value'], Decimal('3000.00'))
        self.assertIsNone(self.get().data['team'])

    def test_jour_de_travail_frontiere_minuit(self):
        self.inv(self.alice, '100', delivered=_aware(D1, 23, 59))
        self.inv(self.bob, '200', delivered=_aware(D2, 0, 1))
        self.assertEqual([x['client_name'] for x in self.get().data['results']], ['Anne Alpha'])
        self.assertEqual([x['client_name'] for x in self.get(date=str(D2)).data['results']], ['Bob Beta'])

    def test_ajustement_exclu(self):
        self.inv(self.alice, '5000', is_adjustment=True)
        self.assertEqual(self.get().data['results'], [])

    def test_jour_vide(self):
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['totals'], {'clients': 0, 'tours': 0, 'order_value': Decimal('0.00'),
                                            'paid': Decimal('0.00'), 'commission': Decimal('0.00')})

    def test_pagination_bornes_et_plafond(self):
        for i in range(5):
            self.inv(make_client(self.node, last_name=f'P{i}'), '100')
        r = self.get(page=3, page_size=2)
        self.assertEqual(len(r.data['results']), 1)
        self.assertEqual(r.data['count'], 5)
        self.assertEqual(self.get(page=9, page_size=2).data['results'], [])
        self.assertEqual(self.get(page_size=99999).data['page_size'], 1000)
        for bad in ({'page': 0}, {'page_size': 0}, {'page': -1}, {'page': 'a'}, {'page_size': '1.5'}):
            r = self.get(**bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn('detail', r.data)

    def test_totaux_independants_de_la_page(self):
        for i in range(4):
            self.inv(make_client(self.node, last_name=f'Q{i}'), '250')
        full = self.get().data['totals']
        part = self.get(page_size=1).data['totals']
        self.assertEqual(full, part)
        self.assertEqual(full['order_value'], Decimal('1000.00'))

    def test_decimaux_serialises_en_nombres_precis(self):
        self.inv(self.alice, '1234.50', '0.10')
        r = self.get().data['results'][0]
        self.assertEqual(r['order_value'], Decimal('1234.50'))
        self.assertEqual(r['paid'], Decimal('0.10'))


class Bug327ErreursEtRolesTests(_Base):
    def test_erreurs_400_en_francais(self):
        for params in ({}, {'date': ''}, {'date': '2026-13-45'}, {'date': '31/10/2026'},
                       {'date': 'abc'}, {'date': str(D1), 'team': 'Z'}, {'date': str(D1), 'team': 'JOUR'}):
            r = self.api.get(URL, params)
            self.assertEqual(r.status_code, 400, params)
            self.assertIn('detail', r.data, params)
            self.assertTrue(any(w in r.data['detail'] for w in ('date', 'Date', 'Équipe')), r.data)

    def test_direction_node_manquant_ou_invalide(self):
        d = _api(make_user('DIRECTION', node=None))
        for params in ({'date': str(D1)}, {'date': str(D1), 'node': 'ZZ9'}):
            r = d.get(URL, params)
            self.assertEqual(r.status_code, 400, params)
            self.assertIn('detail', r.data)
        self.assertIn('introuvable', d.get(URL, {'date': str(D1), 'node': 'ZZ9'}).data['detail'])

    def test_roles(self):
        for role in ('GERANT', 'COMPTABLE', 'DIRECTION', 'ADMIN'):
            u = make_user(role, node=self.node if role == 'GERANT' else None)
            r = _api(u).get(URL, {'date': str(D1), 'node': 'K1'})
            self.assertEqual(r.status_code, 200, role)
        for role in ('FACTURIER', 'LIVREUR'):
            r = _api(make_user(role, node=self.node)).get(URL, {'date': str(D1), 'node': 'K1'})
            self.assertEqual(r.status_code, 403, role)

    def test_anonyme_401(self):
        self.assertEqual(APIClient().get(URL, {'date': str(D1)}).status_code, 401)

    def test_post_et_methodes_ecriture_refusees(self):
        self.assertEqual(self.api.post(URL, {'date': str(D1)}, format='json').status_code, 405)
        self.assertEqual(self.api.delete(URL).status_code, 405)

    def test_isolation_noeuds_et_node_force_ignore(self):
        kc = make_client(self.k2, last_name='Zeta', first_name='Zoe')
        self.inv(kc, '9000', '9000', node=self.k2)
        self.inv(self.alice, '1000')
        for node_param in ('K2', str(self.k2.pk)):
            r = self.get(node=node_param)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data['node'], 'K1')
            self.assertEqual([x['client_name'] for x in r.data['results']], ['Anne Alpha'])
            self.assertEqual(r.data['totals']['order_value'], Decimal('1000.00'))
        d = _api(make_user('DIRECTION', node=None))
        self.assertEqual([x['client_name'] for x in self.get(d, node='K2').data['results']], ['Zoe Zeta'])

    def test_client_d_un_autre_noeud_facture_chez_k1_apparait_chez_k1_seulement(self):
        # Un facturier peut facturer un client d'une autre boulangerie (5.1) :
        # la facture appartient à K1 (invoice.node), pas au nœud du client.
        kc = make_client(self.k2, last_name='Zeta', first_name='Zoe')
        self.inv(kc, '2000', '2000', node=self.node)
        self.assertEqual([x['client_name'] for x in self.get().data['results']], ['Zoe Zeta'])
        g2 = _api(make_user('GERANT', node=self.k2))
        self.assertEqual(g2.get(URL, {'date': str(D1)}).data['results'], [])


class Bug327PerformanceEtCoherenceTests(_Base):
    def _queries(self):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.get().status_code, 200)
        return len(ctx)

    def test_aucun_n_plus_un(self):
        self.inv(self.alice, '1000')
        self._queries()
        base = self._queries()
        for i in range(25):
            c = make_client(self.node, last_name=f'Perf{i:02d}')
            self.inv(c, '1000', '500', special_code='')
            self.inv(c, '0', '100', is_debt_repayment=True, rate='0.00')
            ns = self.inv(c, '0', '0', status=Invoice.Status.NOT_SERVED)
            Invoice.objects.filter(pk=ns.pk).update(not_served_at=_aware(D1, 9))
        self.assertEqual(self._queries(), base)

    def test_coherence_avec_daily_closure_ecart_facture(self):
        self.inv(self.alice, '10000', '4000')
        self.inv(self.alice, '6000', '6000', before='1000')
        self.inv(self.bob, '2000', '0', is_soldee=True, rate='0.00')
        self.inv(self.bob, '0', '3000')  # épargne
        self.inv(None, '500', '500')
        ns = self.inv(self.bob, '4000', '0', status=Invoice.Status.NOT_SERVED)
        Invoice.objects.filter(pk=ns.pk).update(not_served_at=_aware(D1, 9))
        cl = self.api.get(CLOSURE, {'node': 'K1', 'date': str(D1)})
        self.assertEqual(cl.status_code, 200, cl.data)
        t = self.get().data['totals']
        # ecart/facture du rapport = Σ commandé - Σ versé des factures livrées non NS.
        self.assertEqual(Decimal(cl.data['totals']['ecart_facture_fc']), t['order_value'] - t['paid'])
        self.assertEqual(t['order_value'], Decimal('18500.00'))
        self.assertEqual(t['paid'], Decimal('13500.00'))

    def test_coherence_commission_avec_daily_closure(self):
        self.inv(self.alice, '10000', '4000')
        self.inv(self.bob, '2000', '0', rate='0.30')
        cl = self.api.get(CLOSURE, {'node': 'K1', 'date': str(D1)})
        t = self.get().data['totals']
        # Le rapport l'agrège par catégorie de pain (lignes) ; sans lignes il vaut 0 :
        # on ne compare que si le rapport expose un total commission comparable.
        total = sum(Decimal(c['commission_jr']['fc']) for c in cl.data['categories'])
        if total:
            self.assertEqual(total, t['commission'])
        self.assertEqual(t['commission'], Decimal('3100.00'))
