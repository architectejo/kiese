"""Clients / Commissions / Sync - ronde b10 (testeur Clients/Commissions, 2026-11-23).

Verification independante de BUG-915 a 918 : rejets cibles ET non-regression des
flux legitimes (REST, import Excel, paie, push), puis defauts voisins (push
DebtMovement, booleens poussés en chaine, doublons uniques, modeles non
supportes). Donnees FICTIVES. Code applicatif non modifie.
"""
import io
import uuid
from datetime import date
from decimal import Decimal as D
from unittest import expectedFailure

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile

from clients.models import (
    Client, SocialContribution, SocialDistribution, SocialDistributionLine,
)
from clients.tests.test_clients_v2 import CL, CONTRIB, DISTRIB, LINES, Base, api
from clients.tests.test_clients_v6 import PERIODS, node_api, push
from commissions.models import ClientCommission
from core.testing import make_bread_price, make_client
from sync.models import DebtMovement

TODAY = date.today()


def _rec(**kw):
    rec = {'id': str(uuid.uuid4()), 'first_name': 'Bo', 'last_name': 'Rne', 'node': 'K1', 'node_origin': 'K1'}
    rec.update(kw)
    return rec


# ----------------------------------------------------------------------------
# A. BUG-915 : verification REST (rejets + flux legitimes)
# ----------------------------------------------------------------------------
class V915Rest(Base):
    def setUp(self):
        super().setUp()
        self.c1 = self.mk(self.k1, 'A', 'A')

    def test_chiffres_non_ascii_refuses_sur_toutes_les_routes_caisse_sociale(self):
        for amount in ('٣٠٠٠', '３０００', '۳۰۰۰'):
            r = api(self.g1).post(CONTRIB, {'client': str(self.c1.id), 'node': self.k1.pk, 'month': 5,
                                            'year': 2026, 'amount': amount}, format='json')
            self.assertEqual(r.status_code, 400, (amount, r.data))
        for month in ('５', '٥'):
            r = api(self.g1).post(CONTRIB, {'client': str(self.c1.id), 'node': self.k1.pk, 'month': month,
                                            'year': 2026, 'amount': '2000'}, format='json')
            self.assertEqual(r.status_code, 400, (month, r.data))
        self.assertFalse(SocialContribution.objects.exists())
        # PATCH d'une cotisation existante
        sc = SocialContribution.objects.create(client=self.c1, node=self.k1, month=2, year=2026, amount=D('2000'))
        r = api(self.g1).patch(f'{CONTRIB}{sc.pk}/', {'amount': '٣٠٠٠'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        sc.refresh_from_db()
        self.assertEqual(sc.amount, D('2000.00'))
        # bulk_create_month : montant et annee
        for body in ({'month': 3, 'year': '２０２６'}, {'month': '٣', 'year': 2026}):
            body['node'] = str(self.k1.pk)
            r = api(self.g1).post(CONTRIB + 'bulk_create_month/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.data))
        self.assertEqual(SocialContribution.objects.count(), 1)

    @expectedFailure  # BUG-915 (reouvert : `amount` de bulk_create_month non controle)
    def test_BUG_915_residuel_bulk_create_month_amount_non_ascii(self):
        Client.objects.filter(pk=self.c1.pk).update(cotisation_sociale=D('2000.00'))
        r = api(self.g1).post(CONTRIB + 'bulk_create_month/', {'node': str(self.k1.pk), 'month': 3, 'year': 2026,
                                                               'amount': '٣٠٠٠'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_distribution_ligne_tarif_merite_indice_non_ascii_refuses(self):
        d = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2026, 'tarif': '700'}, format='json').data['id']
        self.assertEqual(api(self.direction).patch(f'{DISTRIB}{d}/', {'tarif': '٨٠٠'}, format='json').status_code, 400)
        self.assertEqual(SocialDistribution.objects.get(pk=d).tarif, D('700.00'))
        for body in ({'merite': '٥٠٠'}, {'indice': '３'}, {'total_social': '１０００'}):
            body.update({'distribution': d, 'client': str(self.c1.id)})
            r = api(self.g1).post(LINES, body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.data))
        self.assertFalse(SocialDistributionLine.objects.exists())

    def test_generate_paie_non_ascii_refuse_et_ascii_accepte(self):
        for body in ({'month': '１１', 'year': 2026}, {'month': 11, 'year': '２０２６'}, {'month': '٣', 'year': 2026}):
            body['node'] = str(self.k1.pk)
            r = api(self.direction).post(PERIODS + 'generate/', body, format='json')
            self.assertEqual(r.status_code, 400, (body, r.data))
        r = api(self.direction).post(PERIODS + 'generate/', {'node': str(self.k1.pk), 'month': '11', 'year': '2026'},
                                     format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_formulaire_multipart_et_nombres_json_legitimes(self):
        r = api(self.g1).post(CONTRIB, {'client': str(self.c1.id), 'node': self.k1.pk, 'month': 6, 'year': 2026,
                                        'amount': '2000.50'}, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(SocialContribution.objects.get(client=self.c1).amount, D('2000.50'))
        r = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2026, 'tarif': 700}, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_creation_client_rest_et_ancien_poste_sans_prenom(self):
        r = api(self.g1).post(CL, {'first_name': 'Aline', 'last_name': 'Demo', 'credit_limit': '50000',
                                   'commission_rate': '0.30', 'cotisation_sociale': '1500'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['commission_rate'], '0.30')
        # REST exige le prenom (400) : meme regle cote push
        r = api(self.g1).post(CL, {'last_name': 'Demo'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_import_excel_noms_avec_chiffres_non_ascii_sans_erreur(self):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        ws = wb.create_sheet('CL-K1 TABO')
        ws.append(['DATE', 'CODE', 'NOM'])
        ws.append(['2026-11-01', 'C1', 'Jean ٣٣٣'])
        ws.append(['2026-11-02', 'C2', 'MONO'])
        ws.append(['2026-11-03', 'C3', 'Ａｌｉｎｅ １２ Zola'])
        buf = io.BytesIO()
        wb.save(buf)
        f = SimpleUploadedFile('fictif.xlsx', buf.getvalue(),
                               content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        r = api(self.direction).post(CL + 'import_excel/', {'file': f}, format='multipart')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertEqual(r.data['created'], 3)
        mono = Client.objects.get(node=self.k1, last_name='MONO')
        self.assertEqual(mono.first_name, 'MONO')  # convention : prenom = nom si un seul mot
        for c in Client.objects.filter(node=self.k1):
            self.assertTrue(c.code.startswith('K1-'), c.code)


# ----------------------------------------------------------------------------
# B. BUG-916/917/918 : push, rejets cibles + non-regression
# ----------------------------------------------------------------------------
class V916Push(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.own = self.mk(self.k1, 'Own', 'Own')
        self.foreign = self.mk(self.k3, 'For', 'Eign')

    def test_client_bornes_exactes_acceptees_et_depassements_refuses(self):
        for kw in ({'commission_rate': '0.30', 'credit_limit': '10000000.00'},
                   {'commission_rate': '0', 'credit_limit': '0'},
                   {'commission_rate': 0.25, 'credit_limit': 50000, 'cotisation_sociale': '0'},
                   {'commission_rate': '0.25', 'credit_limit': '50000.00', 'cotisation_sociale': '1500.50'}):
            rec = _rec(**kw)
            self.assertEqual(push(self.n1, 'clients.Client', rec)['status'], 'ACCEPTED', kw)
            self.assertTrue(Client.objects.filter(pk=rec['id']).exists(), kw)
        for kw in ({'commission_rate': '0.31'}, {'commission_rate': '0.305'}, {'credit_limit': '10000000.01'},
                   {'credit_limit': 'abc'}, {'commission_rate': True}, {'credit_limit': '٥٠٠٠٠'},
                   {'credit_limit': 'NaN'}, {'credit_limit': 'Infinity'}, {'commission_rate': '１'},
                   {'first_name': '   '}, {'last_name': None}, {'first_name': 12}):
            rec = _rec(**kw)
            r = push(self.n1, 'clients.Client', rec)
            self.assertEqual(r['status'], 'REJECTED', (kw, r))
            self.assertFalse(Client.objects.filter(pk=rec['id']).exists(), kw)

    def test_client_sans_prenom_ancien_noeud_rejete_avec_motif_clair(self):
        # Contrat d27 (risque annonce) : REST exige aussi le prenom. Le rejet doit rester explicite.
        rec = _rec()
        del rec['first_name']
        r = push(self.n1, 'clients.Client', rec)
        self.assertEqual(r['status'], 'REJECTED')
        self.assertIn('first_name', str(r))

    def test_client_connu_renvoye_reste_noop_idempotent(self):
        rec = _rec(commission_rate='0.25')
        self.assertEqual(push(self.n1, 'clients.Client', rec)['status'], 'ACCEPTED')
        rec2 = dict(rec, commission_rate='0.95', first_name='')  # rejeu altere : n'ecrase rien
        r = push(self.n1, 'clients.Client', rec2)
        c = Client.objects.get(pk=rec['id'])
        self.assertEqual((c.commission_rate, c.first_name), (D('0.25'), 'Bo'), r)

    def test_cotisation_cycle_legitime_et_rejets_cibles(self):
        sid = str(uuid.uuid4())
        rec = {'id': sid, 'client': str(self.own.id), 'node': 'K1', 'month': 12, 'year': 2026, 'amount': '0'}
        self.assertEqual(push(self.n1, 'clients.SocialContribution', rec)['status'], 'ACCEPTED')
        self.assertEqual(push(self.n1, 'clients.SocialContribution',
                              {'id': sid, 'is_paid': True, 'paid_at': '2026-12-05T10:00:00Z', 'amount': '2000.50'})['status'],
                         'ACCEPTED')
        sc = SocialContribution.objects.get(pk=sid)
        self.assertEqual((sc.is_paid, sc.amount), (True, D('2000.50')))
        for kw in ({'month': 0}, {'month': 13}, {'month': '٣'}, {'month': 1.5}, {'year': 1999}, {'year': 99999},
                   {'amount': '١٠'}, {'amount': '-0.01'}, {'amount': '12345678901'}, {'month': True}):
            r2 = {'id': str(uuid.uuid4()), 'client': str(self.own.id), 'node': 'K1', 'month': 1, 'year': 2025,
                  'amount': '2000'}
            r2.update(kw)
            self.assertEqual(push(self.n1, 'clients.SocialContribution', r2)['status'], 'REJECTED', kw)
            self.assertFalse(SocialContribution.objects.filter(pk=r2['id']).exists(), kw)

    def test_cotisation_client_inconnu_ou_id_non_uuid_rejete_sans_500(self):
        for cl in (str(uuid.uuid4()), 'pas-un-uuid', 12, {'x': 1}, ['a']):
            rec = {'id': str(uuid.uuid4()), 'client': cl, 'node': 'K1', 'month': 3, 'year': 2026, 'amount': '1'}
            r = self.n1.post('/api/sync/push/', {'batch_id': str(uuid.uuid4()),
                                                 'records': {'clients.SocialContribution': [rec]}}, format='json')
            self.assertEqual(r.status_code, 200, (cl, r.status_code))
            self.assertEqual(r.data['results']['clients.SocialContribution'][0]['status'], 'REJECTED', cl)

    def test_ligne_recalcul_serveur_identique_a_rest(self):
        # Cotisations 3 x 2000 -> total social 6000 ; tarif 700 ; indice 3
        did = str(uuid.uuid4())
        push(self.n1, 'clients.SocialDistribution', {'id': did, 'node': 'K1', 'year': 2026, 'tarif': '700'})
        lid = str(uuid.uuid4())
        r = push(self.n1, 'clients.SocialDistributionLine',
                 {'id': lid, 'distribution': did, 'client': str(self.own.id), 'indice': 3, 'total_social': '6000',
                  'merite': '900', 'remise': '1', 'total_payer': '1'})
        self.assertEqual(r['status'], 'ACCEPTED', r)
        line = SocialDistributionLine.objects.get(pk=lid)
        self.assertEqual((line.remise, line.total_payer), (D('2100.00'), D('9000.00')))
        # modification : changer l'indice recalcule ; changer seulement remise est ignore
        push(self.n1, 'clients.SocialDistributionLine', {'id': lid, 'distribution': did, 'indice': 4})
        line.refresh_from_db()
        self.assertEqual((line.remise, line.total_payer), (D('2800.00'), D('9700.00')))
        push(self.n1, 'clients.SocialDistributionLine', {'id': lid, 'distribution': did, 'remise': '5', 'total_payer': '5'})
        line.refresh_from_db()
        self.assertEqual((line.remise, line.total_payer), (D('2800.00'), D('9700.00')))
        # meme resultat que la voie REST (autre client)
        c2 = self.mk(self.k1, 'Rest', 'Rest')
        r = api(self.g1).post(LINES, {'distribution': did, 'client': str(c2.id), 'indice': 4, 'total_social': '6000',
                                      'merite': '900'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((D(r.data['remise']), D(r.data['total_payer'])), (line.remise, line.total_payer))

    def test_ligne_rejets_cibles_et_bornes_exactes(self):
        did = str(uuid.uuid4())
        push(self.n1, 'clients.SocialDistribution', {'id': did, 'node': 'K1', 'year': 2026, 'tarif': '700'})
        ok = {'id': str(uuid.uuid4()), 'distribution': did, 'client': str(self.own.id), 'indice': 12}
        self.assertEqual(push(self.n1, 'clients.SocialDistributionLine', ok)['status'], 'ACCEPTED')
        self.assertEqual(SocialDistributionLine.objects.get(pk=ok['id']).remise, D('8400.00'))
        for kw in ({'indice': 13}, {'indice': -1}, {'indice': '٣'}, {'indice': 1.5}, {'merite': '-0.01'},
                   {'total_social': '-1'}, {'merite': '١'}, {'position': 'x'}, {'form': 'cheque'}):
            c = self.mk(self.k1, 'Z', str(uuid.uuid4())[:8])
            rec = {'id': str(uuid.uuid4()), 'distribution': did, 'client': str(c.id)}
            rec.update(kw)
            r = push(self.n1, 'clients.SocialDistributionLine', rec)
            self.assertEqual(r['status'], 'REJECTED', (kw, r))
            self.assertFalse(SocialDistributionLine.objects.filter(pk=rec['id']).exists(), kw)

    def test_ligne_modification_avec_valeur_hors_borne_refusee_sans_alterer(self):
        did = str(uuid.uuid4())
        push(self.n1, 'clients.SocialDistribution', {'id': did, 'node': 'K1', 'year': 2026, 'tarif': '700'})
        lid = str(uuid.uuid4())
        push(self.n1, 'clients.SocialDistributionLine', {'id': lid, 'distribution': did, 'client': str(self.own.id),
                                                          'indice': 2, 'total_social': '4000'})
        for kw in ({'indice': 99}, {'merite': '-5'}, {'total_social': '٤'}):
            rec = {'id': lid, 'distribution': did}
            rec.update(kw)
            self.assertEqual(push(self.n1, 'clients.SocialDistributionLine', rec)['status'], 'REJECTED', kw)
        line = SocialDistributionLine.objects.get(pk=lid)
        self.assertEqual((line.indice, line.merite, line.total_payer), (2, D('0.00'), D('5400.00')))


# ----------------------------------------------------------------------------
# C. Defauts voisins : push DebtMovement
# ----------------------------------------------------------------------------
class V919DebtMovement(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.own = self.mk(self.k1, 'Own', 'Own')

    def _mv(self, **kw):
        rec = {'id': str(uuid.uuid4()), 'client': str(self.own.id), 'amount': '1000', 'kind': 'ORDER'}
        rec.update(kw)
        return rec

    def test_legitimes_negatif_zero_et_current_debt_recompose(self):
        self.assertEqual(push(self.n1, 'sync.DebtMovement', self._mv(amount='15000'))['status'], 'ACCEPTED')
        self.assertEqual(push(self.n1, 'sync.DebtMovement', self._mv(amount='-4000.50', kind='REPAYMENT'))['status'], 'ACCEPTED')
        self.assertEqual(Client.objects.get(pk=self.own.pk).current_debt, D('10999.50'))
        # rejeu strictement identique : idempotent
        rec = self._mv(amount='250')
        push(self.n1, 'sync.DebtMovement', rec)
        self.assertEqual(push(self.n1, 'sync.DebtMovement', rec)['status'], 'ACCEPTED')
        self.assertEqual(DebtMovement.objects.filter(client=self.own).count(), 3)
        self.assertEqual(Client.objects.get(pk=self.own.pk).current_debt, D('11249.50'))

    def test_dette_d_ouverture_conservee(self):
        Client.objects.filter(pk=self.own.pk).update(current_debt=D('5000.00'))
        push(self.n1, 'sync.DebtMovement', self._mv(amount='1000'))
        self.assertEqual(Client.objects.get(pk=self.own.pk).current_debt, D('6000.00'))

    def test_montants_invalides_refuses_sans_toucher_la_dette(self):
        bad = ('٣٠٠٠', '１２', 'NaN', 'Infinity', '-Infinity', 'abc', True, [1], {'a': 1}, '1e400', '99999999999999')
        for amount in bad:
            rec = self._mv(amount=amount)
            r = push(self.n1, 'sync.DebtMovement', rec)
            self.assertEqual(r['status'], 'REJECTED', (amount, r))
            self.assertFalse(DebtMovement.objects.filter(pk=rec['id']).exists(), amount)
        self.assertEqual(Client.objects.get(pk=self.own.pk).current_debt, D('0.00'))

    @expectedFailure  # BUG-933
    def test_BUG_933_montant_absent_ou_null_cree_mouvement_zero_silencieux(self):
        # `_to_decimal(None)` -> 0 : un mouvement sans montant est ACCEPTED (aucun effet) au lieu d'etre refuse.
        for rec in ({'id': str(uuid.uuid4()), 'client': str(self.own.id), 'kind': 'ORDER'},
                    {'id': str(uuid.uuid4()), 'client': str(self.own.id), 'amount': None, 'kind': 'ORDER'},
                    {'id': str(uuid.uuid4()), 'client': str(self.own.id), 'amount': '', 'kind': 'ORDER'}):
            self.assertEqual(push(self.n1, 'sync.DebtMovement', rec)['status'], 'REJECTED', rec)

    @expectedFailure  # BUG-934
    def test_BUG_934_sous_centime_arrondi_silencieusement_ou_a_zero(self):
        # 0.004 : valide par _validate_fields (arrondi) mais le handler quantize/cree selon le champ ; la dette ne
        # doit jamais bouger d'un montant different de celui pousse (REST : 2 decimales maximum).
        rec = self._mv(amount='0.004')
        r = push(self.n1, 'sync.DebtMovement', rec)
        self.assertEqual(r['status'], 'REJECTED', r)

    def test_kind_et_note_hors_regles_refuses(self):
        for kw in ({'kind': 'HACK'}, {'note': 'x' * 300}, {'kind': 5}):
            rec = self._mv(**kw)
            r = push(self.n1, 'sync.DebtMovement', rec)
            self.assertEqual(r['status'], 'REJECTED', (kw, r))
            self.assertFalse(DebtMovement.objects.filter(pk=rec['id']).exists(), kw)

    def test_rejeu_avec_contenu_different_est_un_conflit(self):
        rec = self._mv(amount='100')
        push(self.n1, 'sync.DebtMovement', rec)
        r = push(self.n1, 'sync.DebtMovement', dict(rec, amount='999'))
        self.assertEqual(r['status'], 'REJECTED')
        self.assertEqual(Client.objects.get(pk=self.own.pk).current_debt, D('100.00'))

    def test_client_autre_noeud_accepte_mais_facture_autre_noeud_refusee(self):
        foreign = self.mk(self.k3, 'F', 'F')
        self.assertEqual(push(self.n1, 'sync.DebtMovement', self._mv(client=str(foreign.id)))['status'], 'ACCEPTED')
        from sales.models import Invoice
        inv = Invoice.objects.create(node=self.k3, client=foreign, payment_type=Invoice.PaymentType.CASH,
                                     status=Invoice.Status.DELIVERED, payment_amount=D('0'), node_origin='K3')
        r = push(self.n1, 'sync.DebtMovement', self._mv(invoice=str(inv.pk)))
        self.assertEqual(r['status'], 'REJECTED', r)

    def test_mouvement_ne_peut_pas_usurper_node_origin(self):
        rec = self._mv(node_origin='K3')
        r = push(self.n1, 'sync.DebtMovement', rec)
        self.assertEqual(r['status'], 'REJECTED', r)
        self.assertFalse(DebtMovement.objects.filter(pk=rec['id']).exists())


# ----------------------------------------------------------------------------
# D. Defauts voisins : booleens, doublons, modeles non supportes
# ----------------------------------------------------------------------------
class V920Voisins(Base):
    def setUp(self):
        super().setUp()
        self.n1 = node_api(self.k1)
        self.own = self.mk(self.k1, 'Own', 'Own')

    def test_is_paid_chaine_false_ne_marque_pas_la_cotisation_payee(self):
        # `bool('false')` est True : le handler lit le booleen sans l'interpreter.
        rec = {'id': str(uuid.uuid4()), 'client': str(self.own.id), 'node': 'K1', 'month': 3, 'year': 2026,
               'amount': '2000', 'is_paid': 'false'}
        r = push(self.n1, 'clients.SocialContribution', rec)
        sc = SocialContribution.objects.filter(pk=rec['id']).first()
        self.assertTrue(r['status'] == 'REJECTED' or (sc is not None and sc.is_paid is False), (r, sc and sc.is_paid))

    def test_is_closed_chaine_false_ne_cloture_pas_la_distribution(self):
        rec = {'id': str(uuid.uuid4()), 'node': 'K1', 'year': 2026, 'tarif': '700', 'is_closed': 'false'}
        r = push(self.n1, 'clients.SocialDistribution', rec)
        d = SocialDistribution.objects.filter(pk=rec['id']).first()
        self.assertTrue(r['status'] == 'REJECTED' or (d is not None and d.is_closed is False), (r, d and d.is_closed))

    def test_distribution_meme_annee_autre_id_rejetee_sans_500(self):
        SocialDistribution.objects.create(node=self.k1, year=2026, tarif=D('700'))
        r = push(self.n1, 'clients.SocialDistribution', {'id': str(uuid.uuid4()), 'node': 'K1', 'year': 2026})
        self.assertEqual(r['status'], 'REJECTED', r)
        self.assertEqual(SocialDistribution.objects.filter(node=self.k1, year=2026).count(), 1)

    def test_ligne_meme_client_autre_id_rejetee_sans_500(self):
        d = SocialDistribution.objects.create(node=self.k1, year=2026, tarif=D('700'))
        SocialDistributionLine.objects.create(distribution=d, client=self.own)
        r = push(self.n1, 'clients.SocialDistributionLine',
                 {'id': str(uuid.uuid4()), 'distribution': str(d.pk), 'client': str(self.own.id)})
        self.assertEqual(r['status'], 'REJECTED', r)
        self.assertEqual(SocialDistributionLine.objects.filter(distribution=d).count(), 1)

    def test_client_code_doublon_et_type_invalide_rejetes(self):
        rec = _rec(code=self.own.code)
        self.assertEqual(push(self.n1, 'clients.Client', rec)['status'], 'REJECTED')
        for kw in ({'client_type': 'ROI'}, {'phone': '9' * 40}, {'code': 'K1-' + '9' * 30}):
            rec = _rec(**kw)
            self.assertEqual(push(self.n1, 'clients.Client', rec)['status'], 'REJECTED', kw)
            self.assertFalse(Client.objects.filter(pk=rec['id']).exists(), kw)

    def test_client_champs_serveur_ignores_current_debt_category(self):
        rec = _rec(current_debt='999999', category='BEST', total_breads_received=500, is_active=False)
        r = push(self.n1, 'clients.Client', rec)
        if r['status'] == 'ACCEPTED':
            c = Client.objects.get(pk=rec['id'])
            self.assertEqual((c.current_debt, c.category, c.total_breads_received), (D('0.00'), 'NORMAL', 0))

    def test_modeles_core_chat_non_supportes_rejetes_proprement(self):
        for label in ('core.ColisDistribution', 'clients.ClientCategory', 'chat.Message', 'chat.Conversation',
                      'core.Config', 'core.User', 'core.BreadPrice', 'clients.Nope'):
            rec = {'id': str(uuid.uuid4()), 'name': 'x'}
            r = self.n1.post('/api/sync/push/', {'batch_id': str(uuid.uuid4()), 'records': {label: [rec]}},
                             format='json')
            self.assertEqual(r.status_code, 200, (label, r.status_code))
            self.assertEqual(r.data['results'][label][0]['status'], 'REJECTED', label)
        self.assertFalse(Client.objects.filter(first_name='x').exists())
