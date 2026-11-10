"""
BUG-118 (docs/qa/REGISTRE_BUGS.md) : snapshot quotidien du stock de pains par
catégorie à la clôture d'une session de production — permet de répondre à
« quel était le stock de pains 500FC à la fin de la journée du 15 octobre à
K1 ? », ce qu'un simple solde courant (`BreadStock.qty_available`) ne permet
pas.

Extension BUG-118 (confirmée par le client le 2026-11-01) : dans le fichier
réel (`data_kiese/DOC 01- RAPPORT BOULANGERIES AOUT 2026.xlsx`, feuille
ZADIM), `RESTE DU HIER` dépend de l'ÉQUIPE (A/B, CLAUDE.md §5.2) qui a
clôturé en dernier — chaque équipe a SON propre solde déclaré, reporté
inchangé les jours où elle ne clôture pas. Le snapshot est donc désormais
tenu PAR ÉQUIPE : `reste_du_hier(nœud, catégorie, équipe T, jour N)` =
`−reste_du_jour` de l'équipe T au dernier jour où CETTE équipe a clôturé
avant N (pas forcément N-1), et 0 si l'équipe T n'a encore jamais clôturé
pour ce nœud/catégorie.

La quantité déclarée par équipe (`qty_at_close`) provient des dispositions
`BreadDisposal` de type `REMAINING` (« stock restant à vendre ») rattachées
à LA session qui clôture — ces dispositions ne touchent jamais
`BreadStock.qty_available` (solde physique global partagé par nœud+
catégorie, inchangé par cette extension).
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price, make_client
from production.models import ProductionSession, DailyBreadStockSnapshot, BreadStock, BreadDisposal


class DailyBreadStockSnapshotTests(TestCase):
    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.user = make_user(role='GERANT', node=self.node)
        self.bp = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def _declare_and_close(self, qty, date, team='A', remaining=None):
        """
        Déclare une session produisant `qty` pains de `self.bp`, enregistre
        (optionnellement) une disposition REMAINING de `remaining` pains
        (le solde que l'équipe déclare restant à vendre), puis clôture.
        Par défaut `remaining=qty` (rien n'a été vendu/disposé — toute la
        production reste en stock déclaré par cette équipe).
        """
        if remaining is None:
            remaining = qty
        resp = self.client_api.post('/api/production/sessions/', {
            'team': team, 'date': date, 'flour_sacks_used': '1.00',
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        session_id = resp.data['id']

        if remaining:
            disp_resp = self.client_api.post('/api/production/disposals/', {
                'session': session_id, 'bread_price': self.bp.pk,
                'disposal_type': 'REMAINING', 'quantity': remaining,
            }, format='json')
            self.assertEqual(disp_resp.status_code, 201, disp_resp.data)

        close_resp = self.client_api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(close_resp.status_code, 200, close_resp.data)
        return session_id

    def test_close_creates_snapshot_matching_declared_remaining(self):
        """La clôture d'une fournée crée un snapshot par équipe égal au
        solde déclaré (REMAINING) par cette équipe, pas au solde physique
        global `BreadStock.qty_available`."""
        self._declare_and_close(qty=200, date='2026-10-10', team='A')

        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, 200)  # stock physique global inchangé

        snapshot = DailyBreadStockSnapshot.objects.get(
            node=self.node, bread_price=self.bp, date='2026-10-10', team='A',
        )
        self.assertEqual(snapshot.qty_at_close, 200)
        self.assertEqual(
            DailyBreadStockSnapshot.reste_du_jour(self.node, self.bp, '2026-10-10', team='A'),
            200,
        )

    def test_second_closure_same_day_keeps_separate_team_snapshots(self):
        """Deux clôtures le même jour (équipe A puis équipe B) : chaque
        équipe garde SON propre snapshot déclaré, aucun upsert ne doit
        écraser l'autre équipe."""
        self._declare_and_close(qty=100, date='2026-10-10', team='A')
        self._declare_and_close(qty=50, date='2026-10-10', team='B')

        snap_a = DailyBreadStockSnapshot.objects.get(
            node=self.node, bread_price=self.bp, date='2026-10-10', team='A',
        )
        snap_b = DailyBreadStockSnapshot.objects.get(
            node=self.node, bread_price=self.bp, date='2026-10-10', team='B',
        )
        self.assertEqual(snap_a.qty_at_close, 100)
        self.assertEqual(snap_b.qty_at_close, 50)
        self.assertEqual(
            DailyBreadStockSnapshot.objects.filter(
                node=self.node, bread_price=self.bp, date='2026-10-10',
            ).count(),
            2,
        )
        # Le stock physique global, lui, est bien la somme des deux équipes.
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, 150)

    def test_reste_du_hier_is_negative_of_previous_snapshot_same_team(self):
        """reste_du_hier(jour N, équipe T) = −reste_du_jour(jour N-1, équipe
        T) lorsqu'un snapshot de CETTE équipe existe pour la veille."""
        self._declare_and_close(qty=200, date='2026-10-10', team='A')
        self._declare_and_close(qty=80, date='2026-10-11', team='A')

        self.assertEqual(
            DailyBreadStockSnapshot.reste_du_jour(self.node, self.bp, '2026-10-10', team='A'),
            200,
        )
        self.assertEqual(
            DailyBreadStockSnapshot.reste_du_jour(self.node, self.bp, '2026-10-11', team='A'),
            80,
        )
        self.assertEqual(
            DailyBreadStockSnapshot.reste_du_hier(self.node, self.bp, '2026-10-11', team='A'),
            -200,
        )

    def test_reste_du_hier_is_zero_on_first_day_of_activity(self):
        """Première journée d'activité de cette équipe pour cette
        catégorie : aucun snapshot antérieur, reste_du_hier = 0."""
        self._declare_and_close(qty=50, date='2026-10-10', team='A')

        self.assertEqual(
            DailyBreadStockSnapshot.reste_du_hier(self.node, self.bp, '2026-10-10', team='A'),
            0,
        )

    def test_reste_du_hier_skips_days_with_no_closure_for_that_team(self):
        """Si l'équipe B n'a pas clôturé le 11 ni le 12, le reste_du_hier du
        12 pour B doit se référer à son dernier snapshot disponible (le
        10), pas à un jour calendaire fixe ni à l'équipe A."""
        self._declare_and_close(qty=200, date='2026-10-10', team='A')
        self._declare_and_close(qty=30, date='2026-10-10', team='B')
        # Jour 11 : seule l'équipe A clôture. B ne clôture ni le 11 ni le 12.
        self._declare_and_close(qty=80, date='2026-10-11', team='A')

        self.assertEqual(
            DailyBreadStockSnapshot.reste_du_hier(self.node, self.bp, '2026-10-12', team='B'),
            -30,
        )
        # Pour A, en revanche, le dernier jour clôturé avant le 12 est le 11.
        self.assertEqual(
            DailyBreadStockSnapshot.reste_du_hier(self.node, self.bp, '2026-10-12', team='A'),
            -80,
        )

    def test_reste_du_jour_is_none_when_not_yet_closed(self):
        """Pas de session clôturée par cette équipe pour cette date : pas de
        valeur connue."""
        self.assertIsNone(
            DailyBreadStockSnapshot.reste_du_jour(self.node, self.bp, '2026-10-10', team='A')
        )

    def test_remaining_disposal_never_adjusts_global_bread_stock(self):
        """Une disposition REMAINING déclarée par une équipe ne doit jamais
        décrémenter `BreadStock.qty_available` (elle reste en stock,
        report à la fournée suivante) — seule la donnée déclarative par
        équipe change."""
        self._declare_and_close(qty=100, date='2026-10-10', team='A', remaining=60)

        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp)
        self.assertEqual(stock.qty_available, 100)  # pas 60 : REMAINING ne décrémente pas

        snapshot = DailyBreadStockSnapshot.objects.get(
            node=self.node, bread_price=self.bp, date='2026-10-10', team='A',
        )
        self.assertEqual(snapshot.qty_at_close, 60)


class CloseWithRemainingBodyTests(TestCase):
    """
    BUG-152 (remarque.md, après l.408) : le « RESTE DU JOUR » par catégorie
    peut désormais être déclaré EN MÊME TEMPS que l'appel à `close()`, via
    `{"remaining": [{"bread_price": <id>, "quantity": <int>}, ...]}`, sans
    passer par le formulaire séparé `BreadDisposalViewSet` au préalable.
    """

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.user = make_user(role='GERANT', node=self.node)
        self.bp1 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.bp2 = make_bread_price(category='GRAND', label='Pain 1000 FC', unit_price=1000)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def _create_session(self, date='2026-11-10', team='A'):
        resp = self.client_api.post('/api/production/sessions/', {
            'team': team, 'date': date, 'flour_sacks_used': '2.00',
            'lines': [
                {'bread_price': self.bp1.pk, 'quantity': 100},
                {'bread_price': self.bp2.pk, 'quantity': 50},
            ],
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data['id']

    def test_close_with_remaining_body_creates_per_category_snapshot_without_predeclared_disposal(self):
        """Aucune disposition REMAINING pré-déclarée séparément : la clôture
        avec `remaining` dans le corps doit, à elle seule, produire le bon
        snapshot par catégorie."""
        session_id = self._create_session()
        self.assertEqual(BreadDisposal.objects.filter(session_id=session_id).count(), 0)

        resp = self.client_api.post(
            f'/api/production/sessions/{session_id}/close/',
            {'remaining': [
                {'bread_price': self.bp1.pk, 'quantity': 30},
                {'bread_price': self.bp2.pk, 'quantity': 0},
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        snap1 = DailyBreadStockSnapshot.objects.get(
            node=self.node, bread_price=self.bp1, date='2026-11-10', team='A',
        )
        snap2 = DailyBreadStockSnapshot.objects.get(
            node=self.node, bread_price=self.bp2, date='2026-11-10', team='A',
        )
        self.assertEqual(snap1.qty_at_close, 30)
        self.assertEqual(snap2.qty_at_close, 0)

        # Les BreadDisposal REMAINING ont bien été créés par close(), pas par
        # un passage préalable par le formulaire séparé.
        self.assertEqual(
            BreadDisposal.objects.filter(
                session_id=session_id, disposal_type=BreadDisposal.DisposalType.REMAINING,
            ).count(),
            2,
        )
        # Le stock physique global n'est jamais affecté par REMAINING.
        stock1 = BreadStock.objects.get(node=self.node, bread_price=self.bp1)
        self.assertEqual(stock1.qty_available, 100)

    def test_close_with_remaining_is_idempotent_and_overrides_predeclared_disposal(self):
        """Si une ligne REMAINING existait déjà (déclarée séparément au
        préalable) pour une catégorie, la valeur fournie dans `remaining`
        à la clôture la remplace proprement (pas de doublon, pas de somme)."""
        session_id = self._create_session()
        pre_resp = self.client_api.post('/api/production/disposals/', {
            'session': session_id, 'bread_price': self.bp1.pk,
            'disposal_type': 'REMAINING', 'quantity': 999,
        }, format='json')
        self.assertEqual(pre_resp.status_code, 201, pre_resp.data)

        resp = self.client_api.post(
            f'/api/production/sessions/{session_id}/close/',
            {'remaining': [{'bread_price': self.bp1.pk, 'quantity': 40}]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        self.assertEqual(
            BreadDisposal.objects.filter(
                session_id=session_id, bread_price=self.bp1,
                disposal_type=BreadDisposal.DisposalType.REMAINING,
            ).count(),
            1,
        )
        snap1 = DailyBreadStockSnapshot.objects.get(
            node=self.node, bread_price=self.bp1, date='2026-11-10', team='A',
        )
        self.assertEqual(snap1.qty_at_close, 40)

    def test_close_with_negative_remaining_quantity_rejected_and_nothing_applied(self):
        """Une quantité négative dans `remaining` → 400, aucune disposition
        créée, session non clôturée."""
        session_id = self._create_session()

        resp = self.client_api.post(
            f'/api/production/sessions/{session_id}/close/',
            {'remaining': [
                {'bread_price': self.bp1.pk, 'quantity': 10},
                {'bread_price': self.bp2.pk, 'quantity': -5},
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.data)

        session = ProductionSession.objects.get(pk=session_id)
        self.assertFalse(session.is_closed)
        self.assertEqual(BreadDisposal.objects.filter(session_id=session_id).count(), 0)
        self.assertFalse(
            DailyBreadStockSnapshot.objects.filter(node=self.node, bread_price=self.bp1).exists()
        )

    def test_close_without_remaining_body_is_unchanged(self):
        """Non-régression BUG-118 : corps vide (comportement historique),
        avec une disposition REMAINING pré-déclarée séparément."""
        session_id = self._create_session()
        disp_resp = self.client_api.post('/api/production/disposals/', {
            'session': session_id, 'bread_price': self.bp1.pk,
            'disposal_type': 'REMAINING', 'quantity': 70,
        }, format='json')
        self.assertEqual(disp_resp.status_code, 201, disp_resp.data)

        resp = self.client_api.post(f'/api/production/sessions/{session_id}/close/')
        self.assertEqual(resp.status_code, 200, resp.data)

        snap1 = DailyBreadStockSnapshot.objects.get(
            node=self.node, bread_price=self.bp1, date='2026-11-10', team='A',
        )
        self.assertEqual(snap1.qty_at_close, 70)
        # bp2 n'a jamais eu de REMAINING déclaré : considéré écoulé (0).
        snap2 = DailyBreadStockSnapshot.objects.get(
            node=self.node, bread_price=self.bp2, date='2026-11-10', team='A',
        )
        self.assertEqual(snap2.qty_at_close, 0)

    def test_remaining_breads_do_not_affect_closure_summary_gap(self):
        """Les lignes REMAINING créées via `remaining` à la clôture ne
        doivent jamais être comptées comme des « retours »/dispositions dans
        le recoupement agrégé (`closure_summary['returns']`,
        `reliquat_breads`/`nv_breads`) : `_build_reconciliation_querysets`
        exclut explicitement REMAINING, et le calcul d'écart est fait AVANT
        la création de ces lignes dans `close()`."""
        session_id = self._create_session()  # 100 + 50 = 150 pains produits, rien vendu/disposé

        resp = self.client_api.post(
            f'/api/production/sessions/{session_id}/close/',
            {'remaining': [
                {'bread_price': self.bp1.pk, 'quantity': 100},
                {'bread_price': self.bp2.pk, 'quantity': 50},
            ]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        summary = resp.data['closure_summary']
        # returns (hors REMAINING) doit rester 0 : les 150 pains REMAINING
        # créés par cet appel ne sont jamais comptés ici.
        self.assertEqual(summary['returns']['breads'], 0)
        # gap = produit(150) - (vendu(0) + retours(0)) = 150 -> tout est NV,
        # ce n'est pas une anomalie (gap positif).
        self.assertEqual(summary['gap']['breads'], 150)
        self.assertEqual(summary['nv']['breads'], 150)
        self.assertFalse(summary['anomaly'])
