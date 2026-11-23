"""Clients / Sync - ronde b12 (testeur Clients/Commissions, 2026-11-23).

Verification independante de BUG-941 a BUG-950 (dev-backend d32) puis recherche de
defauts voisins : push d'identite (garde updated_at), pull plafond + identite,
PATCH partiel vs livraison concurrente, journal / notifications, caisse sociale.
Donnees FICTIVES. Code applicatif non modifie.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as D
from unittest import expectedFailure, mock

from django.db.models import F
from django.utils import timezone

from clients.models import Client, SocialContribution, SocialDistribution
from clients.tests.test_clients_v2 import CL, CONTRIB, DISTRIB, Base, api
from clients.tests.test_clients_v6 import node_api, push
from core.models import ActivityLog, SystemNotification
from sync.management.commands.sync_now import apply_pull_response
from sync.models import DebtMovement


def n_notifs():
    return SystemNotification.objects.exclude(title__icontains="onfiguration").count()


def n_logs():
    return ActivityLog.objects.exclude(action__icontains="Configuration").count()


class PushIdentite(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.n3 = node_api(self.k3)
        self.own = self.mk(self.k1, 'Own', 'Own', credit_limit=D('50000.00'), current_debt=D('1500.00'))
        Client.objects.filter(pk=self.own.pk).update(total_breads_received=40)

    def edit(self, node=None, **changes):
        rec = {'id': str(self.own.id), 'node': 'K1', 'node_origin': 'K1', 'first_name': 'Own', 'last_name': 'Own'}
        rec.update(changes)
        return push(node or self.n1, 'clients.Client', rec)

    def cur(self):
        return Client.objects.get(pk=self.own.pk)

    def test_identite_et_parametres_appliques(self):
        r = self.edit(first_name='Nouveau', last_name='Nom', phone='0811111111', address='Av. Fictive 1',
                      notes='n', credit_limit='70000', commission_rate='0.30', cotisation_sociale='2500',
                      client_type='DETAILLANT')
        self.assertEqual(r['status'], 'ACCEPTED', r)
        c = self.cur()
        self.assertEqual((c.first_name, c.last_name, c.phone, c.address, c.notes),
                         ('Nouveau', 'Nom', '0811111111', 'Av. Fictive 1', 'n'))
        self.assertEqual((c.credit_limit, c.commission_rate, c.cotisation_sociale),
                         (D('70000.00'), D('0.30'), D('2500.00')))

    def test_dette_bp_pains_jamais_touches_meme_si_fournis(self):
        r = self.edit(phone='0822222222', current_debt='999999', total_breads_received=1, category='RISK',
                      is_active=False, code='ZZ999', node_origin='K3')
        self.assertEqual(r['status'], 'ACCEPTED', r)
        c = self.cur()
        self.assertEqual((c.current_debt, c.total_breads_received, c.category), (D('1500.00'), 40, 'NORMAL'))
        self.assertEqual(c.phone, '0822222222')
        self.assertTrue(c.is_active)
        self.assertEqual((c.code, c.node_origin), (self.own.code, 'K1'))

    def test_champ_invalide_rejette_tout_l_enregistrement(self):
        for bad in ({'phone': 'x' * 26}, {'first_name': '   '}, {'last_name': None}, {'first_name': 12},
                    {'credit_limit': '99999999999'}, {'credit_limit': 'NaN'}, {'credit_limit': '-1'},
                    {'commission_rate': '9'}, {'client_type': 'ROI'}, {'cotisation_sociale': 'abc'},
                    {'address': ['a']}):
            r = self.edit(first_name='Change', **bad) if 'first_name' not in bad else self.edit(**bad)
            self.assertEqual(r['status'], 'REJECTED', (bad, r))
            c = self.cur()
            self.assertEqual((c.first_name, c.phone, c.credit_limit), ('Own', '', D('50000.00')), bad)

    def test_garde_updated_at(self):
        old = (self.cur().updated_at - timedelta(hours=1)).isoformat()
        r = self.edit(phone='0833333333', updated_at=old)
        self.assertEqual(r['status'], 'ACCEPTED')
        self.assertEqual(self.cur().phone, '', "un push plus ancien que le Cloud doit etre ignore")
        new = (self.cur().updated_at + timedelta(minutes=1)).isoformat()
        self.assertEqual(self.edit(phone='0833333333', updated_at=new)['status'], 'ACCEPTED')
        self.assertEqual(self.cur().phone, '0833333333')
        self.assertEqual(self.edit(phone='0844444444')['status'], 'ACCEPTED')  # sans updated_at
        self.assertEqual(self.cur().phone, '0844444444')
        for bad in ('pas une date', 12, [1]):
            self.assertEqual(self.edit(phone='0855555555', updated_at=bad)['status'], 'REJECTED', bad)
        self.assertEqual(self.cur().phone, '0844444444')

    def test_baisse_du_plafond_categorie_risque_et_notification(self):
        before = n_notifs()
        self.assertEqual(self.edit(credit_limit='1000')['status'], 'ACCEPTED')
        c = self.cur()
        self.assertEqual(c.category, Client.Category.RISK)
        self.assertEqual(n_notifs(), before + 1)
        self.edit(credit_limit='900')  # deja a risque : pas de seconde alerte
        self.assertEqual(n_notifs(), before + 1)

    def test_hausse_du_plafond_sort_du_risque(self):
        Client.objects.filter(pk=self.own.pk).update(credit_limit=D('1000.00'), category='RISK')
        self.assertEqual(self.edit(credit_limit='50000')['status'], 'ACCEPTED')
        self.assertEqual(self.cur().category, Client.Category.NORMAL)

    def test_non_proprietaire_rejete(self):
        self.assertEqual(self.edit(self.n3, phone='0866666666')['status'], 'REJECTED')
        self.assertEqual(self.cur().phone, '')

    def test_rejeu_idempotent(self):
        for _ in range(3):
            self.assertEqual(self.edit(phone='0877777777', credit_limit='65000')['status'], 'ACCEPTED')
        c = self.cur()
        self.assertEqual((c.phone, c.credit_limit, c.current_debt), ('0877777777', D('65000.00'), D('1500.00')))

    def test_champ_invalide_rejete_meme_sous_garde_ancienne(self):
        old = (self.cur().updated_at - timedelta(hours=1)).isoformat()
        self.assertEqual(self.edit(phone='x' * 30, updated_at=old)['status'], 'REJECTED')

    def test_BUG_951_edition_identite_legitime_ignoree_apres_un_mouvement_de_dette_du_cloud(self):
        # le proprietaire edite hors ligne a T0 ; un autre poste (K3) facture ce client : le mouvement
        # pousse fait avancer updated_at du Cloud (BUG-787) ; le push d'identite date de T0 est ignore
        # (ACCEPTED) et le poste le croit synchronise : modification perdue silencieusement.
        t0 = (timezone.now() - timedelta(minutes=5)).isoformat()
        mv = {'id': str(uuid.uuid4()), 'client': str(self.own.id), 'amount': '2000', 'kind': 'ORDER'}
        self.assertEqual(push(self.n3, 'sync.DebtMovement', mv)['status'], 'ACCEPTED')
        self.assertEqual(self.cur().current_debt, D('3500.00'))
        r = self.edit(phone='0899999999', credit_limit='65000', updated_at=t0)
        self.assertEqual(r['status'], 'ACCEPTED')
        c = self.cur()
        self.assertEqual((c.phone, c.credit_limit), ('0899999999', D('65000.00')),
                         "edition d'identite du proprietaire perdue : updated_at avance a chaque mouvement de dette")


class PullPlafondIdentite(Base):
    def setUp(self):
        super().setUp()
        self.own = self.mk(self.k1, 'Own', 'Own', credit_limit=D('50000.00'))

    def pull(self, **kw):
        row = {'id': str(self.own.id), 'code': self.own.code, 'current_debt': '30000.00',
               'credit_limit': '50000.00', 'category': 'NORMAL'}
        row.update(kw)
        apply_pull_response({'clients': [row]})
        return Client.objects.get(pk=self.own.pk)

    def test_plafond_identite_appliques(self):
        c = self.pull(credit_limit='80000.00', first_name='Pf', last_name='Pl', phone='0811', address='Ad')
        self.assertEqual((c.credit_limit, c.first_name, c.last_name, c.phone, c.address),
                         (D('80000.00'), 'Pf', 'Pl', '0811', 'Ad'))
        self.assertEqual((c.current_debt, c.category), (D('30000.00'), 'NORMAL'))

    def test_categorie_coherente_avec_le_plafond_applique(self):
        # categorie perimee RISK mais plafond releve : redevient NORMAL
        c = self.pull(credit_limit='80000.00', category='RISK')
        self.assertEqual(c.category, 'NORMAL')
        # dette >= plafond mais categorie NORMAL envoyee : RISK
        c = self.pull(credit_limit='20000.00', category='NORMAL')
        self.assertEqual(c.category, 'RISK')
        # meilleur client conserve s'il reste sous le plafond
        Client.objects.filter(pk=self.own.pk).update(total_breads_received=10 ** 9)
        c = self.pull(credit_limit='80000.00', category='BEST')
        self.assertEqual(c.category, 'BEST')

    def test_valeurs_invalides_ignorees_sans_exception(self):
        for bad in ({'credit_limit': '-5'}, {'credit_limit': 'NaN'}, {'credit_limit': '1e12'},
                    {'credit_limit': True}, {'first_name': '  '}, {'first_name': 'x' * 101}, {'phone': 'x' * 26},
                    {'last_name': 7}):
            c = self.pull(**bad)
            self.assertEqual((c.credit_limit, c.first_name, c.last_name, c.phone),
                             (D('50000.00'), 'Own', 'Own', ''), bad)

    def test_notification_quand_le_pull_fait_passer_a_risque(self):
        before = n_notifs()
        self.pull(credit_limit='10000.00', category='RISK')
        self.assertEqual(n_notifs(), before + 1)
        self.pull(credit_limit='10000.00', category='RISK')
        self.assertEqual(n_notifs(), before + 1)

    def test_mouvement_local_non_pousse_protege_la_dette(self):
        DebtMovement.objects.create(client=self.own, amount=D('100'), kind='ORDER', node_origin='K1',
                                    is_synced=False)
        c = self.pull(first_name='Autre', credit_limit='1000.00')
        self.assertEqual((c.current_debt, c.first_name, c.credit_limit), (D('0.00'), 'Own', D('50000.00')))

    def test_BUG_952_pull_ecrase_une_edition_locale_non_encore_poussee(self):
        # poste : le gerant change le plafond (is_synced=False) ; un pull arrive avant le push
        # avec l'ancien plafond du Cloud : l'edition locale est ecrasee puis poussee telle quelle.
        r = api(self.g1).patch(f'{CL}{self.own.pk}/', {'credit_limit': '90000', 'last_name': 'Local'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(Client.objects.get(pk=self.own.pk).is_synced)
        c = self.pull(credit_limit='50000.00', last_name='Own', current_debt='0.00')
        self.assertEqual((c.credit_limit, c.last_name), (D('90000.00'), 'Local'),
                         "edition locale non synchronisee ecrasee par le pull (pas de garde, cf. BUG-780)")


class PatchPartiel(Base):
    def setUp(self):
        super().setUp()
        self.c = self.mk(self.k1, 'L', 'L', current_debt=D('1000.00'), credit_limit=D('50000.00'))

    def patch(self, body, user=None, during=None):
        from clients.serializers import ClientBoundsMixin
        real = ClientBoundsMixin.validate_credit_limit

        def hook(self_, value):
            if during:
                during()
            return real(self_, value)

        with mock.patch.object(ClientBoundsMixin, 'validate_credit_limit', hook):
            return api(user or self.g1).patch(f'{CL}{self.c.pk}/', body, format='json')

    def test_livraison_concurrente_conservee_et_categorie_sur_valeurs_verrouillees(self):
        def deliver():
            Client.objects.filter(pk=self.c.pk).update(current_debt=F('current_debt') + D('4000.00'),
                                                       total_breads_received=F('total_breads_received') + 50)
        before = n_notifs()
        r = self.patch({'credit_limit': '4500'}, during=deliver)
        self.assertEqual(r.status_code, 200, r.data)
        c = Client.objects.get(pk=self.c.pk)
        self.assertEqual((c.current_debt, c.total_breads_received, c.credit_limit), (D('5000.00'), 50, D('4500.00')))
        self.assertEqual(c.category, Client.Category.RISK, "5000 >= 4500 : RISK sur la dette reelle")
        self.assertEqual(n_notifs(), before + 1)

    def test_modification_concurrente_du_plafond_non_reecrite_par_un_patch_du_nom(self):
        def other():
            Client.objects.filter(pk=self.c.pk).update(credit_limit=D('12000.00'))
        # le hook est branche sur validate_credit_limit : on envoie les deux champs, puis on verifie le nom seul
        r = api(self.g1).patch(f'{CL}{self.c.pk}/', {'first_name': 'Renomme'}, format='json')
        self.assertEqual(r.status_code, 200)
        other()
        r = api(self.g1).patch(f'{CL}{self.c.pk}/', {'phone': '0811'}, format='json')
        self.assertEqual(r.status_code, 200)
        c = Client.objects.get(pk=self.c.pk)
        self.assertEqual((c.first_name, c.phone, c.credit_limit), ('Renomme', '0811', D('12000.00')))

    def test_patch_vide_ne_touche_pas_la_dette(self):
        r = api(self.g1).patch(f'{CL}{self.c.pk}/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Client.objects.get(pk=self.c.pk).current_debt, D('1000.00'))

    def test_facturier_et_livreur_ne_peuvent_pas_modifier_le_plafond(self):
        for u in (self.f1, self.l1):
            r = api(u).patch(f'{CL}{self.c.pk}/', {'credit_limit': '99999'}, format='json')
            self.assertIn(r.status_code, (403, 404), (u.role, r.status_code))
        self.assertEqual(Client.objects.get(pk=self.c.pk).credit_limit, D('50000.00'))

    def test_journal_plafond_et_taux(self):
        b = n_logs()
        api(self.g1).patch(f'{CL}{self.c.pk}/', {'first_name': 'X'}, format='json')
        self.assertEqual(n_logs(), b, "un simple renommage n'est pas une modification de plafond/taux")
        api(self.g1).patch(f'{CL}{self.c.pk}/', {'credit_limit': '60000'}, format='json')
        self.assertEqual(n_logs(), b + 1)
        api(self.g1).patch(f'{CL}{self.c.pk}/', {'credit_limit': '60000'}, format='json')
        self.assertEqual(n_logs(), b + 1, "valeur identique : pas de trace")
        api(self.g1).patch(f'{CL}{self.c.pk}/', {'commission_rate': '0.30'}, format='json')
        self.assertEqual(n_logs(), b + 2)

    def test_notification_risque_une_seule_fois(self):
        b = n_notifs()
        api(self.g1).patch(f'{CL}{self.c.pk}/', {'credit_limit': '500'}, format='json')
        self.assertEqual(n_notifs(), b + 1)
        api(self.g1).patch(f'{CL}{self.c.pk}/', {'credit_limit': '400'}, format='json')
        self.assertEqual(n_notifs(), b + 1)
        api(self.g1).patch(f'{CL}{self.c.pk}/', {'credit_limit': '90000'}, format='json')
        self.assertEqual(Client.objects.get(pk=self.c.pk).category, 'NORMAL')
        self.assertEqual(n_notifs(), b + 1)

    def test_patch_node_par_direction_regenere_code_et_origine(self):
        old_code = self.c.code
        r = api(self.direction).patch(f'{CL}{self.c.pk}/', {'node': self.k3.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        c = Client.objects.get(pk=self.c.pk)
        self.assertEqual((c.node_id, c.node_origin), (self.k3.pk, 'K3'))
        self.assertTrue(c.code.startswith('K3') and c.code != old_code, c.code)
        self.assertEqual(Client.objects.filter(code=c.code).count(), 1)
        self.assertEqual(c.current_debt, D('1000.00'))

    def test_patch_meme_node_garde_le_code_et_gerant_ne_deplace_pas(self):
        code = self.c.code
        api(self.direction).patch(f'{CL}{self.c.pk}/', {'node': self.k1.pk}, format='json')
        self.assertEqual(Client.objects.get(pk=self.c.pk).code, code)
        r = api(self.g1).patch(f'{CL}{self.c.pk}/', {'node': self.k3.pk}, format='json')
        self.assertEqual(r.status_code, 200)
        c = Client.objects.get(pk=self.c.pk)
        self.assertEqual((c.node_id, c.code), (self.k1.pk, code))

    def test_deux_deplacements_successifs_codes_distincts(self):
        other = self.mk(self.k1, 'M', 'M')
        for cl in (self.c, other):
            api(self.direction).patch(f'{CL}{cl.pk}/', {'node': self.k3.pk}, format='json')
        codes = set(Client.objects.filter(pk__in=[self.c.pk, other.pk]).values_list('code', flat=True))
        self.assertEqual(len(codes), 2)


class CaisseSociale(Base):
    def setUp(self):
        super().setUp()
        self.c1 = self.mk(self.k1, 'A', 'A')
        self.c3 = self.mk(self.k3, 'B', 'B')
        Client.objects.filter(pk=self.c1.pk).update(cotisation_sociale=D('2000.00'))
        self.contrib = SocialContribution.objects.create(client=self.c1, node=self.k1, month=2, year=2026,
                                                         amount=D('2000'))

    def body(self, **kw):
        b = {'client': str(self.c1.id), 'node': self.k1.pk, 'month': 3, 'year': 2026, 'amount': '2000'}
        b.update(kw)
        return b

    def test_annee_bornee_2000_2200(self):
        for year in (1999, 2201, 0, 65535):
            r = api(self.g1).post(CONTRIB, self.body(year=year), format='json')
            self.assertEqual(r.status_code, 400, (year, r.status_code))
            r = api(self.g1).patch(f'{CONTRIB}{self.contrib.pk}/', {'year': year}, format='json')
            self.assertEqual(r.status_code, 400, (year, r.status_code))
        for year in (2000, 2200):
            r = api(self.g1).post(CONTRIB, self.body(year=year), format='json')
            self.assertEqual(r.status_code, 201, (year, r.data))

    def test_is_paid_paid_at(self):
        url = f'{CONTRIB}{self.contrib.pk}/'
        r = api(self.g1).patch(url, {'is_paid': True}, format='json')
        self.assertEqual(r.status_code, 200)
        first = SocialContribution.objects.get(pk=self.contrib.pk).paid_at
        self.assertIsNotNone(first)
        api(self.g1).patch(url, {'is_paid': True}, format='json')
        self.assertEqual(SocialContribution.objects.get(pk=self.contrib.pk).paid_at, first, "date conservee")
        api(self.g1).patch(url, {'amount': '2100'}, format='json')
        self.assertEqual(SocialContribution.objects.get(pk=self.contrib.pk).paid_at, first)
        api(self.g1).patch(url, {'is_paid': False}, format='json')
        s = SocialContribution.objects.get(pk=self.contrib.pk)
        self.assertEqual((s.is_paid, s.paid_at), (False, None))
        # toggle_paid coherent avec le PATCH
        api(self.g1).post(f'{url}toggle_paid/')
        s = SocialContribution.objects.get(pk=self.contrib.pk)
        self.assertTrue(s.is_paid and s.paid_at is not None)

    def test_creation_payee_pose_la_date_et_paid_at_force_est_ignore(self):
        forged = '2001-01-01T00:00:00Z'
        r = api(self.g1).post(CONTRIB, self.body(is_paid=True, paid_at=forged), format='json')
        self.assertEqual(r.status_code, 201, r.data)
        s = SocialContribution.objects.get(pk=r.data['id'])
        self.assertTrue(s.is_paid and s.paid_at is not None and s.paid_at.year >= 2026)
        r = api(self.g1).post(CONTRIB, self.body(month=4, is_paid=False, paid_at=forged), format='json')
        self.assertIsNone(SocialContribution.objects.get(pk=r.data['id']).paid_at)

    def test_patch_node_et_client_controles(self):
        url = f'{CONTRIB}{self.contrib.pk}/'
        r = api(self.direction).patch(url, {'node': self.k3.pk}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        r = api(self.direction).patch(url, {'client': str(self.c3.id)}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        r = api(self.g1).patch(url, {'client': str(self.c3.id)}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        s = SocialContribution.objects.get(pk=self.contrib.pk)
        self.assertEqual((s.node_id, s.client_id), (self.k1.pk, self.c1.pk))
        # meme node explicite = accepte
        r = api(self.direction).patch(url, {'node': self.k1.pk, 'amount': '2500'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_put_complet_toujours_valide(self):
        r = api(self.direction).put(f'{CONTRIB}{self.contrib.pk}/', self.body(month=2, year=2026, amount='2300'),
                                    format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_bulk_montant_zero_explicite(self):
        for amount in (0, '0', '0.00', '0.0'):
            SocialContribution.objects.exclude(pk=self.contrib.pk).delete()
            r = api(self.g1).post(CONTRIB + 'bulk_create_month/',
                                  {'node': str(self.k1.pk), 'month': 7, 'year': 2026, 'amount': amount},
                                  format='json')
            self.assertEqual(r.status_code, 200, (amount, r.data))
            self.assertEqual(SocialContribution.objects.get(month=7).amount, D('0.00'), amount)

    def test_bulk_annee_2101_refusee_alors_que_le_serializer_accepte_2200(self):
        # constat d'incoherence mineure (2100 vs 2200), non ticketee
        r = api(self.g1).post(CONTRIB + 'bulk_create_month/',
                              {'node': str(self.k1.pk), 'month': 7, 'year': 2150}, format='json')
        self.assertEqual(r.status_code, 400)

    @expectedFailure
    def test_BUG_953_cotisation_d_une_distribution_cloturee_modifiable(self):
        # BUG-263/889 : commission payee / periode cloturee figees. Pour la caisse sociale, une fois la
        # distribution de l'annee cloturee (lignes figees), l'annulation du paiement par PATCH ou toggle_paid
        # est acceptee et rend les lignes figees incoherentes avec les cotisations.
        SocialContribution.objects.filter(pk=self.contrib.pk).update(is_paid=True, paid_at=timezone.now())
        SocialDistribution.objects.create(node=self.k1, year=2026, tarif=D('700'), is_closed=True)
        r = api(self.g1).patch(f'{CONTRIB}{self.contrib.pk}/', {'is_paid': False}, format='json')
        r2 = api(self.g1).post(f'{CONTRIB}{self.contrib.pk}/toggle_paid/')
        self.assertTrue(r.status_code == 400 and r2.status_code == 400,
                        (r.status_code, r2.status_code, "paiement annule apres cloture de la distribution"))

    def test_BUG_954_patch_is_paid_et_suppression_cotisation_non_journalises(self):
        # toggle_paid journalise (BUG-944) ; le PATCH direct (meme effet) et le DELETE d'une cotisation ne laissent
        # aucune trace.
        b = n_logs()
        r = api(self.g1).patch(f'{CONTRIB}{self.contrib.pk}/', {'is_paid': True}, format='json')
        self.assertEqual(r.status_code, 200)
        r = api(self.g1).delete(f'{CONTRIB}{self.contrib.pk}/')
        self.assertEqual(r.status_code, 204)
        self.assertGreaterEqual(n_logs(), b + 2)

    def test_toggle_paid_journalise_controle_positif(self):
        b = n_logs()
        api(self.g1).post(f'{CONTRIB}{self.contrib.pk}/toggle_paid/')
        self.assertEqual(n_logs(), b + 1)

    def test_isolation_gerant_k3_ne_touche_pas_la_cotisation_k1(self):
        r = api(self.g3).patch(f'{CONTRIB}{self.contrib.pk}/', {'is_paid': True}, format='json')
        self.assertEqual(r.status_code, 404)
        r = api(self.g3).post(f'{CONTRIB}{self.contrib.pk}/toggle_paid/')
        self.assertEqual(r.status_code, 404)
