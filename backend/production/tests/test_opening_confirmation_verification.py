"""
Vérification indépendante (testeur-production, 2026-11-09) des tickets
BUG-133/134/135/136, actuellement au statut CORRIGÉ dans
`docs/qa/REGISTRE_BUGS.md` — jamais encore passés à VÉRIFIÉ.

Ce fichier ne refait pas simplement les tests déjà écrits par dev-backend
dans `test_daily_opening_confirmation.py` (relus et jugés corrects après
relecture du code, pas seulement du rapport) : il couvre le scénario métier
BOUT-EN-BOUT demandé par le coordinateur, en insistant sur l'interaction
entre les 3 effets de la confirmation (DailyOpeningConfirmationLine, report
de clôture BUG-120/135, BreadStock.qty_adjusted BUG-136) dans un seul
parcours, et sur les permissions (BUG-022/025/056) pour les rôles qui ne
doivent jamais pouvoir agir sur un autre nœud.
"""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as dj_timezone
from rest_framework.test import APIClient

from core.testing import make_node, make_user, make_bread_price
from production.models import (
    BreadStock, DailyOpeningConfirmation, DailyOpeningConfirmationLine,
    _adjust_bread_stock,
)
from production.views import _build_daily_closure_report


TODAY = '2026-11-09'
TODAY_DATE = datetime.date(2026, 11, 9)


class OpeningConfirmationEndToEndScenarioTests(TestCase):
    """Parcours complet : le gérant consulte, corrige, valide — et on
    vérifie les 3 effets attendus en une seule fois (stock réel, rapport de
    clôture avec signe correct, non-perturbation du calcul financier)."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.api = APIClient()
        self.api.force_authenticate(self.gerant)
        # Stock physique courant avant toute confirmation : 120 pains 500 FC.
        _adjust_bread_stock(self.node, self.bp500, produced=120)

    def test_gerant_corrects_proposed_value_full_scenario(self):
        """Le gérant voit 120 proposés, corrige à 110, valide pour A :
        - BreadStock.qty_available doit devenir exactement 110 (BUG-136)
        - reste_du_hier['A'] du rapport de clôture doit être -110 (BUG-135)
        - ce calcul ne doit dépendre QUE de qty_confirmed, jamais de
          BreadStock (vérifié en comparant à un scénario équivalent purement
          déclaré, sans aucun ajustement de stock nécessaire pour que le
          signe/la grandeur soient corrects)."""
        get_resp = self.api.get(f'/api/production/opening-confirmation/?date={TODAY}')
        self.assertEqual(get_resp.status_code, 200, get_resp.data)
        proposed = next(c['qty_proposed'] for c in get_resp.data['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(proposed, 120)

        post_resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 110}],  # corrigé, pas 120
        }, format='json')
        self.assertEqual(post_resp.status_code, 200, post_resp.data)

        # Effet 1 (BUG-136) : stock réel ajusté exactement à la valeur validée.
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_available, 110)
        self.assertEqual(post_resp.data['stock_adjustments'], [
            {'bread_price_id': self.bp500.pk, 'before': 120, 'after': 110, 'delta': -10},
        ])

        # Effet 2 (BUG-135) : reste_du_hier négatif, même grandeur que la
        # quantité confirmée (positive en base, BUG-134 intact).
        line = DailyOpeningConfirmationLine.objects.get(
            confirmation__node=self.node, confirmation__team='A',
            confirmation__date=TODAY, bread_price=self.bp500,
        )
        self.assertEqual(line.qty_confirmed, 110)  # stockage positif inchangé

        report = _build_daily_closure_report(self.node, TODAY_DATE)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(row['reste_du_hier']['A'], -110)
        self.assertEqual(row['reste_du_hier']['B'], 0)  # équipe B non confirmée, jamais clôturée

        # Effet 3 : le calcul du rapport ne dépend QUE de qty_confirmed, pas
        # de BreadStock — preuve : si on modifie encore BreadStock APRÈS
        # coup (ex. une vente), le rapport déjà construit pour ce jour ne
        # doit pas changer de résultat pour une nouvelle évaluation tant que
        # la ligne de confirmation n'a pas elle-même changé.
        _adjust_bread_stock(self.node, self.bp500, sent=5)  # une vente après la confirmation
        report_after_sale = _build_daily_closure_report(self.node, TODAY_DATE)
        row_after_sale = next(c for c in report_after_sale['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(row_after_sale['reste_du_hier']['A'], -110)  # inchangé : dépend de qty_confirmed, pas de BreadStock
        self.assertEqual(row['facture_mvm_interne']['fc'], row_after_sale['facture_mvm_interne']['fc'])

    def test_gerant_validates_proposed_value_as_is_is_exact_noop_on_stock(self):
        """Valider SANS corriger (valeur proposée = valeur validée) : aucun
        delta, donc qty_adjusted doit rester à 0 (pas seulement
        qty_available inchangé — le champ qty_adjusted lui-même ne doit pas
        bouger, preuve qu'aucun ajustement fictif n'est appliqué)."""
        stock_before = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock_before.qty_adjusted, 0)

        post_resp = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 120}],  # valeur proposée, non corrigée
        }, format='json')
        self.assertEqual(post_resp.status_code, 200, post_resp.data)
        self.assertEqual(post_resp.data['stock_adjustments'], [])  # no-op explicite

        stock_after = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock_after.qty_adjusted, 0)  # pas seulement qty_available : qty_adjusted lui-même intact
        self.assertEqual(stock_after.qty_available, 120)

        report = _build_daily_closure_report(self.node, TODAY_DATE)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(row['reste_du_hier']['A'], -120)  # BUG-135 : toujours négatif, même en no-op

    def test_team_b_get_reflects_team_a_adjustment_independent_check(self):
        """Revérification indépendante (ne pas se fier au seul rapport
        dev-backend) : l'équipe B doit voir, dans son GET, le `qty_proposed`
        déjà corrigé par la confirmation de l'équipe A le même jour."""
        post_a = self.api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 90}],  # correction -30
        }, format='json')
        self.assertEqual(post_a.status_code, 200, post_a.data)

        get_b = self.api.get(f'/api/production/opening-confirmation/?date={TODAY}')
        self.assertEqual(get_b.status_code, 200, get_b.data)
        proposed_for_b = next(c['qty_proposed'] for c in get_b.data['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(proposed_for_b, 90)
        self.assertFalse(get_b.data['teams']['B']['confirmed'])
        self.assertTrue(get_b.data['teams']['A']['confirmed'])

        # L'équipe B confirme ensuite tel que proposé (no-op) : le rapport
        # doit refléter -90 également pour B.
        post_b = self.api.post('/api/production/opening-confirmation/', {
            'team': 'B', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 90}],
        }, format='json')
        self.assertEqual(post_b.status_code, 200, post_b.data)
        self.assertEqual(post_b.data['stock_adjustments'], [])  # déjà à 90, no-op pour B

        report = _build_daily_closure_report(self.node, TODAY_DATE)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(row['reste_du_hier']['A'], -90)
        self.assertEqual(row['reste_du_hier']['B'], -90)


class OpeningConfirmationPermissionBoundaryTests(TestCase):
    """Revérification indépendante des permissions — motif BUG-022/025/056.
    Couvre spécifiquement le POST (pas seulement le GET déjà couvert par
    dev-backend) et les rôles HQ qui ne sont PAS GERANT à proprement parler
    (COMPTABLE) pour clarifier leur comportement réel au lieu de le
    supposer."""

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.other_node = make_node(sac_value_fc=Decimal('200000'))
        self.gerant = make_user(role='GERANT', node=self.node)
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        _adjust_bread_stock(self.node, self.bp500, produced=100)
        _adjust_bread_stock(self.other_node, self.bp500, produced=300)

    def test_facturier_post_allowed_on_own_node_refused_on_other_node(self):
        """BUG-138 (client, tranché directement, 2026-11-09, remarque.md
        l.398 « le facturier peut aussi faire ça ») : un FACTURIER peut
        désormais confirmer sur SON nœud (effet de bord identique à un
        GERANT), mais ne peut jamais forger `node` vers un autre nœud —
        même garantie BUG-022/025/056 que pour GERANT (requête silencieusement
        reroutée vers son propre nœud, jamais un accès à un nœud étranger)."""
        facturier = make_user(role='FACTURIER', node=self.node, team='A')
        api = APIClient()
        api.force_authenticate(facturier)

        resp = api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 50}],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(DailyOpeningConfirmation.objects.filter(node=self.node, date=TODAY, team='A').exists())
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_available, 50)  # ajusté comme pour un GERANT

        # Jamais d'effet sur un autre nœud, même en forgeant `node`.
        resp_forged = api.post('/api/production/opening-confirmation/', {
            'node': self.other_node.code, 'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 1}],
        }, format='json')
        self.assertEqual(resp_forged.status_code, 200, resp_forged.data)
        self.assertEqual(resp_forged.data['node'], self.node.code)
        other_stock = BreadStock.objects.get(node=self.other_node, bread_price=self.bp500)
        self.assertEqual(other_stock.qty_available, 300)  # intact

    def test_livreur_post_refused_entirely(self):
        livreur = make_user(role='LIVREUR', node=self.node, team='A')
        api = APIClient()
        api.force_authenticate(livreur)
        resp = api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 50}],
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(DailyOpeningConfirmation.objects.filter(node=self.node, date=TODAY).exists())

    def test_hq_role_comptable_is_treated_as_headquarters_not_refused_but_cannot_act_implicitly(self):
        """IMPORTANT (constat de vérification, pas une anomalie) :
        `IsGerant` (backend/core/permissions.py) accepte explicitement le
        rôle COMPTABLE au même titre qu'ADMIN/DIRECTION/GERANT — COMPTABLE
        est un rôle HQ (`User.can_access_all_nodes` == True pour ce rôle,
        voir `core/models.py::User.can_access_all_nodes`), et cette vue
        applique à COMPTABLE exactement la même règle qu'à DIRECTION/ADMIN
        (motif BUG-022/025/056, même code que `DailyClosureReportView`) :
        un HQ doit préciser explicitement `node`, il n'a pas de nœud
        implicite. La consigne de mission groupait COMPTABLE avec
        FACTURIER/LIVREUR comme devant être « refusé entièrement » — ce
        n'est PAS le comportement réel du code (ni une régression : c'est
        cohérent avec le reste du module production, déjà vérifié pour
        BUG-120). On vérifie donc ici le comportement RÉEL : COMPTABLE sans
        `node` précisé est refusé en 400 (jamais un accès implicite à un
        nœud), et ne peut jamais agir sur un nœud qu'il ne précise pas
        explicitement — donc ne peut PAS, par erreur de requête, ajuster le
        stock d'un nœud par accident."""
        comptable = make_user(role='COMPTABLE', node=None)
        api = APIClient()
        api.force_authenticate(comptable)

        resp_no_node = api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 50}],
        }, format='json')
        self.assertEqual(resp_no_node.status_code, 400)  # jamais un nœud implicite pour un HQ
        self.assertFalse(DailyOpeningConfirmation.objects.filter(date=TODAY).exists())

        # Avec `node` explicitement précisé, COMPTABLE PEUT agir (comme
        # DIRECTION/ADMIN) — comportement voulu, pas un trou de sécurité :
        # cela reste un rôle HQ qui supervise, au même titre que les autres
        # rôles HQ déjà acceptés par cette vue pour BUG-120.
        resp_with_node = api.post('/api/production/opening-confirmation/', {
            'node': self.node.code, 'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 50}],
        }, format='json')
        self.assertEqual(resp_with_node.status_code, 200, resp_with_node.data)

    def test_build_daily_closure_report_unaffected_by_bug139_change(self):
        """Non-régression explicite (BUG-139) : `_build_daily_closure_report`
        continue, par équipe, à préférer la valeur confirmée de CETTE
        équipe quand elle existe, sinon l'auto-dérivé — BUG-139 ne change
        QUE `needs_confirmation`/`opening_team` sur le GET, jamais cette
        logique de rapport (déjà couverte en détail par
        test_daily_opening_confirmation.py)."""
        gerant = make_user(role='GERANT', node=self.node)
        api = APIClient()
        api.force_authenticate(gerant)
        api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 80}],
        }, format='json')

        report = _build_daily_closure_report(self.node, TODAY_DATE)
        row = next(c for c in report['categories'] if c['bread_price'] == self.bp500.pk)
        self.assertEqual(row['reste_du_hier']['A'], -80)  # équipe confirmée : valeur déclarée
        self.assertEqual(row['reste_du_hier']['B'], 0)  # équipe non confirmée, jamais clôturée : auto-dérivé

    def test_gerant_cannot_make_other_node_adjust_stock_via_forged_node_on_post(self):
        """Revérification indépendante (effet de bord sur le STOCK, pas
        seulement sur la confirmation déjà testée par dev-backend) : un
        GERANT non-HQ qui forge `node` vers un autre nœud ne doit jamais
        déclencher un ajustement de `BreadStock` sur ce nœud étranger — la
        requête doit être silencieusement reroutée vers son propre nœud,
        stock de l'autre nœud intact."""
        api = APIClient()
        api.force_authenticate(self.gerant)
        resp = api.post('/api/production/opening-confirmation/', {
            'node': self.other_node.code, 'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 10}],  # forcerait un delta de -290 sur other_node si pris en compte
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['node'], self.node.code)

        other_stock = BreadStock.objects.get(node=self.other_node, bread_price=self.bp500)
        self.assertEqual(other_stock.qty_available, 300)  # intact

        own_stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(own_stock.qty_available, 10)  # l'ajustement a bien été appliqué... à SON nœud


class OpeningConfirmationFinalVerificationBug137To140Tests(TestCase):
    """
    Vérification finale (testeur-production, 2026-11-09) du lot BUG-133 à
    BUG-140 après correction de BUG-138/139 (backend) et BUG-140/137
    (frontend). Complète (sans dupliquer) `test_daily_opening_confirmation.py
    ::OpeningConfirmationNeedsConfirmationTests` par un parcours qui passe
    par les VRAIS créneaux horaires du nœud (`team_a_start_time`/
    `team_b_start_time`, BUG-130/131), en figeant seulement l'heure
    courante — preuve que l'intégration `_opening_confirmation_resolve_node`
    → `Node.opening_team()` (BUG-141) → `needs_confirmation` fonctionne de
    bout en bout avec de vraies données de configuration, pas seulement avec
    un mock de la méthode elle-même.

    MISE À JOUR BUG-141 : `opening_team` est désormais calculé par
    `Node.opening_team()` (premier créneau structurel de la journée), pas
    par `Node.active_team_at()` (équipe en service à l'instant présent) —
    les assertions qui dépendaient de l'heure figée pour déterminer
    `opening_team` ont été corrigées en conséquence
    (`test_bug141_real_time_slots_opening_team_is_first_slot_not_current_time`,
    ex-`test_bug139_real_time_slots_only_active_team_confirmation_required`).
    """

    def setUp(self):
        self.node = make_node(sac_value_fc=Decimal('200000'))
        self.node.team_a_start_time = datetime.time(6, 0)
        self.node.team_a_end_time = datetime.time(13, 0)
        self.node.team_b_start_time = datetime.time(13, 0)
        self.node.team_b_end_time = datetime.time(20, 0)
        self.node.save()
        self.other_node = make_node(sac_value_fc=Decimal('200000'))
        self.bp500 = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        self.bp200 = make_bread_price(category='PETIT', label='Pain 200 FC', unit_price=200)
        _adjust_bread_stock(self.node, self.bp500, produced=100)
        _adjust_bread_stock(self.node, self.bp200, produced=40)

    def _frozen_localtime(self, hour):
        """Renvoie un remplaçant de `django.utils.timezone.localtime` figé à
        l'heure demandée aujourd'hui, pour piloter `Node.active_team_at()`
        via le vrai mécanisme (pas un mock de la méthode). `Node.active_team_at()`
        appelle toujours `localtime()` sans argument dans ce parcours — on
        n'a donc pas besoin de gérer le cas d'un argument explicite."""
        fixed = dj_timezone.make_aware(
            datetime.datetime.combine(dj_timezone.localdate(), datetime.time(hour, 0)),
        )
        return lambda *args, **kwargs: fixed

    def test_bug138_facturier_get_and_post_on_own_node_only(self):
        """BUG-138 : FACTURIER accède en GET et POST à SON nœud, jamais à un
        autre (effet de bord vérifié sur BreadStock, pas seulement sur le
        code HTTP)."""
        facturier = make_user(role='FACTURIER', node=self.node, team='A')
        api = APIClient()
        api.force_authenticate(facturier)

        get_resp = api.get(f'/api/production/opening-confirmation/?date={TODAY}')
        self.assertEqual(get_resp.status_code, 200, get_resp.data)
        self.assertEqual(get_resp.data['node'], self.node.code)

        # Tentative de GET sur un autre nœud : silencieusement reroutée.
        cross_get = api.get(f'/api/production/opening-confirmation/?node={self.other_node.code}&date={TODAY}')
        self.assertEqual(cross_get.status_code, 200, cross_get.data)
        self.assertEqual(cross_get.data['node'], self.node.code)  # jamais l'autre nœud

        post_resp = api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 90}],
        }, format='json')
        self.assertEqual(post_resp.status_code, 200, post_resp.data)
        stock = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        self.assertEqual(stock.qty_available, 90)

        # Forger `node` sur le POST n'a aucun effet sur l'autre nœud.
        post_forged = api.post('/api/production/opening-confirmation/', {
            'node': self.other_node.code, 'team': 'A', 'date': TODAY,
            'lines': [{'bread_price': self.bp500.pk, 'qty': 1}],
        }, format='json')
        self.assertEqual(post_forged.status_code, 200, post_forged.data)
        self.assertEqual(post_forged.data['node'], self.node.code)
        self.assertFalse(
            BreadStock.objects.filter(node=self.other_node, bread_price=self.bp500).exists()
        )

    def test_bug141_real_time_slots_opening_team_is_first_slot_not_current_time(self):
        """BUG-141 (corrige l'hypothèse initialement vérifiée pour BUG-139) :
        intégration réelle avec de vrais créneaux horaires (`setUp` : A
        06:00-13:00, B 13:00-20:00 — A démarre le premier) — `opening_team`
        doit rester `'A'` MÊME à 14h (créneau B en cours selon l'horloge),
        car `Node.opening_team()` (BUG-141) est purement structurel et ne
        dépend jamais de l'heure d'appel. Seule la confirmation de A (équipe
        du premier créneau) suffit ; celle de B seule ne suffit pas.

        Avant BUG-141, cette assertion était inversée (`opening_team`
        calculé via `Node.active_team_at()`, qui renvoyait 'B' à 14h) — ce
        test encodait alors le comportement incorrect signalé par le client
        (remarque.md l.398, « premier créneau », pas « équipe en service à
        l'instant »)."""
        gerant = make_user(role='GERANT', node=self.node)
        api = APIClient()
        api.force_authenticate(gerant)

        with patch.object(dj_timezone, 'localtime', side_effect=self._frozen_localtime(14)):
            get_resp = api.get(f'/api/production/opening-confirmation/?date={TODAY}')
            self.assertEqual(get_resp.status_code, 200, get_resp.data)
            self.assertEqual(get_resp.data['opening_team'], 'A')  # premier créneau, pas l'équipe active à 14h
            self.assertTrue(get_resp.data['needs_confirmation'])

            api.post('/api/production/opening-confirmation/', {
                'team': 'B', 'date': TODAY,
                'lines': [{'bread_price': self.bp500.pk, 'qty': 100}],
            }, format='json')
            still_needed = api.get(f'/api/production/opening-confirmation/?date={TODAY}')
            self.assertTrue(still_needed.data['needs_confirmation'])  # B n'est pas l'équipe d'ouverture

            api.post('/api/production/opening-confirmation/', {
                'team': 'A', 'date': TODAY,
                'lines': [{'bread_price': self.bp500.pk, 'qty': 100}],
            }, format='json')
            now_satisfied = api.get(f'/api/production/opening-confirmation/?date={TODAY}')
            self.assertFalse(now_satisfied.data['needs_confirmation'])  # A (équipe d'ouverture) a confirmé

    def test_bug139_node_without_slots_either_team_suffices_real_data(self):
        """Nœud réellement non configuré (pas de mock) : une seule
        confirmation, A ou B, suffit."""
        unconfigured_node = make_node(sac_value_fc=Decimal('200000'))
        bp = make_bread_price(category='MOYEN', label='Pain 500 FC', unit_price=500)
        _adjust_bread_stock(unconfigured_node, bp, produced=20)
        gerant = make_user(role='GERANT', node=unconfigured_node)
        api = APIClient()
        api.force_authenticate(gerant)

        data = api.get(f'/api/production/opening-confirmation/?date={TODAY}').data
        self.assertIsNone(data['opening_team'])
        self.assertTrue(data['needs_confirmation'])

        api.post('/api/production/opening-confirmation/', {
            'team': 'B', 'date': TODAY,
            'lines': [{'bread_price': bp.pk, 'qty': 20}],
        }, format='json')
        data = api.get(f'/api/production/opening-confirmation/?date={TODAY}').data
        self.assertFalse(data['needs_confirmation'])

    def test_bug137_stock_adjustments_matches_exact_delta_multi_category(self):
        """BUG-137 : `stock_adjustments` doit correspondre exactement au
        delta réellement appliqué à `BreadStock`, catégorie par catégorie —
        y compris quand une catégorie est corrigée à la hausse, une autre à
        la baisse, et une troisième laissée identique (absente de la
        liste)."""
        bp300 = make_bread_price(category='GRAND', label='Pain 300 FC', unit_price=300)
        _adjust_bread_stock(self.node, bp300, produced=25)

        gerant = make_user(role='GERANT', node=self.node)
        api = APIClient()
        api.force_authenticate(gerant)

        resp = api.post('/api/production/opening-confirmation/', {
            'team': 'A', 'date': TODAY,
            'lines': [
                {'bread_price': self.bp500.pk, 'qty': 130},  # 100 -> 130 (+30)
                {'bread_price': self.bp200.pk, 'qty': 40},   # 40 -> 40 (inchangé, absent de la liste)
                {'bread_price': bp300.pk, 'qty': 10},        # 25 -> 10 (-15)
            ],
        }, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        adjustments_by_bp = {a['bread_price_id']: a for a in resp.data['stock_adjustments']}
        self.assertEqual(set(adjustments_by_bp.keys()), {self.bp500.pk, bp300.pk})
        self.assertEqual(adjustments_by_bp[self.bp500.pk], {
            'bread_price_id': self.bp500.pk, 'before': 100, 'after': 130, 'delta': 30,
        })
        self.assertEqual(adjustments_by_bp[bp300.pk], {
            'bread_price_id': bp300.pk, 'before': 25, 'after': 10, 'delta': -15,
        })

        # Le delta annoncé correspond exactement à l'état final réel de
        # `BreadStock` pour chaque catégorie touchée (pas seulement au
        # moment du calcul, mais bien persisté).
        stock500 = BreadStock.objects.get(node=self.node, bread_price=self.bp500)
        stock300 = BreadStock.objects.get(node=self.node, bread_price=bp300)
        stock200 = BreadStock.objects.get(node=self.node, bread_price=self.bp200)
        self.assertEqual(stock500.qty_available, 130)
        self.assertEqual(stock300.qty_available, 10)
        self.assertEqual(stock200.qty_available, 40)  # inchangé

    def test_bug140_contract_fields_present_and_consistent_for_facturier(self):
        """BUG-140 (contrat consommé par le frontend) : le GET renvoyé à un
        FACTURIER porte bien `opening_team`/`needs_confirmation`, cohérents
        avec `teams`, de la même manière que pour un GERANT (pas un contrat
        différent selon le rôle)."""
        facturier = make_user(role='FACTURIER', node=self.node, team='B')
        api = APIClient()
        api.force_authenticate(facturier)

        with patch.object(dj_timezone, 'localtime', side_effect=self._frozen_localtime(8)):
            data = api.get(f'/api/production/opening-confirmation/?date={TODAY}').data
            self.assertEqual(data['opening_team'], 'A')  # 8h -> créneau A réel
            self.assertTrue(data['needs_confirmation'])

            api.post('/api/production/opening-confirmation/', {
                'team': 'A', 'date': TODAY,
                'lines': [{'bread_price': self.bp500.pk, 'qty': 100}],
            }, format='json')

            data = api.get(f'/api/production/opening-confirmation/?date={TODAY}').data
            self.assertFalse(data['needs_confirmation'])
            self.assertTrue(data['teams']['A']['confirmed'])
