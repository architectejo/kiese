"""
Ronde b16 (testeur clients/commissions, 2026-11-23) : verification independante de BUG-993 (invoice_date
au push), BUG-994 (clients inconnus crees au pull en bloc) et BUG-995, perimetre du pull (CLAUDE.md 5.1),
poste neuf a 5 000 clients, facture hors ligne datee de la veille, ancien poste sans invoice_date.
Donnees FICTIVES uniquement. Code applicatif non modifie.
"""
import time
import uuid
from datetime import timedelta
from decimal import Decimal as D
from unittest import expectedFailure

from django.utils import timezone

from clients.models import Client
from clients.tests.test_clients_v2 import Base
from clients.tests.test_clients_v6 import node_api, push
from commissions.models import CommissionPeriod
from core.models import SystemNotification
from sales.models import Invoice
from sync.management.commands.sync_now import apply_pull_response, build_outbound_payload
from sync.models import DebtMovement


def cloud_rows(node_code, n, prefix='P', debt='1000.00'):
    return [{'id': str(uuid.uuid4()), 'code': f'{node_code}-{prefix}{i:05d}', 'current_debt': debt,
             'credit_limit': '50000.00' if i % 7 else '80000.00', 'category': 'NORMAL',
             'first_name': f'Prénom{i}', 'last_name': f'Nom{i % 50}', 'phone': f'09{i:08d}', 'address': '',
             'node': node_code, 'node_origin': node_code, 'commission_rate': '0.25',
             'cotisation_sociale': None, 'client_type': 'DETAILLANT', 'notes': '',
             'total_breads_received': 0} for i in range(n)]


class PosteNeuf5000(Base):
    N = 5000

    def test_creation_en_bloc_duree_idempotence_aucun_parasite(self):
        rows = cloud_rows('K1', self.N)
        dm0, notif0 = DebtMovement.objects.count(), SystemNotification.objects.count()
        t0 = time.perf_counter()
        apply_pull_response({'clients': rows})
        dt = time.perf_counter() - t0
        print(f"PERF b16 creation {self.N} clients au pull : {dt:.2f}s")
        self.assertLess(dt, 60)
        self.assertEqual(Client.objects.count(), self.N)
        self.assertEqual(Client.objects.values('code').distinct().count(), self.N)
        self.assertEqual(DebtMovement.objects.count(), dm0)
        self.assertEqual(SystemNotification.objects.count(), notif0)
        c = Client.objects.get(code='K1-P00007')
        self.assertEqual((c.credit_limit, c.current_debt, c.is_synced, c.node_id),
                         (D('80000.00'), D('1000.00'), True, self.k1.pk))
        self.assertEqual(str(c.id), rows[7]['id'])
        # le poste ne renvoie pas au cloud les clients qu'il vient de recevoir
        self.assertEqual(build_outbound_payload('K1')['records'].get('clients.Client', []), [])
        # rejeu : rien de plus, dette cloud rappliquee sans mouvement
        for r in rows[:3]:
            r['current_debt'] = '2500.00'
        t0 = time.perf_counter()
        apply_pull_response({'clients': rows})
        print(f"PERF b16 rejeu {self.N} clients : {time.perf_counter() - t0:.2f}s")
        self.assertEqual(Client.objects.count(), self.N)
        self.assertEqual(Client.objects.get(code='K1-P00001').current_debt, D('2500.00'))
        self.assertEqual(DebtMovement.objects.count(), dm0)

    def test_code_deja_pris_par_un_autre_client_local_n_ecrase_rien_et_aucun_doublon(self):
        local = self.mk(self.k1, 'Local', 'Hors ligne')
        Client.objects.filter(pk=local.pk).update(code='K1-P00001')
        apply_pull_response({'clients': cloud_rows('K1', 3)})
        self.assertEqual(Client.objects.filter(code='K1-P00001').count(), 1)
        self.assertEqual(Client.objects.get(code='K1-P00001').pk, local.pk)
        self.assertEqual(Client.objects.filter(code__startswith='K1-P0000').count(), 3)

    def test_deux_lignes_meme_code_dans_la_reponse_une_seule_creee(self):
        rows = cloud_rows('K1', 2)
        rows[1]['code'] = rows[0]['code']
        apply_pull_response({'clients': rows})
        self.assertEqual(Client.objects.filter(code=rows[0]['code']).count(), 1)

    def test_lignes_invalides_ignorees_sans_planter_les_valides_creees(self):
        rows = cloud_rows('K1', 4)
        rows[0]['node'] = 'ZZ'
        rows[1]['credit_limit'] = '-5'
        rows[2]['category'] = 'BIZARRE'
        apply_pull_response({'clients': rows})
        self.assertEqual(sorted(Client.objects.values_list('code', flat=True)), [rows[3]['code']])

    def test_dette_negative_epargne_conservee_a_la_creation(self):
        rows = cloud_rows('K1', 1, debt='-12000.00')
        apply_pull_response({'clients': rows})
        self.assertEqual(Client.objects.get(code=rows[0]['code']).current_debt, D('-12000.00'))

    def test_client_d_un_autre_noeud_deja_facture_cree_avec_son_noeud_d_origine(self):
        rows = cloud_rows('K3', 1, prefix='X')
        apply_pull_response({'clients': rows})
        self.assertEqual(Client.objects.get(code=rows[0]['code']).node_id, self.k3.pk)

    def test_cloud_ancien_sans_cles_additives_ne_cree_rien_mais_met_a_jour_les_connus(self):
        known = self.mk(self.k1, 'Connu', 'Nom')
        old_row = {'id': str(uuid.uuid4()), 'code': 'K1-OLD', 'current_debt': '5.00', 'credit_limit': '50000.00',
                   'category': 'NORMAL', 'first_name': 'A', 'last_name': 'B'}
        known_row = {'id': str(known.id), 'code': known.code, 'current_debt': '900.00',
                     'credit_limit': '50000.00', 'category': 'NORMAL', 'first_name': 'Connu', 'last_name': 'Nom'}
        apply_pull_response({'clients': [old_row, known_row]})
        self.assertFalse(Client.objects.filter(code='K1-OLD').exists())
        self.assertEqual(Client.objects.get(pk=known.pk).current_debt, D('900.00'))


class FactureHorsLigne(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.own = self.mk(self.k1, 'Own', 'Own')

    def rec(self, **kw):
        r = {'id': str(uuid.uuid4()), 'node': 'K1', 'client': str(self.own.id), 'status': 'DELIVERED',
             'payment_type': 'CASH', 'order_total': '25000', 'payment_amount': '0', 'node_origin': 'K1', 'team': 'A'}
        r.update(kw)
        return r

    def retro(self):
        return SystemNotification.objects.filter(title__startswith='Vente rétroactive').count()

    def test_facture_de_la_veille_poussee_le_lendemain_garde_la_veille(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        r = self.rec(invoice_date=yesterday.isoformat())
        self.assertEqual(push(self.n1, 'sales.Invoice', r)['status'], 'ACCEPTED')
        self.assertEqual(Invoice.objects.get(pk=r['id']).invoice_date, yesterday)

    def test_facture_du_mois_precedent_dans_periode_close_avertit_la_direction(self):
        d = timezone.localdate().replace(day=1) - timedelta(days=3)
        CommissionPeriod.objects.create(node=self.k1, month=d.month, year=d.year, is_closed=True)
        before = self.retro()
        r = self.rec(invoice_date=d.isoformat())
        self.assertEqual(push(self.n1, 'sales.Invoice', r)['status'], 'ACCEPTED')
        self.assertEqual(Invoice.objects.get(pk=r['id']).invoice_date, d)
        self.assertEqual(self.retro(), before + 1)

    def test_rejeu_du_meme_push_ne_duplique_ni_facture_ni_avertissement(self):
        d = timezone.localdate().replace(day=1) - timedelta(days=3)
        CommissionPeriod.objects.create(node=self.k1, month=d.month, year=d.year, is_closed=True)
        r = self.rec(invoice_date=d.isoformat())
        for _ in range(3):
            push(self.n1, 'sales.Invoice', r)
        self.assertEqual(Invoice.objects.filter(pk=r['id']).count(), 1)
        self.assertEqual(self.retro(), 1)

    def test_facture_du_jour_pas_d_avertissement(self):
        push(self.n1, 'sales.Invoice', self.rec(invoice_date=timezone.localdate().isoformat()))
        self.assertEqual(self.retro(), 0)

    def test_ancien_poste_sans_invoice_date_prend_le_jour_du_push(self):
        r = self.rec()
        self.assertEqual(push(self.n1, 'sales.Invoice', r)['status'], 'ACCEPTED')
        self.assertEqual(Invoice.objects.get(pk=r['id']).invoice_date, timezone.localdate())

    def test_dates_invalides_rejetees_sans_creer_de_facture(self):
        for bad in ('2999-01-01', '2026-13-45', '23/11/2026', '2019-12-31', 'hier', '２０２６-１１-２２', 12345,
                    (timezone.localdate() + timedelta(days=2)).isoformat()):
            r = self.rec(invoice_date=bad)
            self.assertEqual(push(self.n1, 'sales.Invoice', r)['status'], 'REJECTED', bad)
            self.assertFalse(Invoice.objects.filter(pk=r['id']).exists(), bad)

    def test_invoice_date_vide_ou_nulle_equivaut_a_absente(self):
        for empty in (None, ''):
            r = self.rec(invoice_date=empty)
            self.assertEqual(push(self.n1, 'sales.Invoice', r)['status'], 'ACCEPTED')
            self.assertEqual(Invoice.objects.get(pk=r['id']).invoice_date, timezone.localdate())

    def test_rejeu_avec_autre_date_ne_deplace_pas_la_facture_existante(self):
        d = timezone.localdate() - timedelta(days=2)
        r = self.rec(invoice_date=d.isoformat())
        push(self.n1, 'sales.Invoice', r)
        push(self.n1, 'sales.Invoice', dict(r, invoice_date=(d - timedelta(days=20)).isoformat()))
        self.assertEqual(Invoice.objects.get(pk=r['id']).invoice_date, d)

    def test_lot_sortant_exporte_la_date_et_aller_retour_exact(self):
        past = timezone.localdate() - timedelta(days=9)
        inv = Invoice.objects.create(node=self.k1, client=self.own, payment_type='CASH', status='DELIVERED',
                                     payment_amount=D('0.00'), node_origin='K1', team='A')
        Invoice.objects.filter(pk=inv.pk).update(invoice_date=past, is_synced=False)
        row = [x for x in build_outbound_payload('K1')['records']['sales.Invoice'] if x['id'] == str(inv.id)][0]
        self.assertEqual(row['invoice_date'], past.isoformat())
        Invoice.objects.filter(pk=inv.pk).delete()
        self.assertEqual(push(self.n1, 'sales.Invoice', row)['status'], 'ACCEPTED')
        self.assertEqual(Invoice.objects.get(pk=inv.pk).invoice_date, past)


class PerimetrePull(Base):
    def pulled_ids(self):
        return {x['id'] for x in node_api(self.k1).get('/api/sync/pull/').json()['clients']}

    def test_etat_actuel_pull_sans_client_des_autres_noeuds(self):
        other = self.mk(self.k3, 'Autre', 'Noeud')
        self.assertNotIn(str(other.id), self.pulled_ids())

    def test_client_d_un_autre_noeud_deja_facture_par_ce_poste_descend(self):
        other = self.mk(self.k3, 'Autre', 'Noeud')
        Invoice.objects.create(node=self.k1, client=other, payment_type='CASH', status='DELIVERED',
                               payment_amount=D('0.00'), node_origin='K1', team='A')
        self.assertIn(str(other.id), self.pulled_ids())

    @expectedFailure  # BUG-998
    def test_BUG_998_facturier_hors_ligne_peut_facturer_un_client_d_une_autre_boulangerie_jamais_facture(self):
        # CLAUDE.md 5.1 / remarque.md : un facturier peut rechercher et facturer les clients des autres
        # boulangeries. Hors ligne, le poste K1 n'a que ses clients et ceux deja factures : un client K3
        # jamais facture par K1 n'est pas dans le pull, donc absent de la recherche locale.
        other = self.mk(self.k3, 'Autre', 'Noeud')
        self.assertIn(str(other.id), self.pulled_ids())
