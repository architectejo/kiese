"""Lot I-5 (dev-b / architecte-sync) : statistiques d'intrants JUSTES sur un poste hors ligne et au cloud.
BUG-1111 (donnees d'intrants : mouvements, dates, envois direction) et BUG-1112 (`facturier` d'une facture
poussee). Donnees FICTIVES (jamais celles du fichier du client).

Banc : une seule base de test joue tour a tour le cloud, le poste K1 et le poste K2 (etat des tables
d'intrants sauvegarde / recharge a chaque changement de site, comme `P13Base`). Un poste ne connait l'etat
du cloud que par push / pull (`build_outbound_payload`, push HTTP, pull HTTP, `apply_push_response`,
`apply_pull_response`). La « statistique » est recalculee ici de facon INDEPENDANTE depuis les mouvements :
stock initial du jour, entree, sortie, consommation declaree (sorties liees a une fournee), solde, sacs de
farine du jour, inventaire physique et ecart.
"""
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal as D
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Node
from core.testing import make_node, make_user
from production.models import (ConsumableCount, ConsumableInventory, ConsumableMovement, ConsumableStock,
                               ProductionSession)
from sync.management.commands.sync_now import (apply_pull_response, apply_push_response,
                                               build_outbound_payload)
from sync.models import NodeAuthToken

PUSH = '/api/sync/push/'
PULL = '/api/sync/pull/'
DISPATCH = '/api/production/consumables/dispatch/'
TYPES = ('FLOUR', 'YEAST', 'OIL', 'SALT')
TABLES = (ConsumableStock, ProductionSession, ConsumableMovement, ConsumableInventory, ConsumableCount)


def api_for(node):
    _, raw = NodeAuthToken.issue_for_node(node)
    api = APIClient(raise_request_exception=False)
    api.credentials(HTTP_AUTHORIZATION=f'Bearer {raw}')
    return api


def noon(day):
    return timezone.make_aware(datetime(day.year, day.month, day.day, 12, 0))


class Bench(TestCase):
    SITES = ('cloud', 'K1', 'K2')

    def setUp(self):
        self.node = {'K1': make_node(code='K1'), 'K2': make_node(code='K2')}
        self.siege = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege', 'is_active': False})[0]
        self.direction = make_user(role='DIRECTION')
        self.api = {n: api_for(self.node[n]) for n in ('K1', 'K2')}
        self.today = timezone.localdate()
        self.d0, self.d1, self.d2 = self.today - timedelta(days=2), self.today - timedelta(days=1), self.today
        self.cur = 'cloud'
        self.states = {n: self._dump() for n in self.SITES}
        self.cursor = {'K1': {}, 'K2': {}}

    # ---- sites
    def _dump(self):
        return {m: list(m.objects.values()) for m in TABLES}

    def _load(self, st):
        for m in reversed(TABLES):
            m.objects.all().delete()
        for m in TABLES:
            rows = st[m]
            m.objects.bulk_create([m(**r) for r in rows])
            for r in rows:
                fields = {k: r[k] for k in ('created_at', 'updated_at') if k in r}
                if fields:
                    m.objects.filter(pk=r['id'] if 'id' in r else r['id']).update(**fields)

    def go(self, name):
        if name != self.cur:
            self.states[self.cur] = self._dump()
            self._load(self.states[name])
            self.cur = name

    # ---- cycle de synchronisation (un `sync_now`)
    def sync(self, name, drop_pull=False):
        self.go(name)
        payload = build_outbound_payload(name)
        self.go('cloud')
        r = self.api[name].post(PUSH, dict(payload, batch_id=str(uuid.uuid4())), format='json')
        self.assertEqual(r.status_code, 200, r.content)
        data = r.data
        pr = self.api[name].get(PULL, self.cursor[name])
        self.assertEqual(pr.status_code, 200, pr.content)
        pulled = json.loads(pr.content)
        self.go(name)
        apply_push_response(data)
        if not drop_pull:
            apply_pull_response(pulled)
            if isinstance(pulled.get('since_consumables'), str):
                self.cursor[name] = {'since_consumables': pulled['since_consumables']}
        rejected = [(k, x.get('reason')) for k, rows in data['results'].items() for x in rows
                    if x['status'] != 'ACCEPTED']
        self.assertEqual(rejected, [])
        return payload, data, pulled

    # ---- saisies
    def stock(self, code, ctype):
        st, _ = ConsumableStock.objects.get_or_create(
            node=self.node[code] if code in self.node else self.siege, consumable_type=ctype,
            defaults={'node_origin': code, 'unit': ''})
        return st

    def move(self, code, ctype, kind, qty, day, price='0', session=None, origin=None):
        """Saisie locale (poste `code`) ou cloud/direction (`code='SIEGE'`), datee de `day` a midi."""
        node = self.node.get(code, self.siege)
        m = ConsumableMovement(node=node, stock=self.stock(code, ctype), movement_type=kind, quantity=D(qty),
                               unit_price=D(price), session=session, node_origin=origin or code)
        m.save()
        ConsumableMovement.objects.filter(pk=m.pk).update(created_at=noon(day))
        return m

    def session(self, code, day, sacks, team='A'):
        return ProductionSession.objects.create(
            node=self.node[code], team=team, date=day, flour_sacks_used=D(sacks), node_origin=code)

    def inventory(self, code, day, physical_by_type):
        inv = ConsumableInventory.objects.create(node=self.node[code], inventory_date=day, node_origin=code)
        for ctype, phys in physical_by_type.items():
            system = ConsumableStock.objects.get(node=self.node[code], consumable_type=ctype).quantity
            ConsumableCount.objects.create(
                node=self.node[code], consumable_type=ctype, count_date=day, system_quantity=system,
                physical_quantity=D(phys), gap=D(phys) - system, inventory=inv)
        return inv

    def dispatch(self, ctype, allocs, day):
        """Envoi direction REST au cloud ; les mouvements sont dates de `day`."""
        self.go('cloud')
        before = set(ConsumableMovement.objects.values_list('pk', flat=True))
        c = APIClient()
        c.force_authenticate(self.direction)
        r = c.post(DISPATCH, {'consumable_type': ctype, 'allocations': [
            {'node': self.node[n].pk, 'quantity': q} for n, q in allocs]}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        for m in ConsumableMovement.objects.exclude(pk__in=before):
            ConsumableMovement.objects.filter(pk=m.pk).update(created_at=noon(day))

    # ---- statistique recalculee de facon independante (une ligne boulangerie / type / jour)
    def line(self, site, code, ctype, day):
        self.go(site)
        node = self.node[code] if code in self.node else self.siege
        mv = [(m.movement_type, m.quantity, m.session_id, timezone.localtime(m.created_at).date())
              for m in ConsumableMovement.objects.filter(node=node, stock__consumable_type=ctype)]

        def signed(kind, qty):
            return qty if kind == 'ENTRY' else -qty
        initial = sum((signed(k, q) for k, q, _s, d in mv if d < day), D('0'))
        entry = sum((q for k, q, _s, d in mv if d == day and k == 'ENTRY'), D('0'))
        out_all = sum((q for k, q, _s, d in mv if d == day and k == 'EXIT'), D('0'))
        declared = sum((q for k, q, s, d in mv if d == day and k == 'EXIT' and s), D('0'))
        sacks = sum((s.flour_sacks_used for s in ProductionSession.objects.filter(node=node, date=day)), D('0'))
        cnt = ConsumableCount.objects.filter(node=node, consumable_type=ctype, count_date=day).first()
        stock = ConsumableStock.objects.filter(node=node, consumable_type=ctype).first()
        return {
            'initial': initial, 'entry': entry, 'out': out_all, 'declared': declared,
            'balance': initial + entry - out_all, 'sacks': sacks,
            'physical': cnt.physical_quantity if cnt else None, 'gap': cnt.gap if cnt else None,
            'stock_qty': stock.quantity if stock else D('0'),
        }

    def all_lines(self, site, codes=('K1', 'K2')):
        return {(c, t, d): self.line(site, c, t, d) for c in codes for t in TYPES
                for d in (self.d0, self.d1, self.d2)}

    def scenario(self):
        """3 jours, 2 boulangeries hors ligne + direction au cloud (valeurs fictives)."""
        self.go('cloud')
        # direction : achat 100 sacs a 30 000 (D0), 40 paquets de levure, 100 L d'huile
        self.move('SIEGE', 'FLOUR', 'ENTRY', '100', self.d0, price='30000')
        self.move('SIEGE', 'YEAST', 'ENTRY', '40', self.d0, price='1500')
        self.move('SIEGE', 'OIL', 'ENTRY', '100', self.d0, price='2500')
        self.dispatch('FLOUR', [('K1', '20'), ('K2', '10')], self.d0)
        self.dispatch('YEAST', [('K1', '4.5')], self.d0)
        # K1 hors ligne
        self.go('K1')
        self.move('K1', 'FLOUR', 'ENTRY', '5', self.d0, price='31000')           # achat local
        s = self.session('K1', self.d0, '4')
        self.move('K1', 'FLOUR', 'EXIT', '4', self.d0, session=s)
        self.move('K1', 'SALT', 'ENTRY', '2000', self.d0, price='1')
        self.move('K1', 'OIL', 'ENTRY', '10', self.d0, price='2600')
        s = self.session('K1', self.d1, '6')
        self.move('K1', 'FLOUR', 'EXIT', '6', self.d1, session=s)
        self.move('K1', 'YEAST', 'EXIT', '0.25', self.d1, session=s)
        self.move('K1', 'OIL', 'EXIT', '1.5', self.d1, session=s)
        self.move('K1', 'SALT', 'EXIT', '150', self.d1, session=s)
        self.move('K1', 'FLOUR', 'EXIT', '1.5', self.d1)                           # sortie hors fournee
        self.inventory('K1', self.d1, {'FLOUR': '22', 'OIL': '8.5'})
        # K2 hors ligne
        self.go('K2')
        s = self.session('K2', self.d0, '3')
        self.move('K2', 'FLOUR', 'EXIT', '3', self.d0, session=s)
        s = self.session('K2', self.d2, '2.5')
        self.move('K2', 'FLOUR', 'EXIT', '2.5', self.d2, session=s)
        self.inventory('K2', self.d2, {'FLOUR': '4'})


class IntrantsPostesVsCloud(Bench):
    def test_solde_de_chaque_poste_egal_au_cloud_apres_sync(self):
        """Scenario 2 boulangeries + direction sur 3 jours : toutes les lignes du jour (initial, entree,
        sortie, declare, solde, sacs, inventaire, ecart) et le stock courant sont identiques au poste et
        au cloud."""
        self.scenario()
        self.sync('K1'), self.sync('K2'), self.sync('K1'), self.sync('K2')
        cloud, k1, k2 = self.all_lines('cloud'), self.all_lines('K1', ('K1',)), self.all_lines('K2', ('K2',))
        for key, ligne in k1.items():
            self.assertEqual(ligne, cloud[key], key)
        for key, ligne in k2.items():
            self.assertEqual(ligne, cloud[key], key)
        # valeurs attendues a la main (K1 farine) : initial D0=0, entrees D0 = 20 (direction) + 5 (achat) ;
        # sorties D0 = 4 -> solde D0 = 21 ; D1 : sorties 6 + 1,5 -> 13,5
        d0 = cloud[('K1', 'FLOUR', self.d0)]
        self.assertEqual((d0['initial'], d0['entry'], d0['out'], d0['balance'], d0['sacks']),
                         (D('0'), D('25'), D('4'), D('21'), D('4')))
        d1 = cloud[('K1', 'FLOUR', self.d1)]
        self.assertEqual((d1['initial'], d1['out'], d1['declared'], d1['balance']),
                         (D('21'), D('7.5'), D('6'), D('13.5')))
        # L'ecart d'un inventaire est un INSTANTANE fige a la saisie : K1 comptait hors ligne AVANT d'avoir
        # recu les 20 sacs de la direction, son stock « systeme » valait donc 5-4-6-1,5 = -6,5 (negatif) et
        # l'ecart 22 - (-6,5) = 28,5, identique au poste et au cloud. Recalcule avec le solde complet (13,5)
        # il serait de 8,5 : une statistique d'ecart doit recalculer depuis les mouvements, pas lire `gap`.
        self.assertEqual((d1['physical'], d1['gap']), (D('22.000'), D('28.500')))
        self.assertEqual(d1['physical'] - d1['balance'], D('8.500'))
        self.assertEqual(cloud[('K1', 'YEAST', self.d0)]['entry'], D('4.5'))
        self.assertEqual(cloud[('K2', 'FLOUR', self.d2)]['sacks'], D('2.5'))

    def test_la_ligne_direction_D1_n_existe_qu_au_cloud_et_les_envois_s_apparient(self):
        """D1 = stock du noeud SIEGE : jamais descendu sur un poste (documente) ; chaque sortie direction
        a une entree boulangerie de meme quantite, et le poste recoit son entree."""
        self.scenario()
        self.sync('K1'), self.sync('K2')
        d1 = self.line('cloud', 'SIEGE', 'FLOUR', self.d0)
        self.assertEqual((d1['initial'], d1['entry'], d1['out'], d1['balance']), (D('0'), D('100'), D('30'), D('70')))
        for ctype in ('FLOUR', 'YEAST'):
            self.go('cloud')
            sorties = ConsumableMovement.objects.filter(node=self.siege, stock__consumable_type=ctype,
                                                        movement_type='EXIT')
            recues = ConsumableMovement.objects.filter(node__in=self.node.values(), stock__consumable_type=ctype,
                                                       node_origin='SIEGE', movement_type='ENTRY')
            self.assertEqual(sum(m.quantity for m in sorties), sum(m.quantity for m in recues), ctype)
        for site in ('K1', 'K2'):
            self.go(site)
            self.assertFalse(ConsumableMovement.objects.filter(node=self.siege).exists(), site)
            self.assertFalse(ConsumableStock.objects.filter(node=self.siege).exists(), site)
        self.go('K1')
        recu = ConsumableMovement.objects.get(node=self.node['K1'], stock__consumable_type='FLOUR', node_origin='SIEGE')
        self.assertEqual((recu.movement_type, recu.quantity, recu.unit_price), ('ENTRY', D('20'), D('30000')))
        self.go('K2')      # K2 ne recoit ni l'envoi de K1 ni la levure de K1
        self.assertEqual(ConsumableMovement.objects.filter(node_origin='SIEGE').count(), 1)

    def test_temoin_sans_le_pull_des_envois_direction_le_poste_diverge(self):
        """Temoin de sensibilite : sans application des mouvements descendus (comportement d'avant
        BUG-1111), le poste K1 ignore les 20 sacs envoyes par la direction (stock et solde faux)."""
        self.scenario()
        with mock.patch('sync.management.commands.sync_now._apply_pulled_consumable_movements', lambda *a, **k: 0):
            self.sync('K1'), self.sync('K1')
        poste, cloud = self.line('K1', 'K1', 'FLOUR', self.d0), self.line('cloud', 'K1', 'FLOUR', self.d0)
        self.assertEqual(cloud['balance'] - poste['balance'], D('20'))
        self.assertNotEqual(poste['stock_qty'], cloud['stock_qty'])

    def test_les_dates_d_origine_survivent_au_push_retarde(self):
        """Mouvement saisi le jour D0, pousse le jour D2 : au cloud il reste date de D0 (et non du jour
        d'arrivee). Un poste ancien sans `created_at` garde la date d'arrivee (defaut sur)."""
        self.go('K1')
        m = self.move('K1', 'FLOUR', 'ENTRY', '7', self.d0, price='1')
        payload, _data, _pulled = self.sync('K1')
        sent = [r for r in payload['records']['production.ConsumableMovement'] if r['id'] == str(m.pk)][0]
        self.assertTrue(sent['created_at'].startswith(self.d0.isoformat()))
        self.go('cloud')
        self.assertEqual(timezone.localtime(ConsumableMovement.objects.get(pk=m.pk).created_at).date(), self.d0)
        # poste ancien : pas de `created_at`
        old = {'id': str(uuid.uuid4()), 'node': 'K1', 'consumable_type': 'FLOUR', 'unit': '',
               'movement_type': 'ENTRY', 'quantity': '1', 'unit_price': '0', 'node_origin': 'K1'}
        r = self.api['K1'].post(PUSH, {'batch_id': str(uuid.uuid4()),
                                       'records': {'production.ConsumableMovement': [old]}}, format='json')
        self.assertEqual(r.data['results']['production.ConsumableMovement'][0]['status'], 'ACCEPTED')
        self.assertEqual(timezone.localtime(ConsumableMovement.objects.get(pk=old['id']).created_at).date(), self.today)
        # date future / absurde ignoree
        for bad in ((timezone.now() + timedelta(days=3)).isoformat(), '1999-01-01T00:00:00Z', 'pas une date'):
            rec = dict(old, id=str(uuid.uuid4()), created_at=bad)
            r = self.api['K1'].post(PUSH, {'batch_id': str(uuid.uuid4()),
                                           'records': {'production.ConsumableMovement': [rec]}}, format='json')
            self.assertEqual(r.data['results']['production.ConsumableMovement'][0]['status'], 'ACCEPTED', bad)
            self.assertEqual(timezone.localtime(ConsumableMovement.objects.get(pk=rec['id']).created_at).date(),
                             self.today, bad)


class IntrantsRejeuxEtCoupures(Bench):
    def test_push_rejoue_ne_double_aucun_mouvement_ni_stock(self):
        self.scenario()
        payload = None
        self.go('K1')
        payload = build_outbound_payload('K1')
        self.go('cloud')
        for _ in range(3):
            r = self.api['K1'].post(PUSH, dict(payload, batch_id=str(uuid.uuid4())), format='json')
            self.assertEqual(r.status_code, 200, r.content)
        k1 = self.node['K1']
        self.assertEqual(ConsumableMovement.objects.filter(node=k1).count(), 9 + 2)   # 9 poste + 2 envois direction
        self.assertEqual(ConsumableInventory.objects.filter(node=k1).count(), 1)
        self.assertEqual(ConsumableCount.objects.filter(node=k1).count(), 2)
        self.assertEqual(ProductionSession.objects.filter(node=k1).count(), 2)
        st = ConsumableStock.objects.get(node=k1, consumable_type='FLOUR')
        self.assertEqual(st.quantity, D('20') + D('5') - D('4') - D('6') - D('1.5'))

    def test_pull_rejoue_ne_double_aucun_envoi_direction(self):
        self.scenario()
        self.sync('K1')
        self.go('cloud')
        pulled = json.loads(self.api['K1'].get(PULL).content)
        self.go('K1')
        avant = ConsumableStock.objects.get(node=self.node['K1'], consumable_type='FLOUR').quantity
        for _ in range(4):
            apply_pull_response(pulled)
        self.assertEqual(ConsumableStock.objects.get(node=self.node['K1'], consumable_type='FLOUR').quantity, avant)
        self.assertEqual(ConsumableMovement.objects.filter(node_origin='SIEGE').count(), 2)   # FLOUR + YEAST

    def test_coupure_apres_le_push_avant_le_pull_reprise_sans_perte(self):
        """Le pull est perdu (coupure) : le cycle suivant le rattrape, le poste rejoint le cloud."""
        self.scenario()
        self.sync('K1', drop_pull=True)
        self.go('K1')
        self.assertFalse(ConsumableMovement.objects.filter(node_origin='SIEGE').exists())
        self.sync('K1')
        self.assertEqual(self.line('K1', 'K1', 'FLOUR', self.d1), self.line('cloud', 'K1', 'FLOUR', self.d1))

    def test_envoi_direction_apres_une_premiere_synchro_descend_au_cycle_suivant(self):
        self.scenario()
        self.sync('K1'), self.sync('K1')
        self.dispatch('FLOUR', [('K1', '3.5')], self.d2)
        self.sync('K1')
        self.assertEqual(self.line('K1', 'K1', 'FLOUR', self.d2), self.line('cloud', 'K1', 'FLOUR', self.d2))
        self.assertEqual(self.line('K1', 'K1', 'FLOUR', self.d2)['entry'], D('3.5'))
        self.sync('K1')      # rejeu : rien de plus
        self.assertEqual(self.line('K1', 'K1', 'FLOUR', self.d2)['entry'], D('3.5'))

    def test_donnees_d_une_autre_boulangerie_ne_descendent_pas(self):
        self.scenario()
        self.sync('K1'), self.sync('K2')
        self.go('cloud')
        d = json.loads(self.api['K2'].get(PULL).content)
        self.assertEqual({m['node'] for m in d['consumable_movements']}, {'K2'})
        self.assertNotIn('4.5', str(d['consumable_movements']))      # levure de K1
        for forbidden in ('inventor', 'ConsumableStock', 'SIEGE_STOCK'):
            self.assertNotIn(forbidden, json.dumps(d))


class ApplicationDefensive(Bench):
    def test_lignes_invalides_ignorees_une_par_une(self):
        self.go('K1')
        good = {'id': str(uuid.uuid4()), 'node': 'K1', 'consumable_type': 'OIL', 'unit': 'litres',
                'movement_type': 'ENTRY', 'quantity': '2.250', 'unit_price': '2500', 'description': 'x',
                'node_origin': 'SIEGE', 'created_at': noon(self.d0).isoformat()}
        bad = [dict(good, id='nope'), dict(good, id=str(uuid.uuid4()), node='K2'),
               dict(good, id=str(uuid.uuid4()), movement_type='AUTRE'),
               dict(good, id=str(uuid.uuid4()), quantity='abc'),
               dict(good, id=str(uuid.uuid4()), consumable_type='a b'),
               dict(good, id=str(uuid.uuid4()), unit_price='-1'), 'texte', None, 12]
        apply_pull_response({'node_code': 'K1', 'consumable_movements': bad + [good]})
        self.assertEqual(ConsumableMovement.objects.count(), 1)
        self.assertEqual(ConsumableStock.objects.get(node=self.node['K1'], consumable_type='OIL').quantity, D('2.250'))
        for junk in (None, 'x', 5, {}, [None]):
            apply_pull_response({'node_code': 'K1', 'consumable_movements': junk})
        self.assertEqual(ConsumableMovement.objects.count(), 1)
        # jamais re-pousse : node_origin != K1, is_synced reste vrai
        self.assertEqual(build_outbound_payload('K1')['records']['production.ConsumableMovement'], [])


class Facturier1112(Bench):
    def inv(self, code, **extra):
        rec = {'id': str(uuid.uuid4()), 'node': code, 'status': 'PENDING', 'payment_type': 'CASH',
               'team': 'A', 'order_total': '0', 'payment_amount': '0', 'node_origin': code,
               'invoice_date': self.d1.isoformat()}
        rec.update(extra)
        return rec

    def push_invoice(self, code, rec):
        r = self.api[code].post(PUSH, {'batch_id': str(uuid.uuid4()),
                                       'records': {'sales.Invoice': [rec]}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        res = r.data['results']['sales.Invoice'][0]
        return res['status'], res.get('reason')

    def test_facturier_et_livreur_conserves_au_cloud(self):
        from sales.models import Invoice
        fact = make_user(role='FACTURIER', node=self.node['K1'])
        liv = make_user(role='LIVREUR', node=self.node['K1'])
        rec = self.inv('K1', facturier=str(fact.pk), livreur=str(liv.pk))
        self.assertEqual(self.push_invoice('K1', rec)[0], 'ACCEPTED')
        i = Invoice.objects.get(pk=rec['id'])
        self.assertEqual((i.facturier_id, i.livreur_id), (fact.pk, liv.pk))

    def test_un_livreur_peut_etre_porte_par_le_champ_facturier(self):
        from sales.models import Invoice
        liv = make_user(role='LIVREUR', node=self.node['K1'])
        rec = self.inv('K1', facturier=str(liv.pk))
        self.assertEqual(self.push_invoice('K1', rec)[0], 'ACCEPTED')
        self.assertEqual(Invoice.objects.get(pk=rec['id']).facturier_id, liv.pk)

    def test_valeurs_invalides_donnent_null_sans_rejeter_la_facture(self):
        from sales.models import Invoice
        autre = make_user(role='FACTURIER', node=self.node['K2'])      # autre boulangerie
        for bad in (str(uuid.uuid4()), 'pas-un-uuid', 12, ['x'], '', None, str(autre.pk)):
            rec = self.inv('K1', facturier=bad)
            self.assertEqual(self.push_invoice('K1', rec)[0], 'ACCEPTED', bad)
            self.assertIsNone(Invoice.objects.get(pk=rec['id']).facturier_id, bad)
        sans_cle = self.inv('K1')
        self.assertEqual(self.push_invoice('K1', sans_cle)[0], 'ACCEPTED')
        self.assertIsNone(Invoice.objects.get(pk=sans_cle['id']).facturier_id)

    def test_direction_sans_rattachement_admise_et_rejeu_idempotent(self):
        from sales.models import Invoice
        rec = self.inv('K1', facturier=str(self.direction.pk))
        self.assertEqual(self.push_invoice('K1', rec)[0], 'ACCEPTED')
        self.assertEqual(self.push_invoice('K1', rec)[0], 'ACCEPTED')
        self.assertEqual(Invoice.objects.filter(pk=rec['id']).count(), 1)
        self.assertEqual(Invoice.objects.get(pk=rec['id']).facturier_id, self.direction.pk)

    def test_facture_existante_sans_facturier_le_recoit_sans_ecraser_ensuite(self):
        from sales.models import Invoice
        fact = make_user(role='FACTURIER', node=self.node['K1'])
        autre = make_user(role='FACTURIER', node=self.node['K1'])
        rec = self.inv('K1')
        self.push_invoice('K1', rec)
        self.push_invoice('K1', dict(rec, facturier=str(fact.pk)))
        self.assertEqual(Invoice.objects.get(pk=rec['id']).facturier_id, fact.pk)
        self.push_invoice('K1', dict(rec, facturier=str(autre.pk)))
        self.assertEqual(Invoice.objects.get(pk=rec['id']).facturier_id, fact.pk)

    def test_export_du_poste_porte_facturier_et_livreur(self):
        from sales.models import Invoice
        fact = make_user(role='FACTURIER', node=self.node['K1'])
        liv = make_user(role='LIVREUR', node=self.node['K1'])
        i = Invoice(node=self.node['K1'], facturier=fact, livreur=liv, team='A', node_origin='K1')
        i.save()
        rec = [r for r in build_outbound_payload('K1')['records']['sales.Invoice'] if r['id'] == str(i.pk)][0]
        self.assertEqual((rec['facturier'], rec['livreur']), (str(fact.pk), str(liv.pk)))
        Invoice.objects.filter(pk=i.pk).update(facturier=None, livreur=None)
        rec = [r for r in build_outbound_payload('K1')['records']['sales.Invoice'] if r['id'] == str(i.pk)][0]
        self.assertEqual((rec['facturier'], rec['livreur']), (None, None))


class InventaireStockSystemeNegatif(Bench):
    def test_comptage_avec_stock_systeme_negatif_accepte_physique_negatif_refuse(self):
        inv = {'id': str(uuid.uuid4()), 'node': 'K1', 'inventory_date': self.d1.isoformat(),
               'comment': '', 'node_origin': 'K1'}

        def cnt(physical, gap):
            return {'node': 'K1', 'inventory': inv['id'], 'consumable_type': 'FLOUR',
                    'count_date': self.d1.isoformat(), 'system_quantity': '-6.500',
                    'physical_quantity': physical, 'gap': gap, 'notes': ''}
        r = self.api['K1'].post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {
            'production.ConsumableInventory': [inv],
            'production.ConsumableCount': [cnt('22.000', '28.500')]}}, format='json')
        self.assertEqual(r.data['results']['production.ConsumableCount'][0]['status'], 'ACCEPTED')
        self.assertEqual(ConsumableCount.objects.get(node=self.node['K1']).gap, D('28.500'))
        inv2 = dict(inv, id=str(uuid.uuid4()), inventory_date=self.d0.isoformat())
        bad = dict(cnt('-1.000', '5.500'), inventory=inv2['id'], count_date=self.d0.isoformat())
        r = self.api['K1'].post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': {
            'production.ConsumableInventory': [inv2], 'production.ConsumableCount': [bad]}}, format='json')
        self.assertEqual(r.data['results']['production.ConsumableCount'][0]['status'], 'REJECTED')
