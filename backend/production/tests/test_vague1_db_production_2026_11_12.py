"""
Vague 1 (base réelle, K2) — Production & Stocks — testeur-production, 2026-11-12.

Anomalies observées via l'API en marche (backend/db.sqlite3, boulangerie K2) et
reproduites ici sur base de test. Chaque test `@expectedFailure` porte la
référence du ticket (docs/qa/REGISTRE_BUGS.md) ; il doit PASSER (retirer le
décorateur) une fois le ticket corrigé. Aucun code applicatif n'est modifié.

Tests sans décorateur : comportements CONFORMES vérifiés (non-régression).
"""
from datetime import date, datetime
from decimal import Decimal
from unittest import expectedFailure
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user, make_bread_price
from production.models import (
    BreadDisposal, BreadStock, BreadTransfer, ConsumableMovement, ConsumableStock,
    ConsumableType, ProductionSession, _adjust_bread_stock,
)

# Les tests d'anomalies « 500 » doivent recevoir la réponse au lieu de lever.
def _api(user):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(user)
    return c


def _stocks(node):
    for code, unit in (('FLOUR', 'sacs'), ('SALT', 'g'), ('YEAST', 'paquets'), ('OIL', 'litres')):
        ConsumableType.objects.get_or_create(code=code, defaults={'label': code, 'unit': unit})
        ConsumableStock.objects.get_or_create(node=node, consumable_type=code, defaults={'unit': unit})


def _stock_qty(node, code):
    return ConsumableStock.objects.get(node=node, consumable_type=code).quantity


class _Base(TestCase):
    def setUp(self):
        self.node = make_node(code='K2', sac_value_fc=Decimal('210000'))
        self.other = make_node(code='K4')
        self.gerant = make_user('GERANT', node=self.node)
        self.gerant_other = make_user('GERANT', node=self.other)
        self.bp200 = make_bread_price('MINI', 'Pain 200 FC', 200)
        self.bp500 = make_bread_price('GRAND', 'Pain 500 FC', 500)
        _stocks(self.node)
        self.api = _api(self.gerant)

    def _entry(self, code, qty, price='10', mtype='ENTRY'):
        stock = ConsumableStock.objects.get(node=self.node, consumable_type=code)
        return self.api.post('/api/production/movements/', {
            'stock': str(stock.pk), 'movement_type': mtype, 'quantity': str(qty), 'unit_price': price,
        }, format='json')

    def _declare(self, **extra):
        body = {
            'team': 'A', 'date': '2026-11-12', 'flour_sacks_used': '3',
            'lines': [{'bread_price': self.bp200.pk, 'quantity': 100}],
        }
        body.update(extra)
        return self.api.post('/api/production/sessions/', body, format='json')


# ───────────────────────── Comportements conformes ─────────────────────────

class ConformityTests(_Base):
    def test_stock_restant_initial_plus_entrees_moins_utilise_decimaux(self):
        self._entry('FLOUR', '10.5')
        self._entry('SALT', '5000')
        self._entry('YEAST', '4.25')
        self._entry('OIL', '10.33')
        r = self._declare(consumables_used=[
            {'consumable_type': 'SALT', 'quantity': '1500'},
            {'consumable_type': 'YEAST', 'quantity': '0.25'},
            {'consumable_type': 'OIL', 'quantity': '0.33'},
        ])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(_stock_qty(self.node, 'FLOUR'), Decimal('7.500'))
        self.assertEqual(_stock_qty(self.node, 'SALT'), Decimal('3500.000'))
        self.assertEqual(_stock_qty(self.node, 'YEAST'), Decimal('4.000'))
        self.assertEqual(_stock_qty(self.node, 'OIL'), Decimal('10.000'))

    def test_manquant_et_excedent_signes_et_valeur_sac_figee(self):
        r = self._declare(lines=[{'bread_price': self.bp500.pk, 'quantity': 1000}])  # 500 000 vs 630 000
        self.assertEqual(r.json()['yield_gap'], -130000)
        self.node.sac_value_fc = Decimal('250000')
        self.node.save()
        s = ProductionSession.objects.get()
        r2 = self.api.get(f'/api/production/sessions/{s.pk}/')
        self.assertEqual(r2.json()['sac_value_fc_used'], 210000)  # historique intact
        self.assertEqual(r2.json()['yield_gap'], -130000)

    def test_stock_consommable_negatif_autorise_et_notifie(self):
        self._entry('SALT', '3500')
        r = self._declare(consumables_used=[{'consumable_type': 'SALT', 'quantity': '5000'}])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(_stock_qty(self.node, 'SALT'), Decimal('-1500.000'))
        self.assertTrue(SystemNotification.objects.filter(title__startswith='Stock négatif').exists())

    def test_inventaire_ecart_calcule(self):
        self._entry('FLOUR', '4.5')
        r = self.api.post('/api/production/counts/', {
            'consumable_type': 'FLOUR', 'count_date': '2026-11-12', 'physical_quantity': '6.25',
        }, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Decimal(r.json()['gap']), Decimal('1.750'))

    def test_transfert_somme_groupe_inchangee_et_roles(self):
        _adjust_bread_stock(self.node, self.bp200, produced=500)
        req = _api(self.gerant_other).post('/api/production/transfers/', {
            'from_node': self.node.pk, 'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': 100}],
        }, format='json')
        self.assertEqual(req.status_code, 201)
        tid = req.json()['id']
        # le demandeur ne peut pas répondre à sa propre demande
        self.assertEqual(_api(self.gerant_other).post(
            f'/api/production/transfers/{tid}/respond_to_request/',
            {'approved': True, 'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': 100}]}, format='json',
        ).status_code, 403)
        self.assertEqual(self.api.post(
            f'/api/production/transfers/{tid}/respond_to_request/',
            {'approved': True, 'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': 100}]}, format='json',
        ).status_code, 200)
        # l'émetteur ne peut pas valider la réception
        self.assertEqual(self.api.post(
            f'/api/production/transfers/{tid}/confirm_reception/',
            {'lines': [{'bread_price': self.bp200.pk, 'quantity_received': 100}]}, format='json',
        ).status_code, 403)
        r = _api(self.gerant_other).post(
            f'/api/production/transfers/{tid}/confirm_reception/',
            {'lines': [{'bread_price': self.bp200.pk, 'quantity_received': 100}]}, format='json')
        self.assertEqual(r.json()['transfer_status'], 'CONFIRMED')
        total = sum(b.qty_available for b in BreadStock.objects.all())
        self.assertEqual(total, 500)
        # double validation refusée
        self.assertEqual(_api(self.gerant_other).post(
            f'/api/production/transfers/{tid}/confirm_reception/',
            {'lines': [{'bread_price': self.bp200.pk, 'quantity_received': 100}]}, format='json',
        ).status_code, 400)


# ─────────────────────────────── Anomalies ────────────────────────────────

class NegativeQuantityTests(_Base):
    @expectedFailure
    def test_bug216_entree_negative_ou_nulle_refusee(self):
        """BUG-216 : un mouvement ENTRY de quantité négative est accepté (201) et DIMINUE le stock."""
        self._entry('SALT', '5000')
        r = self._entry('SALT', '-5')
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(_stock_qty(self.node, 'SALT'), Decimal('5000.000'))

    @expectedFailure
    def test_bug216_sortie_negative_refusee(self):
        """BUG-216 : un mouvement EXIT négatif AUGMENTE le stock (201)."""
        self._entry('YEAST', '4')
        r = self._entry('YEAST', '-1', mtype='EXIT')
        self.assertEqual(r.status_code, 400, r.content)

    @expectedFailure
    def test_bug216_inventaire_physique_negatif_refuse(self):
        """BUG-216 : un comptage physique négatif (-1400 g) est accepté (201)."""
        r = self.api.post('/api/production/counts/', {
            'consumable_type': 'SALT', 'count_date': '2026-11-12', 'physical_quantity': '-1400',
        }, format='json')
        self.assertEqual(r.status_code, 400, r.content)


class StockNegativeNotificationTests(_Base):
    @expectedFailure
    def test_bug217_message_stock_negatif_lisible(self):
        """BUG-217 : le message cite `F(quantity) - Value(Decimal('5000'))` au lieu de la quantité disponible."""
        self._entry('SALT', '3500')
        self._declare(consumables_used=[{'consumable_type': 'SALT', 'quantity': '5000'}])
        n = SystemNotification.objects.filter(title__startswith='Stock négatif').first()
        self.assertIsNotNone(n)
        self.assertNotIn('F(quantity)', n.message)
        self.assertNotIn('Value(Decimal', n.message)
        self.assertIn('3500', n.message)


class TheoreticalYieldDecimalTests(_Base):
    @expectedFailure
    def test_bug218_valeur_theorique_exacte_pour_sacs_decimaux(self):
        """BUG-218 : 1,13 sac x 210 000 FC = 237 300 FC ; obtenu 237 299 (float tronqué)."""
        r = self._declare(flour_sacks_used='1.13', lines=[{'bread_price': self.bp500.pk, 'quantity': 474}])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['theoretical_yield'], 237300)
        self.assertEqual(r.json()['yield_gap'], 237000 - 237300)


class AtomicityTests(_Base):
    @expectedFailure
    def test_bug219_consumables_used_invalide_ne_laisse_aucune_trace(self):
        """BUG-219 : `consumables_used` invalide -> 500 APRES création de la session et du stock pains ;
        un rejeu double la production. Attendu : 400 et aucun effet de bord."""
        for bad in ('abc', [{'consumable_type': 'SALT', 'quantity': 'abc'}], [5]):
            r = self._declare(consumables_used=bad)
            self.assertEqual(r.status_code, 400, (bad, r.status_code))
        self.assertEqual(ProductionSession.objects.count(), 0)
        self.assertEqual(sum(b.qty_produced for b in BreadStock.objects.all()), 0)


class SessionEditStockTests(_Base):
    @expectedFailure
    def test_bug220_modifier_les_sacs_ajuste_le_stock_farine(self):
        """BUG-220 : PATCH flour_sacks_used (3 -> 5) ne modifie pas le stock de farine (aucun mouvement)."""
        self._entry('FLOUR', '10')
        r = self._declare()
        sid = r.json()['id']
        self.assertEqual(_stock_qty(self.node, 'FLOUR'), Decimal('7.000'))
        self.api.patch(f'/api/production/sessions/{sid}/', {'flour_sacks_used': '5'}, format='json')
        self.assertEqual(_stock_qty(self.node, 'FLOUR'), Decimal('5.000'))


class DisposalEditStockTests(_Base):
    def _disposal(self, qty=50):
        _adjust_bread_stock(self.node, self.bp200, produced=500)
        s = ProductionSession.objects.create(node=self.node, team='A', date=date(2026, 11, 12))
        r = self.api.post('/api/production/disposals/', {
            'session': str(s.pk), 'bread_price': self.bp200.pk, 'disposal_type': 'DECLASSED', 'quantity': qty,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()['id']

    def _avail(self):
        return BreadStock.objects.get(node=self.node, bread_price=self.bp200).qty_available

    @expectedFailure
    def test_bug221_modifier_une_disposition_ajuste_le_stock(self):
        """BUG-221 : PATCH quantity 50 -> 100 laisse qty_disposed à 50."""
        did = self._disposal(50)
        self.assertEqual(self._avail(), 450)
        self.api.patch(f'/api/production/disposals/{did}/', {'quantity': 100}, format='json')
        self.assertEqual(self._avail(), 400)

    @expectedFailure
    def test_bug221_supprimer_une_disposition_rend_les_pains(self):
        """BUG-221 : DELETE d'une disposition (204) ne restitue pas les pains au stock."""
        did = self._disposal(50)
        r = self.api.delete(f'/api/production/disposals/{did}/')
        self.assertIn(r.status_code, (204, 403, 405))
        if r.status_code == 204:
            self.assertEqual(self._avail(), 500)


class MovementEditTests(_Base):
    @expectedFailure
    def test_bug222_modifier_un_mouvement_ne_double_pas_le_stock(self):
        """BUG-222 : PATCH quantity 2 -> 10 sur une ENTRY ajoute de NOUVEAU 10 au stock (stock = 2 + 10)."""
        r = self._entry('YEAST', '2')
        mid = r.json()['id']
        self.api.patch(f'/api/production/movements/{mid}/', {'quantity': '10'}, format='json')
        self.assertEqual(_stock_qty(self.node, 'YEAST'), Decimal('10.000'))

    @expectedFailure
    def test_bug222_supprimer_un_mouvement_inverse_le_stock_ou_est_refuse(self):
        """BUG-222 : DELETE (204) d'une ENTRY laisse le stock inchangé : registre et stock divergent."""
        r = self._entry('SALT', '500')
        mid = r.json()['id']
        d = self.api.delete(f'/api/production/movements/{mid}/')
        if d.status_code == 204:
            self.assertEqual(_stock_qty(self.node, 'SALT'), Decimal('0.000'))
        else:
            self.assertIn(d.status_code, (403, 405))


class TransferDisputeTests(_Base):
    def _disputed(self):
        _adjust_bread_stock(self.node, self.bp200, produced=500)
        rcv = _api(self.gerant_other)
        tid = rcv.post('/api/production/transfers/', {
            'from_node': self.node.pk, 'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': 100}],
        }, format='json').json()['id']
        self.api.post(f'/api/production/transfers/{tid}/respond_to_request/',
                      {'approved': True, 'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': 100}]}, format='json')
        r = rcv.post(f'/api/production/transfers/{tid}/confirm_reception/',
                     {'lines': [{'bread_price': self.bp200.pk, 'quantity_received': 98}]}, format='json')
        self.assertEqual(r.json()['transfer_status'], 'DISPUTED')
        return rcv, tid

    def test_ecart_98_sur_100_alerte_et_bloque_la_cloture(self):
        rcv, tid = self._disputed()
        self.assertTrue(SystemNotification.objects.filter(title__startswith='Litige Transfert').exists())
        r = rcv.post('/api/treasury/closures/', {'date': timezone.localdate().isoformat()}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('Clôture bloquée', r.json()['detail'])

    @expectedFailure
    def test_bug223_un_litige_doit_pouvoir_etre_resolu(self):
        """BUG-223 : un transfert DISPUTED ne peut plus changer d'état (confirm_reception exige RESPONDED)
        et aucune action de résolution n'existe -> la clôture du récepteur reste bloquée à jamais
        (message « Faites valider/corriger le transfert »). Attendu : une re-validation (ou une action
        de résolution) est possible et lève le blocage."""
        rcv, tid = self._disputed()
        r = rcv.post(f'/api/production/transfers/{tid}/confirm_reception/',
                     {'lines': [{'bread_price': self.bp200.pk, 'quantity_received': 100}]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)


class TransferInputValidationTests(_Base):
    def _post(self, api, body):
        return api.post('/api/production/transfers/', body, format='json')

    @expectedFailure
    def test_bug224_quantite_non_numerique_400(self):
        r = self._post(_api(self.gerant_other), {'from_node': self.node.pk,
                                                 'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': 'abc'}]})
        self.assertEqual(r.status_code, 400, r.status_code)

    @expectedFailure
    def test_bug224_auto_transfert_refuse(self):
        r = self._post(_api(self.gerant_other), {'from_node': self.other.pk,
                                                 'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': 5}]})
        self.assertEqual(r.status_code, 400, r.status_code)

    @expectedFailure
    def test_bug224_demande_sans_ligne_refusee(self):
        r = self._post(_api(self.gerant_other), {'from_node': self.node.pk, 'lines': []})
        self.assertEqual(r.status_code, 400, r.status_code)
        self.assertEqual(BreadTransfer.objects.count(), 0)

    @expectedFailure
    def test_bug224_reception_negative_400(self):
        _adjust_bread_stock(self.node, self.bp200, produced=50)
        rcv = _api(self.gerant_other)
        tid = self._post(rcv, {'from_node': self.node.pk,
                               'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': 10}]}).json()['id']
        self.api.post(f'/api/production/transfers/{tid}/respond_to_request/',
                      {'approved': True, 'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': 10}]}, format='json')
        r = rcv.post(f'/api/production/transfers/{tid}/confirm_reception/',
                     {'lines': [{'bread_price': self.bp200.pk, 'quantity_received': -30}]}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)

    @expectedFailure
    def test_bug224_siege_sans_boulangerie_pas_de_500(self):
        hq = make_user('DIRECTION', node=None)
        r = self._post(_api(hq), {'from_node': self.node.pk,
                                  'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': 5}]})
        self.assertIn(r.status_code, (400, 403), r.status_code)


class InvalidDateTests(_Base):
    @expectedFailure
    def test_bug225_date_calendaire_invalide_400(self):
        """BUG-225 : `date=2026-13-45` (format valide, date impossible) -> ValueError 500 sur 4 endpoints."""
        for url in (
            '/api/production/bread-stocks/by-date/?date=2026-13-45',
            '/api/production/opening-confirmation/?date=2026-13-45',
            '/api/production/daily-closure/?date=2026-13-45',
            '/api/production/sessions/reconciliation/?date=2026-13-45',
        ):
            r = self.api.get(url)
            self.assertEqual(r.status_code, 400, (url, r.status_code))


class ClassicPreviousDayTests(_Base):
    def _at(self, y, m, d, hh, mm):
        return timezone.make_aware(datetime(y, m, d, hh, mm), timezone.get_current_timezone())

    @expectedFailure
    def test_bug226_session_de_la_veille_cloturee_en_mode_classique(self):
        """BUG-226 : hors rotation, `shift-end-status` ne regarde que `date=today` : la session de
        l'équipe B de la VEILLE (fin de créneau 20:00 dépassée de 10 h) reste ouverte indéfiniment."""
        self.node.team_b_end_time = datetime(2026, 1, 1, 20, 0).time()
        self.node.save()
        self.api.post('/api/production/sessions/', {
            'team': 'B', 'date': '2026-11-11', 'flour_sacks_used': '1',
            'lines': [{'bread_price': self.bp200.pk, 'quantity': 10}],
        }, format='json')
        with patch('django.utils.timezone.now', return_value=self._at(2026, 11, 12, 6, 0)):
            r = self.api.get('/api/production/sessions/shift-end-status/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        s = ProductionSession.objects.get(date=date(2026, 11, 11))
        self.assertTrue(body.get('auto_closed') or body.get('pending_validation') or s.is_closed, body)


class ClassicTeamAssignmentTests(_Base):
    @expectedFailure
    def test_bug227_team_assignment_hors_rotation_meme_journee_que_le_reste(self):
        """BUG-227 : hors rotation, GET/POST team-assignment utilisent la journée de relève
        (05:00 -> J-1) alors que sessions/opening-confirmation/daily-closure utilisent la date calendaire."""
        with patch('django.utils.timezone.now',
                   return_value=timezone.make_aware(datetime(2026, 11, 12, 5, 0), timezone.get_current_timezone())):
            ta = self.api.get('/api/production/team-assignment/').json()
            oc = self.api.get('/api/production/opening-confirmation/').json()
        self.assertEqual(oc['work_date'], '2026-11-12')
        self.assertEqual(ta['work_date'], oc['work_date'])
