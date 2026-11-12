"""
Corrections BUG-217 à BUG-227 (dev-backend, 2026-11-12) — tests de non-régression
complémentaires aux sondes du testeur (`test_vague1_db_production_2026_11_12.py`).
BUG-216 : REJETÉ (décision client, quantités négatives/nulles acceptées) — verrouillé ici.
Données entièrement fictives.
"""
from datetime import date, datetime, time
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.models import ActivityLog, SystemNotification
from core.testing import make_node, make_user
from production.models import (
    BreadDisposal, BreadStock, BreadTransfer, ConsumableMovement, DailyTeamAssignment,
    ProductionSession, _adjust_bread_stock,
)
from production.tests.test_vague1_db_production_2026_11_12 import _Base, _api, _stock_qty


def _at(y, m, d, hh, mm=0):
    return timezone.make_aware(datetime(y, m, d, hh, mm), timezone.get_current_timezone())


class Bug218Tests(_Base):
    def test_valeur_theorique_arrondie_en_decimal(self):
        for sacks, expected in (('1.13', 237300), ('0.29', 60900), ('0.57', 119700), ('1.15', 241500), ('3', 630000)):
            ProductionSession.objects.all().delete()
            r = self._declare(flour_sacks_used=sacks, lines=[{'bread_price': self.bp500.pk, 'quantity': 1}])
            self.assertEqual(r.json()['theoretical_yield'], expected, sacks)


class Bug219Tests(_Base):
    def _no_trace(self):
        self.assertEqual(ProductionSession.objects.count(), 0)
        self.assertEqual(sum(b.qty_produced for b in BreadStock.objects.all()), 0)
        self.assertEqual(ConsumableMovement.objects.count(), 1)  # l'approvisionnement initial seul
        self.assertEqual(_stock_qty(self.node, 'SALT'), Decimal('100.000'))
        self.assertEqual(_stock_qty(self.node, 'FLOUR'), Decimal('0.000'))

    def test_corps_invalides_400_et_aucune_trace(self):
        self._entry('SALT', '100')
        base_moves = ConsumableMovement.objects.count()
        for bad in ('abc', [5], {'a': 1}, [{'consumable_type': 'XXX', 'quantity': '5'}],
                    [{'consumable_type': 'SALT', 'quantity': 'abc'}],
                    [{'consumable_type': 'SALT', 'quantity': 'NaN'}],
                    [{'consumable_type': 'SALT', 'quantity': True}],
                    [{'quantity': '5'}]):
            r = self._declare(consumables_used=bad)
            self.assertEqual(r.status_code, 400, (bad, r.status_code))
            self.assertIn('detail', r.json())
        self.assertEqual(ProductionSession.objects.count(), 0)
        self.assertEqual(sum(b.qty_produced for b in BreadStock.objects.all()), 0)
        self.assertEqual(ConsumableMovement.objects.count(), base_moves)

    def test_declaration_valide_inchangee(self):
        self._entry('SALT', '5000')
        r = self._declare(consumables_used=[{'consumable_type': 'SALT', 'quantity': '1500'},
                                            {'consumable_type': 'SALT', 'quantity': 0}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(_stock_qty(self.node, 'SALT'), Decimal('3500.000'))

    def test_echec_en_cours_de_route_annule_tout(self):
        self._entry('SALT', '100')
        with patch('production.views._record_consumable_exits', side_effect=RuntimeError('boom')):
            r = self._declare(consumables_used=[{'consumable_type': 'SALT', 'quantity': '5'}])
        self.assertEqual(r.status_code, 500)
        self._no_trace()


class Bug220Tests(_Base):
    def test_augmenter_puis_diminuer_les_sacs_regularise_la_farine(self):
        self._entry('FLOUR', '10')
        sid = self._declare().json()['id']          # 3 sacs -> 7
        self.api.patch(f'/api/production/sessions/{sid}/', {'flour_sacks_used': '5'}, format='json')
        self.assertEqual(_stock_qty(self.node, 'FLOUR'), Decimal('5.000'))
        self.api.patch(f'/api/production/sessions/{sid}/', {'flour_sacks_used': '4'}, format='json')
        self.assertEqual(_stock_qty(self.node, 'FLOUR'), Decimal('6.000'))
        self.assertTrue(ActivityLog.objects.filter(action='Régularisation Farine Fournée').exists())

    def test_patch_sans_changement_de_sacs_ne_cree_aucun_mouvement(self):
        self._entry('FLOUR', '10')
        sid = self._declare().json()['id']
        n = ConsumableMovement.objects.count()
        self.api.patch(f'/api/production/sessions/{sid}/', {'notes': 'ok'}, format='json')
        self.assertEqual(ConsumableMovement.objects.count(), n)


class Bug221Tests(_Base):
    def _disposal(self, dtype='DECLASSED', qty=50):
        _adjust_bread_stock(self.node, self.bp200, produced=500)
        s = ProductionSession.objects.create(node=self.node, team='A', date=date(2026, 11, 12))
        r = self.api.post('/api/production/disposals/', {
            'session': str(s.pk), 'bread_price': self.bp200.pk, 'disposal_type': dtype, 'quantity': qty,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()['id']

    def _avail(self):
        return BreadStock.objects.get(node=self.node, bread_price=self.bp200).qty_available

    def test_patch_a_la_baisse_et_suppression(self):
        did = self._disposal()
        self.api.patch(f'/api/production/disposals/{did}/', {'quantity': 20}, format='json')
        self.assertEqual(self._avail(), 480)
        self.assertEqual(self.api.delete(f'/api/production/disposals/{did}/').status_code, 204)
        self.assertEqual(self._avail(), 500)
        self.assertTrue(ActivityLog.objects.filter(action='Suppression Disposition Pain').exists())

    def test_changement_de_type_vers_remaining_restitue_les_pains(self):
        did = self._disposal()
        self.api.patch(f'/api/production/disposals/{did}/', {'disposal_type': 'REMAINING'}, format='json')
        self.assertEqual(self._avail(), 500)

    def test_remaining_ne_touche_jamais_le_stock(self):
        did = self._disposal('REMAINING', 40)
        self.assertEqual(self._avail(), 500)
        self.api.patch(f'/api/production/disposals/{did}/', {'quantity': 10}, format='json')
        self.assertEqual(self._avail(), 500)
        self.api.delete(f'/api/production/disposals/{did}/')
        self.assertEqual(self._avail(), 500)


class Bug222Tests(_Base):
    def test_patch_entree_applique_le_delta(self):
        mid = self._entry('YEAST', '2').json()['id']
        self.api.patch(f'/api/production/movements/{mid}/', {'quantity': '10'}, format='json')
        self.assertEqual(_stock_qty(self.node, 'YEAST'), Decimal('10.000'))
        self.api.patch(f'/api/production/movements/{mid}/', {'quantity': '4'}, format='json')
        self.assertEqual(_stock_qty(self.node, 'YEAST'), Decimal('4.000'))

    def test_patch_sortie_applique_le_delta(self):
        self._entry('SALT', '1000')
        mid = self._entry('SALT', '300', mtype='EXIT').json()['id']
        self.assertEqual(_stock_qty(self.node, 'SALT'), Decimal('700.000'))
        self.api.patch(f'/api/production/movements/{mid}/', {'quantity': '500'}, format='json')
        self.assertEqual(_stock_qty(self.node, 'SALT'), Decimal('500.000'))

    def test_suppression_inverse_entree_et_sortie(self):
        e = self._entry('SALT', '1000').json()['id']
        x = self._entry('SALT', '300', mtype='EXIT').json()['id']
        self.assertEqual(self.api.delete(f'/api/production/movements/{x}/').status_code, 204)
        self.assertEqual(_stock_qty(self.node, 'SALT'), Decimal('1000.000'))
        self.assertEqual(self.api.delete(f'/api/production/movements/{e}/').status_code, 204)
        self.assertEqual(_stock_qty(self.node, 'SALT'), Decimal('0.000'))

    def test_bug216_rejete_quantite_nulle_ou_negative_toujours_acceptee(self):
        self.assertEqual(self._entry('SALT', '0').status_code, 201)
        self.assertEqual(self._entry('SALT', '-3', mtype='EXIT').status_code, 201)


class Bug223_224TransferTests(_Base):
    def setUp(self):
        super().setUp()
        _adjust_bread_stock(self.node, self.bp200, produced=500)
        self.rcv = _api(self.gerant_other)       # K4 demande à K2
        self.third = make_node(code='K5')
        self.direction = make_user('DIRECTION', node=None)

    def _create(self, qty=100):
        return self.rcv.post('/api/production/transfers/', {
            'from_node': self.node.pk, 'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': qty}],
        }, format='json').json()['id']

    def _respond(self, tid, qty=100):
        return self.api.post(f'/api/production/transfers/{tid}/respond_to_request/',
                             {'approved': True, 'lines': [{'bread_price': self.bp200.pk, 'quantity_sent': qty}]},
                             format='json')

    def _receive(self, tid, qty):
        return self.rcv.post(f'/api/production/transfers/{tid}/confirm_reception/',
                             {'lines': [{'bread_price': self.bp200.pk, 'quantity_received': qty}]}, format='json')

    def _disputed(self):
        tid = self._create()
        self._respond(tid)
        self.assertEqual(self._receive(tid, 98).json()['transfer_status'], 'DISPUTED')
        return tid

    def _avail(self, node):
        return BreadStock.objects.get(node=node, bread_price=self.bp200).qty_available

    def _resolve(self, api, tid, **body):
        return api.post(f'/api/production/transfers/{tid}/resolve_dispute/', body, format='json')

    # --- BUG-223
    def test_resolution_reçu_fait_foi_equilibre_le_groupe_et_leve_le_blocage(self):
        from treasury.views import _unresolved_incoming_transfer_gap
        tid = self._disputed()
        self.assertTrue(_unresolved_incoming_transfer_gap(self.other))
        self.assertEqual((self._avail(self.node), self._avail(self.other)), (400, 98))
        r = self._resolve(self.api, tid, resolution='ALIGN_ON_RECEIVED', reason='2 pains tombés en route')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['transfer_status'], 'CONFIRMED')
        self.assertEqual((self._avail(self.node), self._avail(self.other)), (402, 98))
        self.assertEqual(self._avail(self.node) + self._avail(self.other), 500)
        self.assertFalse(_unresolved_incoming_transfer_gap(self.other))
        self.assertTrue(ActivityLog.objects.filter(action='Résolution Litige Transfert').exists())
        self.assertTrue(SystemNotification.objects.filter(title__startswith='Litige Transfert résolu').exists())
        self.assertIn('2 pains tombés', BreadTransfer.objects.get(pk=tid).notes)

    def test_resolution_envoye_fait_foi_credite_le_recepteur(self):
        tid = self._disputed()
        r = self._resolve(_api(self.direction), tid, resolution='ALIGN_ON_SENT', reason='erreur de comptage')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((self._avail(self.node), self._avail(self.other)), (400, 100))

    def test_resolution_permissions_et_validations(self):
        tid = self._disputed()
        body = {'resolution': 'ALIGN_ON_SENT', 'reason': 'x'}
        self.assertEqual(self._resolve(self.rcv, tid, **body).status_code, 403)               # récepteur
        k5 = _api(make_user('GERANT', node=self.third))
        self.assertEqual(self._resolve(k5, tid, **body).status_code, 404)                      # tiers
        self.assertEqual(self._resolve(self.api, tid, resolution='ALIGN_ON_SENT').status_code, 400)  # motif manquant
        self.assertEqual(self._resolve(self.api, tid, resolution='?', reason='x').status_code, 400)
        self.assertEqual(BreadTransfer.objects.get(pk=tid).transfer_status, 'DISPUTED')
        self.assertEqual(self._resolve(self.api, tid, **body).status_code, 200)
        self.assertEqual(self._resolve(self.api, tid, **body).status_code, 400)               # déjà résolu

    def test_recomptage_par_le_recepteur_regularise_du_delta(self):
        tid = self._disputed()
        r = self._receive(tid, 100)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['transfer_status'], 'CONFIRMED')
        self.assertEqual(self._avail(self.other), 100)          # delta +2, pas +100
        self.assertEqual(self._avail(self.node) + self._avail(self.other), 500)

    def test_transfert_engage_non_supprimable_ni_modifiable(self):
        tid = self._disputed()
        self.assertEqual(self.api.delete(f'/api/production/transfers/{tid}/').status_code, 400)
        self.assertEqual(self.api.patch(f'/api/production/transfers/{tid}/', {'notes': 'x'}, format='json').status_code, 400)
        pending = self._create(5)
        self.assertEqual(self.rcv.delete(f'/api/production/transfers/{pending}/').status_code, 204)

    # --- BUG-224
    def test_validations_supplementaires(self):
        def post(body):
            return self.rcv.post('/api/production/transfers/', body, format='json')
        bp = self.bp200.pk
        self.assertEqual(post({'from_node': self.node.pk, 'lines': [{'bread_price': 99999, 'quantity_sent': 5}]}).status_code, 400)
        self.assertEqual(post({'from_node': self.node.pk, 'lines': [{'bread_price': bp, 'quantity_sent': 0}]}).status_code, 400)
        self.assertEqual(post({'from_node': self.node.pk, 'lines': [{'bread_price': bp, 'quantity_sent': True}]}).status_code, 400)
        self.assertEqual(post({'from_node': self.node.pk, 'lines': [{'bread_price': bp, 'quantity_sent': 1.5}]}).status_code, 400)
        self.assertEqual(post({'from_node': self.node.pk, 'lines': 'x'}).status_code, 400)
        self.assertEqual(post({'from_node': self.node.pk}).status_code, 400)
        self.assertEqual(BreadTransfer.objects.count(), 0)
        ok = post({'from_node': self.node.pk, 'lines': [{'bread_price': bp, 'quantity_sent': '5'},
                                                        {'bread_price': bp, 'quantity_sent': 7}]})
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(BreadTransfer.objects.get().lines.get().quantity_sent, 12)   # doublon cumulé

    def test_reponse_quantite_invalide_400_sans_effet_de_stock(self):
        tid = self._create()
        r = self._respond(tid, 'abc')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._avail(self.node), 500)
        self.assertEqual(BreadTransfer.objects.get(pk=tid).transfer_status, 'PENDING')


class Bug225Tests(_Base):
    def test_date_impossible_400_sur_les_routes_et_post(self):
        for url in (
            '/api/production/sessions/reconciliation/?date_from=2026-02-31',
            '/api/production/sessions/reconciliation/?date_to=2026-13-45',
            '/api/production/sessions/reconciliation/?date=abc',
        ):
            r = self.api.get(url)
            self.assertEqual(r.status_code, 400, url)
            self.assertIn('Date invalide', r.json()['detail'])
        r = self.api.post('/api/production/opening-confirmation/', {'team': 'A', 'date': '2026-13-45', 'lines': []}, format='json')
        self.assertEqual(r.status_code, 400, r.content)

    def test_date_valide_toujours_acceptee(self):
        self.assertEqual(self.api.get('/api/production/sessions/reconciliation/?date=2026-11-12').status_code, 200)


class Bug226Tests(_Base):
    def setUp(self):
        super().setUp()
        self.node.team_b_end_time = time(20, 0)
        self.node.save()

    def _session(self, d, team='B'):
        r = self.api.post('/api/production/sessions/', {
            'team': team, 'date': d, 'flour_sacks_used': '1',
            'lines': [{'bread_price': self.bp200.pk, 'quantity': 10}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)

    def _status(self, now):
        with patch('django.utils.timezone.now', return_value=now):
            return self.api.get('/api/production/sessions/shift-end-status/').json()

    def test_veille_cloturee_automatiquement_apres_la_grace(self):
        self._session('2026-11-11')
        body = self._status(_at(2026, 11, 12, 6, 0))
        self.assertTrue(body['auto_closed'], body)
        self.assertTrue(ProductionSession.objects.get(date=date(2026, 11, 11)).is_closed)

    def test_veille_dans_le_delai_de_grace_demande_la_validation(self):
        self.node.team_b_end_time = time(23, 50)
        self.node.save()
        self._session('2026-11-11')
        body = self._status(_at(2026, 11, 12, 0, 5))            # 15 min après 23:50 (< 30 min)
        self.assertTrue(body['pending_validation'], body)
        self.assertFalse(ProductionSession.objects.get(date=date(2026, 11, 11)).is_closed)

    def test_jour_courant_inchange_avant_et_apres_la_fin_de_creneau(self):
        self._session('2026-11-12')
        self.assertFalse(self._status(_at(2026, 11, 12, 19, 0))['pending_validation'])
        self.assertTrue(self._status(_at(2026, 11, 12, 20, 10))['pending_validation'])
        self.assertTrue(self._status(_at(2026, 11, 12, 20, 40))['auto_closed'])

    def test_session_future_ou_deja_close_ignoree(self):
        self._session('2026-11-13')
        self.assertEqual(self._status(_at(2026, 11, 12, 23, 0)), {'pending_validation': False})


class Bug227Tests(TestCase):
    def setUp(self):
        self.node = make_node(code='K1')
        self.api = _api(make_user('GERANT', node=self.node))

    def test_hors_rotation_post_utilise_la_date_calendaire(self):
        with patch('django.utils.timezone.now', return_value=_at(2026, 11, 12, 5, 0)):
            r = self.api.post('/api/production/team-assignment/', {'team': 'B'}, format='json')
            g = self.api.get('/api/production/team-assignment/').json()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['work_date'], '2026-11-12')
        self.assertEqual(g['work_date'], '2026-11-12')
        self.assertEqual(g['team'], 'B')
        self.assertFalse(DailyTeamAssignment.objects.filter(work_date=date(2026, 11, 11)).exists())

    def test_en_rotation_la_journee_de_releve_est_conservee(self):
        self.node.team_rotation_enabled = True
        self.node.save(update_fields=['team_rotation_enabled'])
        with patch('django.utils.timezone.now', return_value=_at(2026, 11, 12, 5, 0)):
            g = self.api.get('/api/production/team-assignment/').json()
        self.assertEqual(g['work_date'], '2026-11-11')
