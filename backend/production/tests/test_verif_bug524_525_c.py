"""Vérification Dev C (testeur-production, 2026-11-22-c4) de BUG-524 et BUG-525.

BUG-524 : `recompute_cump` et entrées de même instant sur stock négatif.
  Cas : stock >= 0, stock négatif + 2 entrées (prix différents / identiques),
  entrée + sortie, 3 mouvements de même instant, --node, idempotence,
  simulation sans écriture, indépendance vis-à-vis des pk (--force) ET
  cohérence rejeu / CUMP EN LIGNE (`ConsumableMovement.save()`).
BUG-525 : `?node=` invalide pour le siège (reconciliation, flour_history,
  ConsumableCount.perform_create), gérant jamais en 400, siège sans paramètre
  inchangé.
Données fictives uniquement.
"""
import random
import uuid
from datetime import timedelta
from decimal import Decimal as Dc
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.models import ActivityLog
from core.testing import make_node
from core.tests.test_permissions_regression_2026_11_19 import cl
from core.tests.test_verif_isolation_a_c import IsoBase
from production.management.commands.recompute_cump import count_ambiguous_movements, replay_stock
from production.models import ConsumableCount, ConsumableMovement, ConsumableStock

ENTRY, EXIT = 'ENTRY', 'EXIT'


def run(*args):
    out = StringIO()
    call_command('recompute_cump', *args, stdout=out)
    return out.getvalue()


def ordered(stock):
    """Même ordre que la commande."""
    return list(ConsumableMovement.objects.filter(stock=stock)
                .order_by('created_at', 'movement_type', 'unit_price', 'quantity', 'pk'))


class Base524(TestCase):
    def setUp(self):
        self.k1 = make_node(code='K1')
        self.k2 = make_node(code='K2')
        self.t0 = timezone.now().replace(microsecond=0)

    def stock(self, node=None, qty='0.000', avg='0'):
        st = ConsumableStock.objects.create(node=node or self.k1, consumable_type='FLOUR',
                                            quantity=Dc(qty), unit='sac')
        ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc(avg))
        st.refresh_from_db()
        return st

    def mv(self, st, kind, qty, price, ts, pk=None):
        """Mouvement RÉEL (save() en ligne), puis horodatage forcé."""
        extra = {'id': pk} if pk else {}
        m = ConsumableMovement.objects.create(node=st.node, stock=st, movement_type=kind,
                                              quantity=Dc(qty), unit_price=Dc(price), **extra)
        ConsumableMovement.objects.filter(pk=m.pk).update(created_at=ts)
        return m

    def snapshot(self):
        return (
            list(ConsumableStock.objects.order_by('pk').values_list('pk', 'quantity', 'average_unit_cost')),
            list(ConsumableMovement.objects.order_by('pk').values_list('pk', 'unit_price', 'quantity', 'created_at')),
            ActivityLog.objects.count(),
        )


class Verif524(Base524):
    # --- scénarios demandés ------------------------------------------------
    def test_stock_positif_non_signale(self):
        st = self.stock()
        self.mv(st, ENTRY, '10', '100', self.t0 - timedelta(seconds=9))
        self.mv(st, ENTRY, '3', '100', self.t0)
        self.mv(st, ENTRY, '10', '300', self.t0)
        self.assertNotIn('même instant', run())

    def test_negatif_deux_entrees_meme_instant_prix_differents_signale(self):
        st = self.stock()
        self.mv(st, EXIT, '5', '0', self.t0 - timedelta(seconds=5))
        self.mv(st, ENTRY, '3', '100', self.t0)
        self.mv(st, ENTRY, '10', '200', self.t0)
        self.assertIn('même instant', run())
        self.assertEqual(count_ambiguous_movements(ordered(st)), 2)

    def test_negatif_prix_identiques_non_signale_et_commutatif(self):
        for first in ('3', '10'):
            ConsumableMovement.objects.all().delete()
            ConsumableStock.objects.all().delete()
            st = self.stock()
            self.mv(st, EXIT, '5', '0', self.t0 - timedelta(seconds=5))
            other = '10' if first == '3' else '3'
            self.mv(st, ENTRY, first, '150', self.t0)
            self.mv(st, ENTRY, other, '150', self.t0)
            self.assertNotIn('même instant', run())
            self.assertEqual(replay_stock(ordered(st))[0], Dc('150.0000'))
            st.refresh_from_db()
            self.assertEqual(st.average_unit_cost, Dc('150.0000'))

    def test_entree_et_sortie_meme_instant_signale(self):
        st = self.stock(qty='0')
        self.mv(st, ENTRY, '4', '100', self.t0 - timedelta(seconds=3))
        self.mv(st, EXIT, '1', '0', self.t0)
        self.mv(st, ENTRY, '2', '400', self.t0)
        out = run()
        self.assertIn('même instant', out)
        self.assertEqual(count_ambiguous_movements(ordered(st)), 2)

    def test_trois_mouvements_meme_instant_comptes(self):
        st = self.stock()
        self.mv(st, EXIT, '20', '0', self.t0 - timedelta(seconds=5))
        self.mv(st, ENTRY, '1', '100', self.t0)
        self.mv(st, ENTRY, '2', '100', self.t0)
        self.mv(st, ENTRY, '3', '250', self.t0)
        self.assertEqual(count_ambiguous_movements(ordered(st)), 3)
        self.assertIn('même instant', run())

    def test_force_independant_ordre_pk_trois_entrees(self):
        results = []
        for ids in ((1, 2, 3), (3, 2, 1), (2, 3, 1)):
            ConsumableMovement.objects.all().delete()
            ConsumableStock.objects.all().delete()
            st = self.stock()
            self.mv(st, EXIT, '20', '0', self.t0 - timedelta(seconds=5))
            specs = [('1', '100'), ('4', '250'), ('2', '400')]
            for i, (q, p) in zip(ids, specs):
                self.mv(st, ENTRY, q, p, self.t0, pk=uuid.UUID(int=i))
            ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('1'))
            # quantité en base = rejeu (pas de stock non tracé)
            ConsumableStock.objects.filter(pk=st.pk).update(quantity=Dc('-13'))
            run('--apply', '--force')
            st.refresh_from_db()
            results.append(st.average_unit_cost)
        self.assertEqual(len(set(results)), 1, results)

    def test_apply_sans_force_ignore_et_n_ecrit_rien(self):
        st = self.stock()
        self.mv(st, EXIT, '5', '0', self.t0 - timedelta(seconds=5))
        self.mv(st, ENTRY, '3', '100', self.t0)
        self.mv(st, ENTRY, '10', '200', self.t0)
        ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('1'))
        before = self.snapshot()
        out = run('--apply')
        self.assertIn('IGNORÉ', out)
        self.assertIn('0 corrigé', out)
        self.assertEqual(self.snapshot(), before)

    def test_simulation_sans_ecriture(self):
        st = self.stock()
        self.mv(st, EXIT, '5', '0', self.t0 - timedelta(seconds=5))
        self.mv(st, ENTRY, '3', '100', self.t0)
        self.mv(st, ENTRY, '10', '200', self.t0)
        ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('1'))
        before = self.snapshot()
        run()
        run('--dry-run')
        self.assertEqual(self.snapshot(), before)

    def test_option_node(self):
        for node in (self.k1, self.k2):
            st = self.stock(node=node)
            self.mv(st, EXIT, '5', '0', self.t0 - timedelta(seconds=5))
            self.mv(st, ENTRY, '3', '100', self.t0)
            self.mv(st, ENTRY, '10', '200', self.t0)
        out1 = run('--node', 'K1')
        self.assertIn('K1 FLOUR', out1)
        self.assertNotIn('K2 FLOUR', out1)
        self.assertIn('1 stock(s) examiné', out1)
        # --apply --force limité à K2 : K1 intact
        k1 = ConsumableStock.objects.get(node=self.k1)
        ConsumableStock.objects.filter(pk=k1.pk).update(average_unit_cost=Dc('7'))
        run('--apply', '--force', '--node', 'K2')
        k1.refresh_from_db()
        self.assertEqual(k1.average_unit_cost, Dc('7'))

    def test_idempotence_apres_force(self):
        st = self.stock()
        self.mv(st, EXIT, '5', '0', self.t0 - timedelta(seconds=5))
        self.mv(st, ENTRY, '3', '100', self.t0)
        self.mv(st, ENTRY, '10', '200', self.t0)
        ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('1'))
        run('--apply', '--force')
        st.refresh_from_db()
        first = (st.average_unit_cost,
                 list(ConsumableMovement.objects.order_by('pk').values_list('unit_price', flat=True)))
        logs = ActivityLog.objects.count()
        out = run('--apply', '--force')
        st.refresh_from_db()
        self.assertEqual(first, (st.average_unit_cost,
                                 list(ConsumableMovement.objects.order_by('pk').values_list('unit_price', flat=True))))
        self.assertIn('0 corrigé', out)
        self.assertEqual(ActivityLog.objects.count(), logs)

    # --- critique : rejeu vs CUMP EN LIGNE ---------------------------------
    def test_divergence_rejeu_vs_en_ligne_est_signalee(self):
        """Stock négatif, 1@100 et 10@200 au même instant. Le CUMP en ligne
        dépend de l'ordre d'ARRIVÉE réel ; le rejeu (prix croissant) peut donc
        différer du CUMP en base. L'avertissement doit alors couvrir le cas et
        `--apply` doit ignorer le stock sans --force."""
        res = {}
        for label, order in (('bas_puis_haut', [('1', '100'), ('10', '200')]),
                             ('haut_puis_bas', [('10', '200'), ('1', '100')])):
            ConsumableMovement.objects.all().delete()
            ConsumableStock.objects.all().delete()
            st = self.stock()
            self.mv(st, EXIT, '5', '0', self.t0 - timedelta(seconds=5))
            for q, p in order:
                self.mv(st, ENTRY, q, p, self.t0)
            st.refresh_from_db()
            online = st.average_unit_cost
            replay = replay_stock(ordered(st))[0]
            out = run('--apply')
            st.refresh_from_db()
            res[label] = (online, replay)
            if online.quantize(Dc('0.0001')) != replay:
                # divergence réelle : doit être signalée ET protégée
                self.assertIn('même instant', out, label)
                self.assertIn('IGNORÉ', out, label)
                self.assertEqual(st.average_unit_cost, online, label)
        # une des deux arrivées au moins diverge du rejeu (prix croissant) :
        diverge = [k for k, (o, r) in res.items() if o.quantize(Dc('0.0001')) != r]
        self.assertEqual(diverge, ['haut_puis_bas'], res)

    def test_propriete_non_signale_implique_rejeu_egal_cump_en_ligne(self):
        """Séquences aléatoires reproductibles (seed) de mouvements RÉELS,
        incluant des groupes d'entrées de même instant. Si l'avertissement ne
        se déclenche pas, le rejeu doit égaler le CUMP en ligne (et les prix
        de sortie)."""
        rnd = random.Random(524)
        non_signales = signales = 0
        for trial in range(60):
            ConsumableMovement.objects.all().delete()
            ConsumableStock.objects.all().delete()
            st = self.stock()
            t = self.t0 - timedelta(hours=1)
            for _ in range(rnd.randint(2, 6)):
                t += timedelta(seconds=1)
                kind = rnd.choice([ENTRY, ENTRY, EXIT])
                if kind == EXIT:
                    self.mv(st, EXIT, str(rnd.randint(1, 12)), '0', t)
                else:
                    for _i in range(rnd.choice([1, 1, 2, 3])):  # groupes de même instant
                        self.mv(st, ENTRY, str(rnd.randint(1, 9)), str(rnd.choice([100, 150, 200, 400])), t)
            st.refresh_from_db()
            mvs = ordered(st)
            avg, qty, exit_prices = replay_stock(mvs)
            self.assertEqual(qty, st.quantity)  # rejeu tracé
            if count_ambiguous_movements(mvs):
                signales += 1
                continue
            non_signales += 1
            self.assertLess(abs(avg - st.average_unit_cost), Dc('0.05'),
                            f"trial {trial} : rejeu {avg} != en ligne {st.average_unit_cost}")
            for m in mvs:
                if m.pk in exit_prices:
                    self.assertLess(abs(exit_prices[m.pk] - m.unit_price), Dc('0.05'), f"trial {trial} sortie")
        self.assertGreater(non_signales, 10)
        self.assertGreater(signales, 0)

    def test_trou_connu_stock_reel_negatif_non_trace(self):
        """Stock initial NÉGATIF non tracé (hors mouvements) : le rejeu part de 0,
        donc `count_ambiguous_movements` ne voit pas de stock négatif ; mais
        l'avertissement « quantité en base != rejouée » prend le relais et
        `--apply` ignore le stock sans --force (couverture par BUG-501)."""
        st = self.stock(qty='-10')
        self.mv(st, ENTRY, '3', '100', self.t0)   # save() en ligne : base_qty = 0
        self.mv(st, ENTRY, '10', '200', self.t0)
        mvs = ordered(st)
        self.assertEqual(count_ambiguous_movements(mvs), 0)  # non couvert par BUG-524...
        ConsumableStock.objects.filter(pk=st.pk).update(average_unit_cost=Dc('1'))
        out = run('--apply')
        self.assertIn('quantité en base', out)  # ... mais couvert par BUG-501
        self.assertIn('IGNORÉ', out)
        st.refresh_from_db()
        self.assertEqual(st.average_unit_cost, Dc('1'))


class Verif525(IsoBase):
    URL = '/api/production/sessions/reconciliation/'
    FLOUR = '/api/production/movements/flour_history/'
    COUNTS = '/api/production/counts/'

    def test_siege_zzz_400_francais(self):
        r = cl(self.u['DIRECTION']).get(f'{self.URL}?node=ZZZ')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data, {'detail': 'Boulangerie « ZZZ » introuvable.'})

    def test_siege_numerique_inexistant_400(self):
        for raw in ('999999', '0', '-1'):
            r = cl(self.u['DIRECTION']).get(f'{self.URL}?node={raw}')
            self.assertEqual(r.status_code, 400, raw)

    def test_tous_roles_siege(self):
        for role in ('ADMIN', 'DIRECTION', 'COMPTABLE'):
            c = cl(self.u[role])
            self.assertEqual(c.get(f'{self.URL}?node=ZZZ').status_code, 400, role)
            self.assertEqual(c.get(f'{self.URL}?node={self.k2.pk}').status_code, 200, role)

    def test_pk_et_code_acceptes_code_insensible_casse(self):
        c = cl(self.u['DIRECTION'])
        for raw in (self.k2.pk, self.k2.code, self.k2.code.lower()):
            r = c.get(f'{self.URL}?node={raw}')
            self.assertEqual(r.status_code, 200, raw)
            self.assertEqual(r.data['node'], self.k2.pk, raw)

    def test_gerant_parametre_ignore_jamais_400(self):
        c = cl(self.u['GERANT'])
        for raw in ('ZZZ', '999999', '', self.k2.code, "' OR 1=1 --", '9' * 40):
            r = c.get(self.URL, {'node': raw})
            self.assertEqual(r.status_code, 200, raw)
            self.assertEqual(r.data['node'], self.k1.pk, raw)

    def test_siege_sans_parametre_inchange(self):
        c = cl(self.u['DIRECTION'])
        r_all = c.get(self.URL)
        self.assertEqual(r_all.status_code, 200)
        self.assertIsNone(r_all.data['node'])
        r1 = c.get(f'{self.URL}?node={self.k1.pk}')
        r2 = c.get(f'{self.URL}?node={self.k2.pk}')
        for key in ('production_declared', 'sales', 'returns', 'gap'):
            self.assertEqual(r_all.data[key]['breads'], r1.data[key]['breads'] + r2.data[key]['breads'], key)
        self.assertEqual(set(r_all.data), set(r1.data))

    def test_siege_node_vide_traite_comme_absent(self):
        r = cl(self.u['DIRECTION']).get(f'{self.URL}?node=')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['node'])

    def test_flour_history(self):
        c = cl(self.u['DIRECTION'])
        self.assertEqual(c.get(f'{self.FLOUR}?node=ZZZ').status_code, 400)
        self.assertEqual(c.get(f'{self.FLOUR}?node=999999').status_code, 400)
        self.assertEqual(c.get(f'{self.FLOUR}?node={self.k2.pk}').status_code, 200)
        self.assertEqual(c.get(f'{self.FLOUR}?node={self.k2.code}').status_code, 200)
        self.assertEqual(c.get(self.FLOUR).status_code, 200)
        g = cl(self.u['GERANT'])
        self.assertEqual(g.get(f'{self.FLOUR}?node=ZZZ').status_code, 200)

    def test_count_create_node_non_numerique_400(self):
        payload = {'consumable_type': 'FAR', 'count_date': '2026-11-18', 'physical_quantity': '5'}
        c = cl(self.u['DIRECTION'])
        r = c.post(self.COUNTS, {**payload, 'node': 'ZZZ'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(ConsumableCount.objects.filter(physical_quantity=Dc('5')).count(), 0)
        r = c.post(self.COUNTS, {**payload, 'node': self.k2.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(ConsumableCount.objects.get(physical_quantity=Dc('5')).node_id, self.k2.pk)

    def test_count_create_gerant_node_ignore(self):
        payload = {'consumable_type': 'FAR', 'count_date': '2026-11-18', 'physical_quantity': '6'}
        r = cl(self.u['GERANT']).post(self.COUNTS, {**payload, 'node': 'ZZZ'}, format='json')
        self.assertIn(r.status_code, (201, 400), r.data)
        self.assertNotEqual(r.status_code, 500)
        if r.status_code == 201:
            self.assertEqual(ConsumableCount.objects.get(physical_quantity=Dc('6')).node_id, self.k1.pk)
