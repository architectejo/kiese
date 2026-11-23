"""Clients / Commissions / Sync - ronde b11 (testeur Clients/Commissions, 2026-11-23).

Verification independante de BUG-915 (reliquat bulk_create_month), 933 et 934
(push DebtMovement), puis recherche de nouveaux defauts :
(a) balayage REST non ASCII / NaN / bornes sur clients, commissions, caisse sociale ;
(b) coherence de current_debt apres sequences mixtes REST + push DebtMovement ;
(c) idempotence et ordre d'un lot complet clients -> cotisations -> distribution -> lignes ;
(d) journal d'activite et notifications des actions metier ;
(e) client modifie sur deux postes (push proprietaire, pull).
Donnees FICTIVES. Code applicatif non modifie.
"""
import uuid
from datetime import date
from decimal import Decimal as D
from unittest import mock

from django.db.models import F

from clients.models import (
    Client, SocialContribution, SocialDistribution, SocialDistributionLine,
)
from clients.tests.test_clients_v2 import CL, CONTRIB, DISTRIB, LINES, Base, api
from clients.tests.test_clients_v6 import COMMS, PERIODS, PUSH, node_api, push
from commissions.models import ClientCommission, CommissionPeriod
from core.models import ActivityLog, SystemNotification
from sync.models import DebtMovement
from sync.services import record_debt_movement

BAD_NUMBERS = ('٣', '３', 'NaN', '-NaN', 'Infinity', '-Infinity', '1e999', '9' * 40, '-1', '', ' ', 'abc',
               None, True, [], {}, '0x10')


def _rec(**kw):
    rec = {'id': str(uuid.uuid4()), 'first_name': 'Bo', 'last_name': 'Rne', 'node': 'K1', 'node_origin': 'K1'}
    rec.update(kw)
    return rec


def _sane(value):
    """Valeur numerique stockee finie (jamais NaN / Infinity)."""
    return value is None or D(str(value)).is_finite()


# ----------------------------------------------------------------------------
# A. Verification BUG-915 / 933 / 934
# ----------------------------------------------------------------------------
class V915Verif(Base):
    def setUp(self):
        super().setUp()
        self.c1 = self.mk(self.k1, 'A', 'A')
        Client.objects.filter(pk=self.c1.pk).update(cotisation_sociale=D('2000.00'))

    def _bulk(self, **kw):
        body = {'node': str(self.k1.pk), 'month': 3, 'year': 2026}
        body.update(kw)
        return api(self.g1).post(CONTRIB + 'bulk_create_month/', body, format='json')

    def test_amount_non_ascii_et_invalides_refuses_sans_rien_creer(self):
        for amount in ('٣٠٠٠', '３０００', '۳۰۰۰', '१२३', 'NaN', 'Infinity', '-Infinity', '-1', '1e999', 'abc',
                       True, [1], {'a': 1}, '100000000', '99999999.999'):
            r = self._bulk(amount=amount)
            self.assertEqual(r.status_code, 400, (amount, r.status_code, getattr(r, 'data', None)))
        self.assertFalse(SocialContribution.objects.exists())

    def test_amount_ascii_et_formes_legitimes_acceptes(self):
        r = self._bulk(amount='2500.5')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(SocialContribution.objects.get(client=self.c1).amount, D('2500.50'))
        for month, amount in ((4, None), (5, ''), (6, 1500), (7, '99999999.99')):
            r = self._bulk(month=month, amount=amount)
            self.assertEqual(r.status_code, 200, (month, amount, r.data))
            self.assertEqual(r.data['created'], 1, (month, amount))
        self.assertEqual(SocialContribution.objects.get(client=self.c1, month=4).amount, D('2000.00'))
        self.assertEqual(SocialContribution.objects.get(client=self.c1, month=6).amount, D('1500.00'))

    def test_rejeu_idempotent_et_montants_decimal(self):
        self.assertEqual(self._bulk(amount='2500.50').data, {'created': 1, 'skipped': 0})
        self.assertEqual(self._bulk(amount='9999').data, {'created': 0, 'skipped': 1})
        self.assertEqual(SocialContribution.objects.get(client=self.c1).amount, D('2500.50'))

    def test_BUG_950_montant_zero_explicite_remplace_par_la_cotisation_par_defaut(self):
        # `manual_amount if manual_amount else default` : 0 explicite est traite comme « absent ».
        r = self._bulk(amount='0')
        self.assertEqual(r.status_code, 200, r.data)
        amounts = set(SocialContribution.objects.values_list('amount', flat=True))
        self.assertEqual(amounts, {D('0.00')}, "un montant 0 explicite ne doit pas etre remplace par 2000")


class V933Verif(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.own = self.mk(self.k1, 'Own', 'Own')

    def _mv(self, **kw):
        rec = {'id': str(uuid.uuid4()), 'client': str(self.own.id), 'amount': '1000', 'kind': 'ORDER'}
        rec.update(kw)
        return rec

    def _debt(self):
        return Client.objects.get(pk=self.own.pk).current_debt

    def test_BUG_933_absent_null_vide_blancs_refuses(self):
        for rec in ({'id': str(uuid.uuid4()), 'client': str(self.own.id), 'kind': 'ORDER'},
                    self._mv(amount=None), self._mv(amount=''), self._mv(amount='   '), self._mv(amount=[]),
                    self._mv(amount={}), self._mv(amount=False)):
            r = push(self.n1, 'sync.DebtMovement', rec)
            self.assertEqual(r['status'], 'REJECTED', (rec, r))
            self.assertFalse(DebtMovement.objects.filter(pk=rec['id']).exists(), rec)
        self.assertEqual(self._debt(), D('0.00'))

    def test_BUG_934_sous_centime_refuse_et_frontieres_exactes(self):
        for amount in ('0.004', '0.005', '0.001', '1.001', '-0.004', '12.345', 0.004, '1E-3'):
            r = push(self.n1, 'sync.DebtMovement', self._mv(amount=amount))
            self.assertEqual(r['status'], 'REJECTED', (amount, r))
        self.assertEqual(DebtMovement.objects.count(), 0)
        self.assertEqual(self._debt(), D('0.00'))
        for amount, expected in (('0.01', D('0.01')), ('-0.01', D('-0.01')), (12.5, D('12.50')), (7, D('7.00')),
                                 ('1E+2', D('100.00')), ('999999999999.99', D('999999999999.99'))):
            DebtMovement.objects.filter(client=self.own).delete()
            Client.objects.filter(pk=self.own.pk).update(current_debt=D('0.00'))
            rec = self._mv(amount=amount)
            r = push(self.n1, 'sync.DebtMovement', rec)
            self.assertEqual(r['status'], 'ACCEPTED', (amount, r))
            self.assertEqual(DebtMovement.objects.get(pk=rec['id']).amount, expected, amount)
            self.assertEqual(self._debt(), expected, amount)

    def test_zero_exact_accepte_sans_trace_et_dette_inchangee(self):
        Client.objects.filter(pk=self.own.pk).update(current_debt=D('300.00'))
        rec = self._mv(amount='0')
        self.assertEqual(push(self.n1, 'sync.DebtMovement', rec)['status'], 'ACCEPTED')
        self.assertEqual(self._debt(), D('300.00'))

    def test_hors_plage_et_cumul_hors_plage_refuses(self):
        for amount in ('1000000000000', '-1000000000000'):
            self.assertEqual(push(self.n1, 'sync.DebtMovement', self._mv(amount=amount))['status'], 'REJECTED', amount)
        self.assertEqual(push(self.n1, 'sync.DebtMovement', self._mv(amount='999999999999.99'))['status'], 'ACCEPTED')
        self.assertEqual(push(self.n1, 'sync.DebtMovement', self._mv(amount='1'))['status'], 'REJECTED')
        self.assertEqual(self._debt(), D('999999999999.99'))


# ----------------------------------------------------------------------------
# (a) Balayage REST : non ASCII, NaN, bornes, types hostiles
# ----------------------------------------------------------------------------
class SweepRest(Base):
    def setUp(self):
        super().setUp()
        self.c1 = self.mk(self.k1, 'A', 'A')
        self.dist = SocialDistribution.objects.create(node=self.k1, year=2026, tarif=D('700'))
        self.contrib = SocialContribution.objects.create(client=self.c1, node=self.k1, month=2, year=2026,
                                                         amount=D('2000'))
        self.line = SocialDistributionLine.objects.create(distribution=self.dist, client=self.c1)
        self.period = CommissionPeriod.objects.create(node=self.k1, month=5, year=2026)
        self.cc = ClientCommission.objects.create(period=self.period, client=self.c1, order_value=D('1000'),
                                                  commission_rate=D('0.25'))

    def _sweep(self, user, method, url, fields, base=None):
        """Renvoie les anomalies : 5xx, ou 2xx avec valeur non finie."""
        problems = []
        for field in fields:
            for bad in BAD_NUMBERS:
                body = dict(base or {})
                body[field] = bad
                r = getattr(api(user), method)(url, body, format='json')
                if r.status_code >= 500:
                    problems.append((field, repr(bad), r.status_code))
                elif r.status_code < 300 and bad not in (None, '', ' ') and not isinstance(bad, (bool, list, dict)):
                    # une valeur hostile ne doit jamais etre acceptee (hors vide eventuellement optionnel)
                    problems.append((field, repr(bad), 'ACCEPTE', r.status_code))
        return problems

    def test_client_create_et_patch(self):
        base = {'first_name': 'Z', 'last_name': 'Z'}
        problems = self._sweep(self.g1, 'post', CL, ('credit_limit', 'commission_rate', 'cotisation_sociale'), base)
        problems += self._sweep(self.g1, 'patch', f'{CL}{self.c1.pk}/',
                                ('credit_limit', 'commission_rate', 'cotisation_sociale'))
        # null est legitime pour cotisation_sociale (retour a la valeur de la boulangerie)
        problems = [p for p in problems if not (p[0] == 'cotisation_sociale' and p[1] in ("None", "''"))]
        self.assertEqual(problems, [])
        for c in Client.objects.all():
            for f in (c.credit_limit, c.commission_rate, c.cotisation_sociale, c.current_debt):
                self.assertTrue(_sane(f))

    def test_client_noms_et_champs_texte(self):
        for field, bad in (('first_name', None), ('first_name', ''), ('first_name', '   '), ('first_name', 'x' * 101),
                           ('last_name', ['a']), ('phone', '9' * 26), ('phone', ['1']),
                           ('client_type', 'ROI'), ('client_type', 5), ('address', {'a': 1}), ('is_active', 'peut-etre'),
                           ('node', 'abc'), ('node', 99999), ('node', ['K1'])):
            body = {'first_name': 'Z', 'last_name': 'Z'}
            body[field] = bad
            r = api(self.g1).post(CL, body, format='json')
            self.assertLess(r.status_code, 500, (field, bad, r.status_code))
            r = api(self.g1).patch(f'{CL}{self.c1.pk}/', {field: bad}, format='json')
            self.assertLess(r.status_code, 500, (field, bad, r.status_code))
        c = Client.objects.get(pk=self.c1.pk)
        self.assertEqual((c.first_name, c.last_name), ('A', 'A'))

    def test_contribution(self):
        base = {'client': str(self.c1.id), 'node': self.k1.pk, 'month': 9, 'year': 2026}
        problems = self._sweep(self.g1, 'post', CONTRIB, ('amount',), base)
        problems += self._sweep(self.g1, 'patch', f'{CONTRIB}{self.contrib.pk}/', ('amount', 'month'))
        problems = [p for p in problems if p[:2] != ('amount', 'None') or p[2] != 'ACCEPTE']
        self.assertEqual([p for p in problems if p[1] not in ("''", "' '")], [])
        for sc in SocialContribution.objects.all():
            self.assertTrue(_sane(sc.amount) and sc.amount >= 0 and 1 <= sc.month <= 12)

    def test_distribution_et_lignes(self):
        problems = self._sweep(self.direction, 'patch', f'{DISTRIB}{self.dist.pk}/', ('tarif', 'year'))
        c2 = self.mk(self.k1, 'B', 'B')
        base = {'distribution': str(self.dist.pk), 'client': str(c2.id)}
        problems += self._sweep(self.g1, 'post', LINES, ('indice', 'merite', 'total_social'), base)
        problems += self._sweep(self.g1, 'patch', f'{LINES}{self.line.pk}/', ('indice', 'merite', 'total_social'))
        self.assertEqual([p for p in problems if p[1] not in ("''", "' '", 'None')], [])
        for ln in SocialDistributionLine.objects.all():
            self.assertTrue(all(_sane(v) for v in (ln.total_social, ln.remise, ln.merite, ln.total_payer)))

    def test_client_commission_post_patch(self):
        c2 = self.mk(self.k1, 'C', 'C')
        base = {'period': str(self.period.pk), 'client': str(c2.id), 'order_value': '1000'}
        fields = ('order_value', 'commission_rate', 'deduction_debt', 'deduction_social', 'deduction_prints',
                  'deduction_other', 'total_breads')
        problems = self._sweep(self.direction, 'post', COMMS, fields, base)
        problems += self._sweep(self.direction, 'patch', f'{COMMS}{self.cc.pk}/', fields)
        self.assertEqual([p for p in problems if p[1] not in ("''", "' '", 'None')], [])
        for cc in ClientCommission.objects.all():
            for v in (cc.order_value, cc.commission_gross, cc.total_deductions, cc.net_payable):
                self.assertTrue(_sane(v))

    def test_set_manuel_et_generate_et_bulk(self):
        for bad in BAD_NUMBERS:
            r = api(self.direction).patch(f'{COMMS}{self.cc.pk}/set_manuel/', {'manuel_adjustment': bad},
                                          format='json')
            self.assertLess(r.status_code, 500, (bad, r.status_code))
            for field in ('month', 'year'):
                body = {'node': str(self.k1.pk), 'month': 8, 'year': 2026}
                body[field] = bad
                r = api(self.direction).post(PERIODS + 'generate/', body, format='json')
                self.assertLess(r.status_code, 500, (field, bad, r.status_code))
                self.assertTrue(r.status_code >= 400 or bad in ('',), (field, bad, r.status_code))
        for bad in ('abc', 5, [1, 'x'], [None], [{}], ['١'], [str(uuid.uuid4()), 3], 'null', {'a': 1}):
            for route in ('bulk_move/', 'bulk_delete/'):
                r = api(self.direction).post(CL + route, {'ids': bad, 'node': str(self.k3.pk)}, format='json')
                self.assertLess(r.status_code, 500, (route, bad, r.status_code))

    def test_BUG_946_annee_cotisation_sans_borne_rest(self):
        # le push (BUG-917) refuse 1999 et 99999 ; bulk_create_month 2000-2100 ; la REST accepte n'importe quelle annee.
        for year in (0, 1, 1999, 32767):
            r = api(self.g1).post(CONTRIB, {'client': str(self.c1.id), 'node': self.k1.pk, 'month': 3,
                                            'year': year, 'amount': '2000'}, format='json')
            self.assertEqual(r.status_code, 400, (year, r.status_code, getattr(r, 'data', None)))

    def test_distribution_et_cotisation_en_double_400_pas_500(self):
        r = api(self.g1).post(DISTRIB, {'node': self.k1.pk, 'year': 2026}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)
        r = api(self.g1).post(DISTRIB, {'year': 2026}, format='json')
        self.assertLess(r.status_code, 500, r.status_code)
        r = api(self.g1).post(CONTRIB, {'client': str(self.c1.id), 'node': self.k1.pk, 'month': 2, 'year': 2026},
                              format='json')
        self.assertEqual(r.status_code, 400, r.status_code)
        c2 = self.mk(self.k1, 'B', 'B')
        r = api(self.g1).patch(f'{LINES}{self.line.pk}/', {'client': str(c2.id)}, format='json')
        self.assertEqual(r.status_code, 200)
        SocialDistributionLine.objects.create(distribution=self.dist, client=self.c1)
        r = api(self.g1).patch(f'{LINES}{self.line.pk}/', {'client': str(self.c1.id)}, format='json')
        self.assertEqual(r.status_code, 400, r.status_code)

    def test_BUG_947_cotisation_is_paid_par_patch_sans_paid_at(self):
        # toggle_paid pose paid_at ; PATCH/POST is_paid=true laisse paid_at vide (et is_paid=false le conserve).
        r = api(self.g1).patch(f'{CONTRIB}{self.contrib.pk}/', {'is_paid': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.contrib.refresh_from_db()
        self.assertTrue(self.contrib.is_paid)
        self.assertIsNotNone(self.contrib.paid_at, "cotisation payee sans date de paiement")

    def test_BUG_947b_cotisation_is_paid_false_efface_paid_at(self):
        api(self.g1).post(f'{CONTRIB}{self.contrib.pk}/toggle_paid/')
        r = api(self.g1).patch(f'{CONTRIB}{self.contrib.pk}/', {'is_paid': False}, format='json')
        self.assertEqual(r.status_code, 200)
        self.contrib.refresh_from_db()
        self.assertFalse(self.contrib.is_paid)
        self.assertIsNone(self.contrib.paid_at, "cotisation non payee mais paid_at conserve")

    def test_BUG_948_siege_peut_rattacher_une_cotisation_a_un_client_d_une_autre_boulangerie(self):
        # perform_create controle client.node == node ; la mise a jour (HQ) ne controle rien.
        c3 = self.mk(self.k3, 'Far', 'Away')
        r = api(self.direction).patch(f'{CONTRIB}{self.contrib.pk}/', {'client': str(c3.id)}, format='json')
        self.contrib.refresh_from_db()
        self.assertTrue(r.status_code >= 400 or self.contrib.client.node_id == self.contrib.node_id,
                        (r.status_code, self.contrib.client.node_id, self.contrib.node_id))

    def test_BUG_948b_siege_peut_deplacer_une_ligne_ou_cotisation_vers_une_autre_boulangerie(self):
        r = api(self.direction).patch(f'{CONTRIB}{self.contrib.pk}/', {'node': self.k3.pk}, format='json')
        self.contrib.refresh_from_db()
        self.assertTrue(r.status_code >= 400 or self.contrib.client.node_id == self.contrib.node_id,
                        (r.status_code, self.contrib.client.node_id, self.contrib.node_id))

    def test_BUG_949_patch_node_siege_ne_regenere_pas_le_code(self):
        # bulk_move regenere le code (prefixe = boulangerie) ; PATCH node par le siege laisse « K1-... » sur K3.
        r = api(self.direction).patch(f'{CL}{self.c1.pk}/', {'node': self.k3.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.node_id, self.k3.pk)
        self.assertTrue(self.c1.code.startswith('K3-'), self.c1.code)


# ----------------------------------------------------------------------------
# (b) current_debt : sequences mixtes REST + push, rejeu, ordre inverse, deux postes
# ----------------------------------------------------------------------------
class DebtMixed(Base):
    def setUp(self):
        super().setUp()
        from core.models import Config
        Config.get_instance()
        self.n1 = node_api(self.k1)
        self.n3 = node_api(self.k3)

    def _rest_sale(self, client, amount, kind='ORDER'):
        """Ce que fait sales.views a la livraison : F() + trace additive."""
        Client.objects.filter(pk=client.pk).update(current_debt=F('current_debt') + amount)
        record_debt_movement(client, amount, kind, node_origin='K1')

    def _mv(self, client, amount, kind='ORDER'):
        return {'id': str(uuid.uuid4()), 'client': str(client.id), 'amount': str(amount), 'kind': kind}

    def _debt(self, c):
        return Client.objects.get(pk=c.pk).current_debt

    def test_sequence_mixte_rejeu_et_ordre_inverse_donnent_la_meme_dette(self):
        a = self.mk(self.k1, 'A', 'A', current_debt=D('5000.00'))
        b = self.mk(self.k1, 'B', 'B', current_debt=D('5000.00'))
        ops = [('rest', D('2000')), ('push1', D('3000.50')), ('push3', D('-1000')), ('rest', D('-250.25'))]
        recs = {}

        def play(client, order):
            for i in order:
                kind, amount = ops[i]
                if kind == 'rest':
                    self._rest_sale(client, amount, 'ORDER' if amount > 0 else 'REPAYMENT')
                else:
                    key = (client.pk, i)
                    recs.setdefault(key, self._mv(client, amount))
                    node = self.n1 if kind == 'push1' else self.n3
                    self.assertEqual(push(node, 'sync.DebtMovement', recs[key])['status'], 'ACCEPTED', key)

        play(a, [0, 1, 2, 3])
        play(b, [3, 2, 1, 0])
        expected = D('5000') + D('2000') + D('3000.50') - D('1000') - D('250.25')
        self.assertEqual((self._debt(a), self._debt(b)), (expected, expected))
        # rejeu complet des deux pushs (memes ids) : aucune derive
        for client in (a, b):
            for i in (1, 2):
                node = self.n1 if ops[i][0] == 'push1' else self.n3
                self.assertEqual(push(node, 'sync.DebtMovement', recs[(client.pk, i)])['status'], 'ACCEPTED')
        self.assertEqual((self._debt(a), self._debt(b)), (expected, expected))
        self.assertEqual(DebtMovement.objects.filter(client=a).count(), 4)

    def test_deux_postes_meme_client_ids_distincts_somme_exacte_et_categorie(self):
        c = self.mk(self.k1, 'R', 'R', credit_limit=D('50000.00'))
        for node, amount in ((self.n1, '30000'), (self.n3, '19999.99'), (self.n1, '0.01'), (self.n3, '-5000')):
            push(node, 'sync.DebtMovement', self._mv(c, amount))
        c.refresh_from_db()
        self.assertEqual(c.current_debt, D('45000.00'))
        self.assertEqual(c.category, Client.Category.NORMAL)
        push(self.n3, 'sync.DebtMovement', self._mv(c, '5000'))
        c.refresh_from_db()
        self.assertEqual((c.current_debt, c.category), (D('50000.00'), Client.Category.RISK))
        push(self.n1, 'sync.DebtMovement', self._mv(c, '-0.01'))
        c.refresh_from_db()
        self.assertEqual((c.current_debt, c.category), (D('49999.99'), Client.Category.NORMAL))

    def test_rejeu_apres_modification_rest_du_plafond_ne_derive_pas(self):
        c = self.mk(self.k1, 'P', 'P', credit_limit=D('50000.00'))
        rec = self._mv(c, '20000')
        push(self.n1, 'sync.DebtMovement', rec)
        r = api(self.g1).patch(f'{CL}{c.pk}/', {'credit_limit': '10000'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        c.refresh_from_db()
        self.assertEqual((c.current_debt, c.category), (D('20000.00'), Client.Category.RISK))
        push(self.n1, 'sync.DebtMovement', rec)  # rejeu
        push(self.n3, 'sync.DebtMovement', self._mv(c, '-15000'))
        c.refresh_from_db()
        self.assertEqual((c.current_debt, c.category), (D('5000.00'), Client.Category.NORMAL))

    def test_BUG_943_patch_client_ecrase_la_dette_modifiee_pendant_la_requete(self):
        # `serializer.save()` ecrit TOUTES les colonnes lues par get_object() : une livraison validee
        # entre la lecture et l'ecriture (F()) est perdue. Simulation deterministe (cf. BUG-735).
        c = self.mk(self.k1, 'L', 'L', current_debt=D('1000.00'))
        from clients.serializers import ClientBoundsMixin
        real = ClientBoundsMixin.validate_credit_limit

        def concurrent(self_, value):
            Client.objects.filter(pk=c.pk).update(current_debt=F('current_debt') + D('4000.00'),
                                                  total_breads_received=F('total_breads_received') + 50)
            return real(self_, value)

        with mock.patch.object(ClientBoundsMixin, 'validate_credit_limit', concurrent):
            r = api(self.g1).patch(f'{CL}{c.pk}/', {'credit_limit': '60000'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        c.refresh_from_db()
        self.assertEqual(c.credit_limit, D('60000.00'))
        self.assertEqual((c.current_debt, c.total_breads_received), (D('5000.00'), 50),
                         "la livraison concurrente (+4000 FC, +50 pains) a ete ecrasee par le PATCH")

    def test_BUG_945_pas_de_notification_quand_la_poussee_fait_passer_un_client_a_risque(self):
        c = self.mk(self.k1, 'N', 'N', credit_limit=D('50000.00'))
        before = SystemNotification.objects.exclude(title__icontains="onfiguration").count()
        push(self.n1, 'sync.DebtMovement', self._mv(c, '60000'))
        c.refresh_from_db()
        self.assertEqual(c.category, Client.Category.RISK)
        # la livraison REST notifie « Alerte Crédit » ; le meme franchissement par push est silencieux
        self.assertGreater(SystemNotification.objects.exclude(title__icontains="onfiguration").count(), before)

    def test_BUG_945b_pas_de_notification_quand_baisser_le_plafond_met_le_client_a_risque(self):
        c = self.mk(self.k1, 'N', 'N', credit_limit=D('50000.00'), current_debt=D('20000.00'))
        before = SystemNotification.objects.exclude(title__icontains="onfiguration").count()
        r = api(self.g1).patch(f'{CL}{c.pk}/', {'credit_limit': '10000'}, format='json')
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.category, Client.Category.RISK)
        # `recalculate_category` notifie la meme transition ; le PATCH ne notifie pas
        self.assertGreater(SystemNotification.objects.exclude(title__icontains="onfiguration").count(), before)


# ----------------------------------------------------------------------------
# (c) Lot complet : ordre et idempotence
# ----------------------------------------------------------------------------
class LotComplet(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.cid, self.sid, self.did, self.lid, self.mid = (str(uuid.uuid4()) for _ in range(5))

    def records(self):
        return {
            'clients.SocialDistributionLine': [{'id': self.lid, 'distribution': self.did, 'client': self.cid,
                                                'indice': 3, 'total_social': '6000', 'merite': '100'}],
            'clients.SocialDistribution': [{'id': self.did, 'node': 'K1', 'year': 2026, 'tarif': '700'}],
            'clients.SocialContribution': [{'id': self.sid, 'client': self.cid, 'node': 'K1', 'month': 1,
                                            'year': 2026, 'amount': '2000', 'is_paid': True}],
            'sync.DebtMovement': [{'id': self.mid, 'client': self.cid, 'amount': '1234.56', 'kind': 'ORDER'}],
            'clients.Client': [_rec(id=self.cid, first_name='Lot', last_name='Complet')],
        }

    def post(self, records, batch=None):
        r = self.n1.post(PUSH, {'batch_id': batch or str(uuid.uuid4()), 'records': records}, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        return r.data['results']

    def state(self):
        return (Client.objects.filter(pk=self.cid).count(), SocialContribution.objects.count(),
                SocialDistribution.objects.count(), SocialDistributionLine.objects.count(),
                DebtMovement.objects.count(),
                Client.objects.get(pk=self.cid).current_debt if Client.objects.filter(pk=self.cid).exists() else None,
                [(l.remise, l.total_payer) for l in SocialDistributionLine.objects.all()])

    def test_ordre_des_cles_inverse_traite_dans_l_ordre_de_dependance(self):
        res = self.post(self.records())
        for label, items in res.items():
            self.assertEqual([i['status'] for i in items], ['ACCEPTED'], (label, items))
        self.assertEqual(self.state(), (1, 1, 1, 1, 1, D('1234.56'), [(D('2100.00'), D('8200.00'))]))

    def test_rejeu_meme_batch_et_nouveau_batch_sont_idempotents(self):
        batch = str(uuid.uuid4())
        self.post(self.records(), batch)
        first = self.state()
        self.post(self.records(), batch)
        self.assertEqual(self.state(), first)
        res = self.post(self.records())
        self.assertTrue(all(i['status'] == 'ACCEPTED' for items in res.values() for i in items), res)
        self.assertEqual(self.state(), first)

    def test_client_rejete_les_dependants_sont_rejetes_proprement_puis_repris(self):
        recs = self.records()
        recs['clients.Client'][0]['credit_limit'] = '99999999999'  # hors borne
        res = self.post(recs)
        self.assertEqual(res['clients.Client'][0]['status'], 'REJECTED')
        for label in ('clients.SocialContribution', 'clients.SocialDistributionLine', 'sync.DebtMovement'):
            self.assertEqual(res[label][0]['status'], 'REJECTED', label)
        self.assertEqual(res['clients.SocialDistribution'][0]['status'], 'ACCEPTED')
        self.assertEqual((SocialContribution.objects.count(), SocialDistributionLine.objects.count(),
                          DebtMovement.objects.count()), (0, 0, 0))
        res = self.post(self.records())  # reprise corrigee
        self.assertTrue(all(i['status'] == 'ACCEPTED' for items in res.values() for i in items), res)
        self.assertEqual(self.state()[:5], (1, 1, 1, 1, 1))

    def test_lot_par_morceaux_dans_le_desordre_converge(self):
        recs = self.records()
        # 1. ligne seule : dependances manquantes ; 2. distribution ; 3. client ; 4. ligne a nouveau
        r1 = self.post({'clients.SocialDistributionLine': recs['clients.SocialDistributionLine']})
        self.assertEqual(r1['clients.SocialDistributionLine'][0]['status'], 'REJECTED')
        self.post({'clients.SocialDistribution': recs['clients.SocialDistribution']})
        self.post({'clients.Client': recs['clients.Client']})
        r4 = self.post({'clients.SocialDistributionLine': recs['clients.SocialDistributionLine']})
        self.assertEqual(r4['clients.SocialDistributionLine'][0]['status'], 'ACCEPTED', r4)
        self.post({'sync.DebtMovement': recs['sync.DebtMovement'],
                   'clients.SocialContribution': recs['clients.SocialContribution']})
        self.assertEqual(self.state(), (1, 1, 1, 1, 1, D('1234.56'), [(D('2100.00'), D('8200.00'))]))

    def test_doublons_dans_un_meme_lot(self):
        recs = self.records()
        recs['clients.Client'] = recs['clients.Client'] * 2
        recs['sync.DebtMovement'] = recs['sync.DebtMovement'] * 2
        recs['clients.SocialContribution'] = recs['clients.SocialContribution'] * 2
        res = self.post(recs)
        self.assertTrue(all(i['status'] == 'ACCEPTED' for items in res.values() for i in items), res)
        self.assertEqual(self.state()[:6], (1, 1, 1, 1, 1, D('1234.56')))

    def test_deuxieme_cotisation_meme_mois_autre_id_rejetee(self):
        self.post(self.records())
        res = self.post({'clients.SocialContribution': [{'id': str(uuid.uuid4()), 'client': self.cid, 'node': 'K1',
                                                         'month': 1, 'year': 2026, 'amount': '9999'}]})
        self.assertEqual(res['clients.SocialContribution'][0]['status'], 'REJECTED', res)
        self.assertEqual(SocialContribution.objects.get().amount, D('2000.00'))


# ----------------------------------------------------------------------------
# (d) Journal d'activite et notifications
# ----------------------------------------------------------------------------
class Journal(Base):
    def setUp(self):
        super().setUp()
        from core.models import Config
        Config.get_instance()
        self.c1 = self.mk(self.k1, 'A', 'A')
        Client.objects.filter(pk=self.c1.pk).update(cotisation_sociale=D('2000.00'))
        self.dist = SocialDistribution.objects.create(node=self.k1, year=2026, tarif=D('700'))
        self.contrib = SocialContribution.objects.create(client=self.c1, node=self.k1, month=2, year=2026,
                                                         amount=D('2000'))
        self.period = CommissionPeriod.objects.create(node=self.k1, month=5, year=2026)
        self.cc = ClientCommission.objects.create(period=self.period, client=self.c1, order_value=D('1000'),
                                                  commission_rate=D('0.25'))

    def count(self):
        # Config.get_instance() journalise « Modification Configuration » à sa création : bruit exclu.
        return ActivityLog.objects.exclude(action__icontains="Configuration").count()

    def test_creation_client_est_journalisee_controle_positif(self):
        before = self.count()
        r = api(self.g1).post(CL, {'first_name': 'N', 'last_name': 'N'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.count(), before + 1)

    def test_BUG_944_modification_plafond_et_taux_client_non_journalisee(self):
        before = self.count()
        r = api(self.g1).patch(f'{CL}{self.c1.pk}/', {'credit_limit': '80000', 'commission_rate': '0.30'},
                               format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertGreater(self.count(), before)

    def test_BUG_944b_suppression_client_unitaire_non_journalisee(self):
        c = self.mk(self.k1, 'D', 'D')
        before = self.count()
        r = api(self.direction).delete(f'{CL}{c.pk}/')
        self.assertEqual(r.status_code, 204)
        self.assertGreater(self.count(), before)

    def test_BUG_944_caisse_sociale_paiement_cotisation_non_journalise(self):
        before = self.count()
        r = api(self.g1).post(f'{CONTRIB}{self.contrib.pk}/toggle_paid/')
        self.assertEqual(r.status_code, 200)
        self.assertGreater(self.count(), before, "toggle_paid : encaissement de cotisation sans trace")

    def test_BUG_944b_caisse_sociale_generation_mensuelle_non_journalisee(self):
        before = self.count()
        r = api(self.g1).post(CONTRIB + 'bulk_create_month/', {'node': str(self.k1.pk), 'month': 8, 'year': 2026},
                              format='json')
        self.assertEqual(r.data['created'], 1)
        self.assertGreater(self.count(), before)

    def test_BUG_944c_cloture_distribution_irreversible_non_journalisee(self):
        before = self.count()
        r = api(self.direction).patch(f'{DISTRIB}{self.dist.pk}/', {'is_closed': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(SocialDistribution.objects.get(pk=self.dist.pk).is_closed)
        self.assertGreater(self.count(), before, "cloture irreversible de la caisse sociale sans trace")

    def test_BUG_944d_modification_ligne_distribution_non_journalisee(self):
        line = SocialDistributionLine.objects.create(distribution=self.dist, client=self.c1)
        before = self.count()
        r = api(self.g1).patch(f'{LINES}{line.pk}/', {'merite': '5000'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertGreater(self.count(), before)

    def test_BUG_944_creation_modification_suppression_commission_non_journalisees(self):
        before = self.count()
        r = api(self.direction).patch(f'{COMMS}{self.cc.pk}/', {'deduction_other': '300'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertGreater(self.count(), before, "retenue modifiee (net a payer change) sans trace")

    def test_BUG_944b_suppression_commission_non_journalisee(self):
        before = self.count()
        r = api(self.direction).delete(f'{COMMS}{self.cc.pk}/')
        self.assertEqual(r.status_code, 204)
        self.assertGreater(self.count(), before)

    def test_actions_deja_journalisees_controle_positif(self):
        before = self.count()
        api(self.direction).post(f'{COMMS}{self.cc.pk}/mark_paid/', {}, format='json')
        self.assertEqual(self.count(), before + 1)
        api(self.direction).post(f'{PERIODS}{self.period.pk}/close_period/')
        self.assertEqual(self.count(), before + 2)


# ----------------------------------------------------------------------------
# (e) Client modifie sur deux postes : push proprietaire et pull
# ----------------------------------------------------------------------------
class DeuxPostes(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.n3 = node_api(self.k3)
        self.own = self.mk(self.k1, 'Own', 'Own', credit_limit=D('50000.00'))

    def _push_edit(self, node, **changes):
        rec = {'id': str(self.own.id), 'node': 'K1', 'node_origin': 'K1', 'first_name': 'Own', 'last_name': 'Own'}
        rec.update(changes)
        return push(node, 'clients.Client', rec)

    def test_non_proprietaire_rejete_et_journalise_sans_toucher_le_client(self):
        r = self._push_edit(self.n3, phone='0999999999', credit_limit='1')
        self.assertEqual(r['status'], 'REJECTED', r)
        c = Client.objects.get(pk=self.own.pk)
        self.assertEqual((c.phone, c.credit_limit), ('', D('50000.00')))

    def test_BUG_941_modification_du_proprietaire_acceptee_mais_jamais_appliquee(self):
        # SYNC.md 5.1 : identite (nom, telephone, plafond) = dernier ecrivain gagne, proprietaire ou Cloud.
        r = self._push_edit(self.n1, phone='0812345678', credit_limit='80000', last_name='Renomme')
        self.assertEqual(r['status'], 'ACCEPTED', r)
        c = Client.objects.get(pk=self.own.pk)
        self.assertEqual((c.phone, c.credit_limit, c.last_name), ('0812345678', D('80000.00'), 'Renomme'),
                         "ACCEPTED mais ni telephone ni plafond ni nom n'ont ete appliques (perte silencieuse)")

    def test_pull_renvoie_le_plafond_et_la_categorie_du_cloud(self):
        api(self.g1).patch(f'{CL}{self.own.pk}/', {'credit_limit': '12000'}, format='json')
        r = self.n1.get('/api/sync/pull/')
        self.assertEqual(r.status_code, 200)
        row = [c for c in r.data['clients'] if c['id'] == str(self.own.id)][0]
        self.assertEqual(row['credit_limit'], '12000.00')

    def test_BUG_942_pull_n_applique_ni_plafond_ni_identite_sur_le_poste(self):
        from sync.management.commands.sync_now import apply_pull_response
        # etat du poste : copie locale avec l'ancien plafond ; le Cloud a un plafond modifie et une dette en RISK
        payload = {'clients': [{'id': str(self.own.id), 'code': self.own.code, 'current_debt': '30000.00',
                                'credit_limit': '20000.00', 'category': 'RISK',
                                'updated_at': '2026-11-23T10:00:00+00:00'}]}
        apply_pull_response(payload)
        c = Client.objects.get(pk=self.own.pk)
        self.assertEqual((c.current_debt, c.category), (D('30000.00'), 'RISK'))
        self.assertEqual(c.credit_limit, D('20000.00'),
                         "categorie RISK appliquee avec le plafond du Cloud, mais plafond local inchange (50000) : "
                         "le poste bloquerait ou non selon une valeur differente de celle du Cloud")

    def test_pull_incremental_curseur_et_modification_simultanee(self):
        r = self.n1.get('/api/sync/pull/')
        cursor = r.data['since_client_debt']
        # deux modifications quasi simultanees au cloud (REST) : la derniere gagne, une seule ligne au pull
        api(self.g1).patch(f'{CL}{self.own.pk}/', {'credit_limit': '12000'}, format='json')
        api(self.direction).patch(f'{CL}{self.own.pk}/', {'credit_limit': '9000'}, format='json')
        r = self.n1.get('/api/sync/pull/', {'since_client_debt': cursor})
        rows = [c for c in r.data['clients'] if c['id'] == str(self.own.id)]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['credit_limit'], '9000.00')
        r2 = self.n1.get('/api/sync/pull/', {'since_client_debt': r.data['since_client_debt']})
        self.assertEqual([c for c in r2.data['clients'] if c['id'] == str(self.own.id)], [])
