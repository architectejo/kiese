"""
Ronde b15 (testeur clients/commissions, 2026-11-23) : verification independante de BUG-981/982/984
(sync push d'identite : horloge en avance, notification dedoublonnee, dedoublonnage de lot sur UUID
normalise), puis balayage : dates de facture au push, pull d'un poste neuf (5 000 clients), recherche
sous charge, import Excel (accents, volume), caisse sociale close (BUG-953), permissions croisees.
Donnees FICTIVES uniquement. Code applicatif non modifie.
"""
import io
import time
import unicodedata
import uuid
from datetime import date, timedelta
from decimal import Decimal as D

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from clients.models import Client, SocialContribution, SocialDistribution
from clients.tests.test_clients_v2 import CL, CONTRIB, DISTRIB, Base, api, results
from clients.tests.test_clients_v6 import PUSH, COMMS, PERIODS, node_api, push
from commissions.models import ClientCommission, CommissionPeriod
from core.models import ActivityLog, Node, SystemNotification
from core.testing import make_bread_price
from sales.models import Invoice
from sync.management.commands.sync_now import apply_pull_response, build_outbound_payload
from sync.models import DebtMovement, SyncConflictLog


def push_batch(c, records):
    r = c.post(PUSH, {'batch_id': str(uuid.uuid4()), 'records': records}, format='json')
    assert r.status_code == 200, (r.status_code, getattr(r, 'data', None))
    return r.data['results']


class Identite(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.own = self.mk(self.k1, 'Own', 'Own', credit_limit=D('50000.00'))
        # edition du siege : plafond 90 000 (pose identity_updated_at)
        r = api(self.direction).patch(f'{CL}{self.own.pk}/', {'credit_limit': '90000'}, format='json')
        assert r.status_code == 200, r.data

    def cur(self):
        return Client.objects.get(pk=self.own.pk)

    def rec(self, **kw):
        r = {'id': str(self.own.id), 'node': 'K1', 'node_origin': 'K1', 'first_name': 'Own', 'last_name': 'Own'}
        r.update(kw)
        return r

    def conflits(self, kind):
        return SyncConflictLog.objects.filter(conflict_type=kind, object_id=str(self.own.id))

    def notifs(self):
        return SystemNotification.objects.filter(title="Modification de client ignorée")

    def obsolete(self, phone):
        Client.objects.filter(pk=self.own.pk).update(identity_updated_at=timezone.now())
        old = (timezone.now() - timedelta(hours=2)).isoformat()
        return push(self.n1, 'clients.Client', self.rec(phone=phone, updated_at=old))


class V981Horloge(Identite):
    def future(self, minutes, **kw):
        stamp = (timezone.now() + timedelta(minutes=minutes)).isoformat()
        return push(self.n1, 'clients.Client', self.rec(updated_at=stamp, **kw))

    def test_stamp_futur_applique_et_trace_avec_anciennes_valeurs(self):
        r = self.future(120, credit_limit='60000', phone='0899')
        self.assertEqual(r['status'], 'ACCEPTED')
        c = self.cur()
        self.assertEqual((c.credit_limit, c.phone), (D('60000.00'), '0899'))
        conf = self.conflits('HORLOGE_POSTE_EN_AVANCE')
        self.assertEqual(conf.count(), 1)
        self.assertEqual(conf.first().node, self.k1)
        self.assertIn("90000", conf.first().detail)  # valeur ecrasee conservee
        self.assertIn("60000", conf.first().detail)
        self.assertIn(self.own.code, conf.first().detail)

    def test_cle_identity_updated_at_future_aussi_tracee(self):
        stamp = (timezone.now() + timedelta(hours=3)).isoformat()
        push(self.n1, 'clients.Client', self.rec(identity_updated_at=stamp, credit_limit='61000'))
        self.assertEqual(self.cur().credit_limit, D('61000.00'))
        self.assertEqual(self.conflits('HORLOGE_POSTE_EN_AVANCE').count(), 1)

    def test_dans_la_tolerance_pas_de_trace(self):
        self.future(4, credit_limit='62000')
        self.assertEqual(self.cur().credit_limit, D('62000.00'))
        self.assertEqual(self.conflits('HORLOGE_POSTE_EN_AVANCE').count(), 0)

    def test_juste_au_dela_de_la_tolerance_trace(self):
        self.future(6, credit_limit='62500')
        self.assertEqual(self.conflits('HORLOGE_POSTE_EN_AVANCE').count(), 1)

    def test_stamp_futur_sans_changement_reel_ne_trace_rien(self):
        self.future(120, credit_limit='90000')  # identique au cloud
        self.assertEqual(self.conflits('HORLOGE_POSTE_EN_AVANCE').count(), 0)
        self.assertEqual(self.cur().credit_limit, D('90000.00'))

    def test_rejeu_du_meme_push_futur_ne_cree_pas_de_second_conflit(self):
        stamp = (timezone.now() + timedelta(hours=2)).isoformat()
        for _ in range(3):
            push(self.n1, 'clients.Client', self.rec(updated_at=stamp, credit_limit='60000'))
        self.assertEqual(self.conflits('HORLOGE_POSTE_EN_AVANCE').count(), 1)

    def test_non_empoisonnement_le_stamp_serveur_est_pose_pas_celui_du_poste(self):
        self.future(600, credit_limit='60000')
        self.assertLess(self.cur().identity_updated_at, timezone.now() + timedelta(minutes=1))
        # edition honnete du siege ensuite, puis push poste legitime mais plus ancien : ignore
        api(self.direction).patch(f'{CL}{self.own.pk}/', {'credit_limit': '75000'}, format='json')
        old = (timezone.now() - timedelta(minutes=30)).isoformat()
        push(self.n1, 'clients.Client', self.rec(credit_limit='55000', updated_at=old))
        self.assertEqual(self.cur().credit_limit, D('75000.00'))

    def test_champ_invalide_avec_stamp_futur_rejete_sans_trace(self):
        stamp = (timezone.now() + timedelta(hours=2)).isoformat()
        r = push(self.n1, 'clients.Client', self.rec(updated_at=stamp, credit_limit='-5'))
        self.assertEqual(r['status'], 'REJECTED')
        self.assertEqual(self.cur().credit_limit, D('90000.00'))
        self.assertEqual(self.conflits('HORLOGE_POSTE_EN_AVANCE').count(), 0)

    def test_dette_jamais_touchee_par_un_push_en_avance(self):
        Client.objects.filter(pk=self.own.pk).update(current_debt=D('1234.00'))
        self.future(120, credit_limit='60000', current_debt='0')
        self.assertEqual(self.cur().current_debt, D('1234.00'))

    def test_BUG_995_second_ecrasement_en_avance_perd_les_valeurs_ecrasees(self):
        # 1er ecrasement : 90 000 -> 60 000 (trace). Le siege remet 120 000 ; le poste (toujours en avance)
        # repousse 70 000 : la valeur 120 000 ecrasee doit etre conservee quelque part (BUG-981 : « conserver
        # les valeurs ecrasees »). Le dedoublonnage BUG-723 ne fait qu'incrementer `occurrences`.
        self.future(120, credit_limit='60000')
        api(self.direction).patch(f'{CL}{self.own.pk}/', {'credit_limit': '120000'}, format='json')
        self.future(120, credit_limit='70000')
        details = " ".join(self.conflits('HORLOGE_POSTE_EN_AVANCE').values_list('detail', flat=True))
        al = " ".join(ActivityLog.objects.values_list('details', flat=True)) if hasattr(ActivityLog, 'details') else ''
        self.assertTrue('120000' in details or '120000' in al,
                        "la valeur 120000 ecrasee par le 2e push en avance n'est conservee nulle part")


class V982Notification(Identite):
    def test_cinq_pushs_obsoletes_une_notification_un_conflit(self):
        for i in range(5):
            self.obsolete(f'080{i}')
        conf = self.conflits('IDENTITE_OBSOLETE')
        self.assertEqual(conf.count(), 1)
        self.assertEqual(conf.first().occurrences, 5)
        self.assertEqual(self.notifs().count(), 1)

    def test_deux_clients_deux_notifications(self):
        other = self.mk(self.k1, 'Autre', 'Autre')
        api(self.direction).patch(f'{CL}{other.pk}/', {'credit_limit': '80000'}, format='json')
        self.obsolete('0801')
        self.obsolete('0802')
        Client.objects.filter(pk=other.pk).update(identity_updated_at=timezone.now())
        old = (timezone.now() - timedelta(hours=2)).isoformat()
        push(self.n1, 'clients.Client', {'id': str(other.id), 'node': 'K1', 'node_origin': 'K1',
                                         'first_name': 'Autre', 'last_name': 'Autre', 'phone': '0777',
                                         'updated_at': old})
        self.assertEqual(self.notifs().count(), 2)

    def test_conflit_resolu_puis_nouvel_obsolete_renotifie(self):
        self.obsolete('0801')
        self.obsolete('0802')
        self.assertEqual(self.notifs().count(), 1)
        self.conflits('IDENTITE_OBSOLETE').update(resolved_at=timezone.now())
        self.obsolete('0803')
        self.assertEqual(self.notifs().count(), 2)
        self.assertEqual(self.conflits('IDENTITE_OBSOLETE').count(), 2)

    def test_notification_lue_ne_est_pas_recreee_tant_que_le_conflit_est_ouvert(self):
        self.obsolete('0801')
        if hasattr(SystemNotification, 'is_read'):
            self.notifs().update(is_read=True)
        self.obsolete('0802')
        self.assertEqual(self.notifs().count(), 1)

    def test_rejeu_a_valeurs_identiques_ni_conflit_ni_notification(self):
        Client.objects.filter(pk=self.own.pk).update(identity_updated_at=timezone.now())
        old = (timezone.now() - timedelta(hours=2)).isoformat()
        push(self.n1, 'clients.Client', self.rec(credit_limit='90000', updated_at=old))
        self.assertEqual(self.conflits('IDENTITE_OBSOLETE').count(), 0)
        self.assertEqual(self.notifs().count(), 0)

    def test_le_code_d_un_client_prefixe_d_un_autre_ne_masque_pas_sa_notification(self):
        # « client K1-0001 » ne doit pas etre confondu avec « client K1-00010 » : la recherche porte sur
        # « client <code> » suivi d'un espace.
        a = self.mk(self.k1, 'A', 'A')
        b = self.mk(self.k1, 'B', 'B')
        Client.objects.filter(pk=a.pk).update(code='K1-9001', identity_updated_at=timezone.now())
        Client.objects.filter(pk=b.pk).update(code='K1-90010', identity_updated_at=timezone.now())
        old = (timezone.now() - timedelta(hours=2)).isoformat()
        for c, ph in ((a, '1'), (a, '2'), (b, '3')):
            push(self.n1, 'clients.Client', {'id': str(c.id), 'node': 'K1', 'node_origin': 'K1',
                                             'first_name': c.first_name, 'last_name': c.last_name,
                                             'phone': ph, 'updated_at': old})
        self.assertEqual(self.notifs().count(), 2)


class V984LotUUID(Identite):
    def test_variantes_de_casse_tirets_accolades_un_seul_client_le_premier_gagne(self):
        u = uuid.uuid4()
        variants = [str(u).upper(), u.hex, '{' + str(u) + '}']
        base = {'node': 'K1', 'node_origin': 'K1', 'last_name': 'Zz'}
        recs = [dict(base, id=str(u), first_name='Premier', code='K1-8001')]
        recs += [dict(base, id=v, first_name=f'Intrus{i}', code=f'K1-800{i + 2}') for i, v in enumerate(variants)]
        res = push_batch(self.n1, {'clients.Client': recs})['clients.Client']
        self.assertTrue(all(x['status'] == 'ACCEPTED' for x in res), res)
        self.assertEqual(Client.objects.filter(pk=u).count(), 1)
        self.assertEqual(Client.objects.get(pk=u).first_name, 'Premier')
        self.assertFalse(Client.objects.filter(first_name__startswith='Intrus').exists())

    def test_ordre_inverse_la_forme_non_canonique_en_premier_gagne(self):
        u = uuid.uuid4()
        base = {'node': 'K1', 'node_origin': 'K1', 'last_name': 'Zz'}
        recs = [dict(base, id=str(u).upper(), first_name='Majuscule', code='K1-8101'),
                dict(base, id=str(u), first_name='Minuscule', code='K1-8102')]
        push_batch(self.n1, {'clients.Client': recs})
        self.assertEqual(Client.objects.get(pk=u).first_name, 'Majuscule')

    def test_deux_ids_reellement_differents_dans_le_lot_sont_crees_tous_deux(self):
        recs = [{'id': str(uuid.uuid4()), 'node': 'K1', 'node_origin': 'K1', 'first_name': f'N{i}',
                 'last_name': 'Zz', 'code': f'K1-82{i:02d}'} for i in range(3)]
        push_batch(self.n1, {'clients.Client': recs})
        self.assertEqual(Client.objects.filter(code__startswith='K1-82').count(), 3)

    def test_id_non_uuid_dans_le_lot_rejete_sans_planter_le_dedoublonnage(self):
        recs = [{'id': 'pas-un-uuid', 'node': 'K1', 'first_name': 'X', 'last_name': 'Y'},
                {'id': 'pas-un-uuid', 'node': 'K1', 'first_name': 'X', 'last_name': 'Y'}]
        res = push_batch(self.n1, {'clients.Client': recs})['clients.Client']
        self.assertEqual([x['status'] for x in res], ['REJECTED', 'ACCEPTED'])  # 2e = rejeu (deja traite)

    # --- AUTRES modeles du lot : ids dupliques en casse/format different ---
    def test_debt_movement_variantes_d_id_comptabilise_une_seule_fois(self):
        u = uuid.uuid4()
        mv = {'client': str(self.own.id), 'amount': '500', 'kind': 'ORDER'}
        recs = [dict(mv, id=str(u)), dict(mv, id=str(u).upper()), dict(mv, id=u.hex), dict(mv, id='{' + str(u) + '}')]
        res = push_batch(self.n1, {'sync.DebtMovement': recs})['sync.DebtMovement']
        self.assertTrue(all(x['status'] == 'ACCEPTED' for x in res), res)
        self.assertEqual(DebtMovement.objects.filter(pk=u).count(), 1)
        self.assertEqual(self.cur().current_debt, D('500.00'))

    def test_debt_movement_meme_id_autre_montant_rejete_et_journalise(self):
        u = uuid.uuid4()
        mv = {'client': str(self.own.id), 'kind': 'ORDER'}
        recs = [dict(mv, id=str(u), amount='500'), dict(mv, id=str(u).upper(), amount='999')]
        res = push_batch(self.n1, {'sync.DebtMovement': recs})['sync.DebtMovement']
        self.assertEqual([x['status'] for x in res], ['ACCEPTED', 'REJECTED'])
        self.assertEqual(self.cur().current_debt, D('500.00'))
        self.assertTrue(SyncConflictLog.objects.filter(conflict_type='MOUVEMENT_IMMUABLE_MODIFIE').exists())

    def test_invoice_variantes_d_id_une_seule_facture(self):
        u = uuid.uuid4()
        inv = {'node': 'K1', 'client': str(self.own.id), 'status': 'PENDING', 'payment_type': 'CASH',
               'order_total': '1000', 'payment_amount': '0', 'node_origin': 'K1', 'team': 'A'}
        recs = [dict(inv, id=str(u)), dict(inv, id=str(u).upper(), order_total='2000'), dict(inv, id=u.hex)]
        res = push_batch(self.n1, {'sales.Invoice': recs})['sales.Invoice']
        self.assertTrue(all(x['status'] == 'ACCEPTED' for x in res), res)
        self.assertEqual(Invoice.objects.filter(pk=u).count(), 1)
        self.assertEqual(Invoice.objects.get(pk=u).order_total, D('1000.00'))  # le premier

    def test_cotisation_variantes_d_id_une_seule_ligne(self):
        u = uuid.uuid4()
        rec = {'client': str(self.own.id), 'node': 'K1', 'month': 5, 'year': 2026, 'amount': '2000',
               'node_origin': 'K1'}
        recs = [dict(rec, id=str(u)), dict(rec, id=str(u).upper())]
        res = push_batch(self.n1, {'clients.SocialContribution': recs})['clients.SocialContribution']
        self.assertTrue(all(x['status'] == 'ACCEPTED' for x in res), res)
        self.assertEqual(SocialContribution.objects.filter(client=self.own, month=5, year=2026).count(), 1)

    def test_lignes_de_facture_pk_entiere_donc_hors_sujet(self):
        # InvoiceLine / lignes de transfert / lignes de fournee : PK entieres, pas d'UUID a normaliser.
        from sales.models import InvoiceLine
        self.assertIn(InvoiceLine._meta.pk.get_internal_type(), ('BigAutoField', 'AutoField'))


class V993DateFacture(Identite):
    def _facture_ancienne(self):
        bp = make_bread_price(category='MOYEN', unit_price=500)
        inv = Invoice.objects.create(node=self.k1, client=self.own, payment_type='CASH', status='DELIVERED',
                                     payment_amount=D('0.00'), node_origin='K1', team='A')
        past = date.today() - timedelta(days=40)
        Invoice.objects.filter(pk=inv.pk).update(invoice_date=past, is_synced=False, order_total=D('25000.00'))
        return inv, past

    def test_BUG_993_le_lot_sortant_porte_la_date_de_la_facture(self):
        inv, past = self._facture_ancienne()
        rows = build_outbound_payload('K1')['records']['sales.Invoice']
        row = [r for r in rows if r['id'] == str(inv.id)][0]
        self.assertEqual(str(row.get('invoice_date')), past.isoformat())

    def test_BUG_993_facture_poussee_au_cloud_garde_sa_date_du_poste(self):
        # un poste hors ligne pousse une facture du mois passe : elle doit rester dans le mois d'origine
        # (sinon elle est comptee dans la periode de commission du jour du push).
        past = date.today() - timedelta(days=40)
        u = uuid.uuid4()
        rec = {'id': str(u), 'node': 'K1', 'client': str(self.own.id), 'status': 'DELIVERED',
               'payment_type': 'CASH', 'order_total': '25000', 'payment_amount': '0', 'node_origin': 'K1',
               'team': 'A', 'invoice_date': past.isoformat()}
        r = push(self.n1, 'sales.Invoice', rec)
        self.assertEqual(r['status'], 'ACCEPTED')
        self.assertEqual(Invoice.objects.get(pk=u).invoice_date, past)


class PullPosteNeuf(Base):
    N = 5000

    def seed(self):
        cl = [Client(code=f"K1-P{i:05d}", first_name=f"Prénom{i}", last_name=f"Nom{i % 50}", node=self.k1,
                     node_origin='K1', credit_limit=D('50000.00') if i % 7 else D('80000.00'),
                     current_debt=D('1000.00'), phone=f"09{i:08d}") for i in range(self.N)]
        Client.objects.bulk_create(cl, batch_size=500)

    def test_pull_5000_clients_duree_taille_curseur(self):
        self.seed()
        n1 = node_api(self.k1)
        t0 = time.perf_counter()
        r = n1.get('/api/sync/pull/')
        dt = time.perf_counter() - t0
        self.assertEqual(r.status_code, 200)
        rows = r.json()['clients']
        size = len(r.content)
        print(f"PERF pull {self.N} clients : {dt:.2f}s, {size / 1e6:.2f} Mo, {len(rows)} lignes")
        self.assertEqual(len(rows), self.N)
        self.assertEqual(len({x['id'] for x in rows}), self.N)
        self.assertLess(dt, 10)
        # curseur : second pull sans modification = 0 client
        cur = r.json()['since_client_debt']
        r2 = n1.get('/api/sync/pull/', {'since_client_debt': cur})
        self.assertEqual(r2.json()['clients'], [])
        # un client modifie apres le curseur redescend seul
        c = Client.objects.filter(code='K1-P00042').first()
        Client.objects.filter(pk=c.pk).update(updated_at=timezone.now() + timedelta(seconds=1))
        r3 = n1.get('/api/sync/pull/', {'since_client_debt': cur})
        self.assertEqual([x['code'] for x in r3.json()['clients']], ['K1-P00042'])

    def test_pull_pas_de_n_plus_1(self):
        self.seed()
        n1 = node_api(self.k1)
        n1.get('/api/sync/pull/')  # echauffement (premiere requete : jeton, config)
        with CaptureQueriesContext(connection) as big:
            n1.get('/api/sync/pull/')
        Client.objects.filter(code__gte='K1-P00100').delete()
        with CaptureQueriesContext(connection) as small:
            n1.get('/api/sync/pull/')
        self.assertEqual(len(big), len(small))

    def test_pull_ne_descend_pas_les_clients_des_autres_noeuds_sans_facture(self):
        self.seed()
        other = self.mk(self.k3, 'Autre', 'Noeud')
        rows = node_api(self.k1).get('/api/sync/pull/').json()['clients']
        self.assertNotIn(str(other.id), {x['id'] for x in rows})

    def test_BUG_994_poste_neuf_recoit_ses_clients_identite_et_plafond(self):
        # poste neuf = base locale sans aucun client : apres le pull, il doit les avoir (SYNC.md §1 :
        # « Client créés par d'autres nœuds (lecture) » descendent) avec identite + plafond.
        self.seed()
        payload = node_api(self.k1).get('/api/sync/pull/').json()
        Client.objects.all().delete()  # simule une base locale vide
        apply_pull_response(payload)
        self.assertEqual(Client.objects.count(), self.N)
        c = Client.objects.get(code='K1-P00007')
        self.assertEqual((c.first_name, c.credit_limit), ('Prénom7', D('50000.00')))

    def test_poste_existant_recoit_identite_et_plafond_du_cloud(self):
        c = self.mk(self.k1, 'Ancien', 'Nom', credit_limit=D('50000.00'))
        apply_pull_response({'clients': [{
            'id': str(c.id), 'code': c.code, 'current_debt': '700.00', 'credit_limit': '95000.00',
            'category': 'NORMAL', 'first_name': 'Nouveau', 'last_name': 'Nom', 'phone': '0811', 'address': 'Av X'}]})
        c.refresh_from_db()
        self.assertEqual((c.first_name, c.credit_limit, c.current_debt, c.phone), ('Nouveau', D('95000.00'), D('700.00'), '0811'))

    def test_application_de_5000_lignes_sur_poste_existant_duree(self):
        self.seed()
        payload = node_api(self.k1).get('/api/sync/pull/').json()
        for row in payload['clients']:
            row['current_debt'] = '1500.00'
        t0 = time.perf_counter()
        apply_pull_response(payload)
        dt = time.perf_counter() - t0
        print(f"PERF apply_pull {self.N} clients : {dt:.2f}s")
        self.assertEqual(Client.objects.filter(current_debt=D('1500.00')).count(), self.N)
        self.assertLess(dt, 120)


class RechercheSousCharge(Base):
    def setUp(self):
        super().setUp()
        cl = []
        for i in range(5000):
            first = 'Élodie' if i % 50 == 0 else f'Prenom{i}'
            cl.append(Client(code=f"K3-S{i:05d}", first_name=first, last_name=f"Nom{i % 40}", node=self.k3,
                             node_origin='K3', phone=f"08{i:08d}"))
        Client.objects.bulk_create(cl, batch_size=500)

    def test_recherche_sans_accent_et_majuscules_trouve_100_et_reste_rapide(self):
        for term in ('elodie', 'ELODIE', 'Élodie', 'élod'):
            t0 = time.perf_counter()
            r = api(self.f1).get(CL, {'search': term, 'page_size': 500})
            dt = time.perf_counter() - t0
            self.assertEqual(r.status_code, 200)
            total = r.data.get('count', len(results(r))) if isinstance(r.data, dict) else len(r.data)
            self.assertEqual(total, 100, term)
            print(f"PERF recherche {term!r} : {dt * 1000:.0f} ms")
            self.assertLess(dt, 3)

    def test_recherche_par_code_exact_en_tete_et_requetes_successives(self):
        durs = []
        for i in range(0, 5000, 250):
            code = f"K3-S{i:05d}"
            t0 = time.perf_counter()
            r = api(self.f1).get(CL, {'search': code})
            durs.append(time.perf_counter() - t0)
            self.assertEqual(results(r)[0]['code'], code)
        print(f"PERF 20 recherches par code : max {max(durs) * 1000:.0f} ms")
        self.assertLess(max(durs), 3)

    def test_facturier_k1_trouve_client_k3_par_telephone_partiel_sous_charge(self):
        r = api(self.f1).get(CL, {'search': '0800004999'})
        self.assertEqual([x['code'] for x in results(r)], ['K3-S04999'])

    def test_termes_hostiles_jamais_500(self):
        for term in ('%', '_', "'; DROP TABLE clients_client;--", 'é' * 200, '\x00', '😀'):
            r = api(self.f1).get(CL, {'search': term})
            self.assertIn(r.status_code, (200, 400), term)


class ImportExcel(Base):
    def _xlsx(self, names, sheet='CL-K1 TABO'):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        ws = wb.create_sheet(sheet)
        ws.append(['DATE', 'CODE', 'NOM'])
        for n in names:
            ws.append(['2026-11-01', 'C', n])
        buf = io.BytesIO()
        wb.save(buf)
        return SimpleUploadedFile('fictif.xlsx', buf.getvalue(),
                                  content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_nfd_et_nfc_sont_le_meme_client(self):
        nfc = unicodedata.normalize('NFC', 'José Mbemba')
        nfd = unicodedata.normalize('NFD', 'José Mbemba')
        r = api(self.direction).post(CL + 'import_excel/', {'file': self._xlsx([nfc, nfd])}, format='multipart')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['created'], 1)
        r = api(self.direction).post(CL + 'import_excel/', {'file': self._xlsx([nfd, 'JOSÉ MBEMBA'])}, format='multipart')
        self.assertEqual(r.data['created'], 0)

    def test_doublons_dans_le_fichier_comptes_une_fois(self):
        r = api(self.direction).post(CL + 'import_excel/', {'file': self._xlsx(['A Un', 'A Un', 'a un', 'B Deux'])},
                                     format='multipart')
        self.assertEqual(r.data['created'], 2)
        self.assertEqual(r.data['report'][0]['already_existing'], 2)

    def test_volume_3000_lignes_codes_uniques_et_duree(self):
        names = [f"Prénom{i} Nom{i}" for i in range(3000)]
        t0 = time.perf_counter()
        r = api(self.direction).post(CL + 'import_excel/', {'file': self._xlsx(names)}, format='multipart')
        dt = time.perf_counter() - t0
        print(f"PERF import 3000 lignes : {dt:.2f}s")
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertEqual(r.data['created'], 3000)
        codes = list(Client.objects.filter(node=self.k1).values_list('code', flat=True))
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(all(c.startswith('K1-') for c in codes))
        self.assertLess(dt, 120)

    def test_gerant_et_facturier_refuses(self):
        for u in (self.g1, self.f1, self.l1):
            r = api(u).post(CL + 'import_excel/', {'file': self._xlsx(['X Y'])}, format='multipart')
            self.assertEqual(r.status_code, 403)
        self.assertEqual(Client.objects.count(), 0)

    def test_noms_exotiques_apostrophe_tiret_et_emoji(self):
        r = api(self.direction).post(CL + 'import_excel/', {'file': self._xlsx(
            ["N'Kosi Ma-Kiese", "Œuvre Çelik", "Zoé 😀 Test"])}, format='multipart')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertEqual(r.data['created'], 3)

    def test_fichier_non_excel_400_en_francais(self):
        f = SimpleUploadedFile('x.xlsx', b'ceci n est pas un classeur', content_type='application/octet-stream')
        r = api(self.direction).post(CL + 'import_excel/', {'file': f}, format='multipart')
        self.assertEqual(r.status_code, 400)

    def test_dry_run_n_ecrit_rien_meme_avec_volume(self):
        r = api(self.direction).post(CL + 'import_excel/', {'file': self._xlsx([f"P{i} N{i}" for i in range(500)]),
                                                            'dry_run': 'true'}, format='multipart')
        self.assertEqual((r.data['created'], r.data['report'][0]['to_import']), (0, 500))
        self.assertEqual(Client.objects.count(), 0)


class CaisseSocialeCloturee(Base):
    def setUp(self):
        super().setUp()
        self.cl = self.mk(self.k1, 'Soc', 'Ial')
        self.dist = SocialDistribution.objects.create(node=self.k1, year=2026, tarif=D('700.00'), is_closed=True)
        self.co = SocialContribution.objects.create(client=self.cl, node=self.k1, month=3, year=2026,
                                                    amount=D('2000.00'), is_paid=True)

    def test_BUG_953_toujours_a_clarifier_etat_actuel_patch_et_toggle_acceptes(self):
        # BUG-953 reste A CLARIFIER : on documente l'etat actuel sans le qualifier de defaut.
        r = api(self.g1).patch(f'{CONTRIB}{self.co.pk}/', {'is_paid': False}, format='json')
        self.assertEqual(r.status_code, 200)
        r = api(self.g1).post(f'{CONTRIB}{self.co.pk}/toggle_paid/')
        self.assertEqual(r.status_code, 200)

    def test_angles_voisins_suppression_et_creation_en_annee_close_meme_comportement(self):
        r = api(self.g1).delete(f'{CONTRIB}{self.co.pk}/')
        d_status = r.status_code
        r2 = api(self.g1).post(CONTRIB, {'client': str(self.cl.pk), 'month': 4, 'year': 2026, 'amount': '2000'},
                               format='json')
        r3 = api(self.g1).post(CONTRIB + 'bulk_create_month/', {'month': 5, 'year': 2026}, format='json')
        print(f"INFO BUG-953 voisins : DELETE={d_status} CREATE={r2.status_code} BULK={r3.status_code}")
        self.assertIn(d_status, (204, 400, 403))

    def test_distribution_close_refuse_toujours_ses_lignes_et_la_reouverture_par_gerant(self):
        r = api(self.g1).patch(f'{DISTRIB}{self.dist.pk}/', {'is_closed': False}, format='json')
        self.assertIn(r.status_code, (400, 403))
        self.dist.refresh_from_db()
        self.assertTrue(self.dist.is_closed)
        r = api(self.g1).post(f'{DISTRIB}{self.dist.pk}/auto_populate_lines/')
        self.assertIn(r.status_code, (400, 403))
        r = api(self.g1).post(f'{DISTRIB}{self.dist.pk}/refresh_indices/')
        self.assertIn(r.status_code, (400, 403))

    def test_push_poste_d_une_cotisation_en_annee_close_meme_regle_que_rest(self):
        # le poste pousse is_paid=False sur une cotisation payee dont la distribution est close
        n1 = node_api(self.k1)
        r = push(n1, 'clients.SocialContribution', {
            'id': str(self.co.id), 'client': str(self.cl.id), 'node': 'K1', 'month': 3, 'year': 2026,
            'amount': '2000', 'is_paid': False, 'node_origin': 'K1'})
        self.co.refresh_from_db()
        print(f"INFO push cotisation annee close : {r['status']} is_paid={self.co.is_paid}")
        self.assertIn(r['status'], ('ACCEPTED', 'REJECTED'))


class PermissionsCroisees(Base):
    def setUp(self):
        super().setUp()
        self.k2 = Node.objects.get_or_create(code='K2', defaults={'name': 'K2 COQ'})[0]
        self.c2 = self.mk(self.k2, 'Chez', 'KDeux', credit_limit=D('50000.00'))
        self.co2 = SocialContribution.objects.create(client=self.c2, node=self.k2, month=3, year=2026,
                                                     amount=D('2000.00'))
        self.period2 = CommissionPeriod.objects.create(node=self.k2, month=10, year=2026)
        self.cm2 = ClientCommission.objects.create(
            period=self.period2, client=self.c2, order_value=D('100000.00'), commission_gross=D('25000.00'),
            net_payable=D('25000.00'), node_origin='K2')

    def test_gerant_k1_n_a_aucune_prise_sur_le_client_k2(self):
        g = api(self.g1)
        cid = self.c2.pk
        self.assertEqual(g.get(f'{CL}{cid}/').status_code, 404)
        self.assertEqual(g.patch(f'{CL}{cid}/', {'credit_limit': '1'}, format='json').status_code, 404)
        self.assertEqual(g.delete(f'{CL}{cid}/').status_code, 404)
        self.assertEqual(g.post(f'{CL}{cid}/recalculate_category/').status_code, 404)
        self.assertEqual(g.get(f'{CL}{cid}/history/').status_code, 404)
        self.assertEqual(results(g.get(CL, {'search': 'KDeux'})), [])
        for url in ('bulk_delete/', 'bulk_move/'):
            r = g.post(CL + url, {'ids': [str(cid)], 'node': self.k1.pk}, format='json')
            self.assertEqual(r.status_code, 403, url)
        self.c2.refresh_from_db()
        self.assertEqual(self.c2.credit_limit, D('50000.00'))
        self.assertEqual(self.c2.node_id, self.k2.pk)

    def test_gerant_k1_ne_voit_ni_cotisation_ni_commission_ni_periode_k2(self):
        g = api(self.g1)
        self.assertEqual(g.get(f'{CONTRIB}{self.co2.pk}/').status_code, 404)
        self.assertEqual(g.post(f'{CONTRIB}{self.co2.pk}/toggle_paid/').status_code, 404)
        self.assertEqual(g.get(f'{COMMS}{self.cm2.pk}/').status_code, 404)
        self.assertEqual(g.get(f'{PERIODS}{self.period2.pk}/').status_code, 404)
        self.assertEqual(results(g.get(COMMS, {'period': str(self.period2.pk)})), [])
        for u in (f'{COMMS}{self.cm2.pk}/mark_paid/', f'{COMMS}{self.cm2.pk}/set_manuel/'):
            r = g.post(u, {}, format='json') if 'mark' in u else g.patch(u, {'net_payable': '1'}, format='json')
            self.assertIn(r.status_code, (403, 404), u)
        self.assertEqual(g.post(PERIODS + 'generate/', {'node': self.k2.pk, 'month': 10, 'year': 2026},
                                format='json').status_code, 403)
        self.assertEqual(g.get(COMMS + 'payroll_listing/', {'period': str(self.period2.pk)}).status_code, 403)
        self.cm2.refresh_from_db()
        self.assertFalse(self.cm2.is_paid)
        self.assertEqual(self.cm2.net_payable, D('25000.00'))

    def test_gerant_k1_ne_cree_pas_de_cotisation_pour_client_k2(self):
        r = api(self.g1).post(CONTRIB, {'client': str(self.c2.pk), 'month': 6, 'year': 2026, 'amount': '2000'},
                              format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(SocialContribution.objects.filter(client=self.c2, month=6).exists())

    def test_gerant_k1_ne_peut_pas_deplacer_son_client_vers_k2(self):
        mine = self.mk(self.k1, 'Mien', 'Client')
        r = api(self.g1).patch(f'{CL}{mine.pk}/', {'node': self.k2.pk}, format='json')
        mine.refresh_from_db()
        self.assertEqual(mine.node_id, self.k1.pk)

    def test_gerant_k1_ne_voit_pas_la_liste_k2_meme_avec_filtres(self):
        for params in ({'node': self.k2.pk}, {'node': 'K2'}, {'node__code': 'K2'}, {'search': self.c2.code}):
            r = api(self.g1).get(CL, params)
            self.assertNotIn(str(self.c2.id), [x['id'] for x in results(r)] if r.status_code == 200 else [], params)

    def test_facturier_k1_voit_k2_mais_ne_modifie_pas_les_retenues_ni_le_plafond(self):
        f = api(self.f1)
        self.assertEqual(f.get(f'{CL}{self.c2.pk}/').status_code, 200)
        self.assertEqual(f.patch(f'{CL}{self.c2.pk}/', {'credit_limit': '1'}, format='json').status_code, 403)
        self.assertEqual(f.get(f'{COMMS}{self.cm2.pk}/').status_code, 403)
        self.assertEqual(f.get(f'{CONTRIB}{self.co2.pk}/').status_code, 403)
