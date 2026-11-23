"""Cycle 14 (testeur-tresorerie, 2026-11-23-c14) : verification independante de BUG-971 (d36) et de
BUG-969 / 970 / 972 (d37), puis recherche de defauts voisins du sync (rejet de cloture non
redescendu, derive d'horloge, notifications parasites, consultation des conflits).
Donnees fictives. Code applicatif non modifie.
"""
import uuid
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from django.utils import timezone

from clients.models import Client
from core.models import SystemNotification
from core.testing import make_client, make_user
from sync.management.commands.sync_now import apply_push_response, build_outbound_payload
from sync.models import SyncConflictLog
from treasury.models import CashbookEntry, CashClosure, DisbursementVoucher, FacturierReport, LocalExpense
from treasury.tests.test_cycle1_tresorerie_c import cl, today
from treasury.tests.test_verif_tresorerie_c10_v9 import CLO, RAP, VOU
from treasury.tests.test_verif_tresorerie_c13_v12 import Base13, EXP
from treasury.tests.test_verif_tresorerie_c8_v7 import PUSH, push_client

CLI = 'clients.Client'
NOTIF_TITLE = "Modification de client ignorée"


class V971_Flux(Base13):
    def _poste(self, node, code, specs, depense):
        for team, cash, credit in specs:
            f = make_user('FACTURIER', node, team)
            FacturierReport.objects.create(node=node, facturier=f, team=team, date=today(),
                                           total_cash_sales=Dc(cash), total_credit_sales=Dc(credit),
                                           theoretical_cash=Dc(cash), node_origin=code)
        LocalExpense.objects.create(node=node, description='Eau', amount=Dc(depense), category=self.cat,
                                    date=today(), node_origin=code)

    def _closure(self, node, code, entries, expenses, **bills):
        c = CashClosure(node=node, date=today(), node_origin=code, total_entries=Dc(entries),
                        total_expenses=Dc(expenses), **bills)
        c.compute_physical_cash()
        c.save()

    def test_flux_2_postes_cloud_validation_direction_rest_puis_versement(self):
        self._poste(self.n1, 'C1', (('A', '7000', '0'), ('B', '3000', '500')), '2000')
        self._poste(self.n2, 'C2', (('A', '20000', '0'),), '5000')
        self._closure(self.n1, 'C1', '10000', '2000', bills_5000=1, bills_1000=3)
        self._closure(self.n2, 'C2', '20000', '5000', bills_10000=1, bills_5000=1)
        _, res1 = self.cycle(self.raw1, 'C1')
        _, res2 = self.cycle(self.raw2, 'C2')
        self.assertEqual((self.refused(res1), self.refused(res2)), ([], []))
        c1 = CashClosure.objects.get(node=self.n1, date=today())
        c2 = CashClosure.objects.get(node=self.n2, date=today())
        # jamais confirmee ni versee par le simple push
        self.assertEqual((c1.is_validated, c2.is_validated, CashbookEntry.objects.count()), (False, False, 0))
        # un gerant ne confirme pas, la direction oui (REST)
        self.assertEqual(self.valider(c1.pk, self.g1).status_code, 403)
        self.assertEqual(self.valider(c1.pk, self.dirn).status_code, 200)
        self.assertEqual(self.valider(c2.pk, self.compt).status_code, 200)
        self.assertEqual(CashbookEntry.objects.count(), 0)  # validation seule : pas de versement
        for c in (c1, c2):
            self.assertEqual(self.verser(c.pk).status_code, 201)
        self.assertEqual(CashbookEntry.objects.count(), 2)
        self.assertEqual(self.verser(c1.pk).status_code, 400)  # double versement
        e = {x.source_closure.node.code: x for x in CashbookEntry.objects.select_related('source_closure__node')}
        self.assertEqual((e['C1'].entry_amount, e['C2'].entry_amount), (Dc('8000'), Dc('15000')))
        self.assertEqual(e['C1'].piece_number, f"VC-C1-{today():%Y%m%d}")
        self.assertTrue(self.chain_ok())
        # coherence des deux endpoints
        a = cl(self.dirn).get('/api/treasury/cashbook/integrity_check/').json()['chain_valid']
        b = cl(self.adm).post('/api/blockchain/snapshots/run_check/', {}, format='json')
        self.assertTrue(a)
        self.assertEqual(b.status_code, 200, b.content)

    def test_cloture_rejouee_apres_validation_cloud_ne_change_rien_ni_ne_double_verse(self):
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='10000', bills_10000=1)
        self.push(self.raw1, CLO, rec)
        self.assertEqual(self.valider(rec['id'], self.dirn).status_code, 200)
        self.assertEqual(self.verser(rec['id']).status_code, 201)
        before = CashClosure.objects.values().get(pk=rec['id'])
        n_book = CashbookEntry.objects.count()
        for variant in (rec, dict(rec, is_validated=True), dict(rec, is_validated=False, bills_10000=9,
                                                                 total_entries='99'),
                        dict(rec, is_validated=True, total_expenses='5000')):
            self.assertEqual(self.status_of(self.push(self.raw1, CLO, variant)), 'ACCEPTED')
        self.assertEqual(CashClosure.objects.values().get(pk=rec['id']), before)
        self.assertEqual(CashbookEntry.objects.count(), n_book)
        self.assertTrue(self.chain_ok())

    def test_observation_rejeu_apres_validation_sans_versement_verse_automatiquement(self):
        """Comportement conserve par d36 (documente, pas un ticket) : la clôture confirmee par le
        comptable mais pas encore versee est versee par un simple rejeu du poste."""
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='10000', bills_10000=1)
        self.push(self.raw1, CLO, rec)
        self.assertEqual(self.valider(rec['id'], self.dirn).status_code, 200)
        self.push(self.raw1, CLO, rec)
        self.assertEqual(CashbookEntry.objects.count(), 1)
        self.assertEqual(self.verser(rec['id']).status_code, 400)

    def test_cloture_infirmee_rejeu_ne_la_confirme_ni_ne_la_verse(self):
        rec = self.clo()
        self.push(self.raw1, CLO, rec)
        r = cl(self.dirn).post(f"/api/treasury/closures/{rec['id']}/reject/", {'reason': 'ecart'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.push(self.raw1, CLO, dict(rec, is_validated=True))
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual((c.is_validated, c.is_rejected), (False, True))
        self.assertEqual(CashbookEntry.objects.count(), 0)

    def test_creation_validee_sans_ecart_cree_non_confirmee(self):
        rec = self.clo(is_validated=True)
        self.assertEqual(self.status_of(self.push(self.raw1, CLO, rec)), 'ACCEPTED')
        self.assertFalse(CashClosure.objects.get(pk=rec['id']).is_validated)

    def test_cloture_creee_par_le_jeton_siege_ne_se_confirme_pas_non_plus(self):
        rec = self.clo(is_validated=True)
        self.push(self.raws, CLO, rec)  # jeton siege, noeud != C1 : refuse (BUG-722)
        self.assertEqual(CashbookEntry.objects.count(), 0)

    # ---- defaut voisin : la resoumission apres rejet n'atteint jamais le cloud
    @expectedFailure
    def test_BUG_983_resoumission_apres_rejet_poussee_par_le_poste(self):
        """REST : seule une cloture infirmee peut etre modifiee puis resoumise (perform_update,
        BUG-034). En mode synchronise, le handler push ignore tout enregistrement existant : la
        resoumission (meme id, billets corriges) n'est jamais appliquee et le rejet reste actif."""
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='10000', bills_10000=1)
        self.push(self.raw1, CLO, rec)
        cl(self.dirn).post(f"/api/treasury/closures/{rec['id']}/reject/", {'reason': 'recompter'}, format='json')
        fixed = dict(rec, bills_10000=0, bills_5000=2)  # le gerant a recompte
        self.assertEqual(self.status_of(self.push(self.raw1, CLO, fixed)), 'ACCEPTED')
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual((c.bills_5000, c.is_rejected), (2, False), "resoumission ignoree, rejet toujours actif")

    @expectedFailure
    def test_BUG_983_pull_redescend_l_etat_des_clotures_du_poste(self):
        """Le poste doit connaitre la confirmation / le rejet (et son motif) pour que le gerant
        agisse ; le pull ne porte aucune information de cloture."""
        rec = self.clo()
        self.push(self.raw1, CLO, rec)
        cl(self.dirn).post(f"/api/treasury/closures/{rec['id']}/reject/", {'reason': 'recompter'}, format='json')
        r = push_client(self.raw1).get('/api/sync/pull/')
        self.assertEqual(r.status_code, 200)
        blob = r.content.decode().lower()
        self.assertTrue('is_rejected' in blob or 'rejection_reason' in blob or 'closures' in r.data,
                        "le pull ne redescend aucun etat de cloture")


class V970_972_Sync(Base13):
    def _client(self, **kw):
        c = make_client(self.n1, **kw)
        return c

    def _rec(self, c, **kw):
        d = {k: v for k, v in next(x for x in build_outbound_payload('C1')['records'][CLI]
                                   if x['id'] == str(c.pk)).items()}
        d.update(kw)
        return d

    def _cloud_edit(self, c, limit='90000'):
        Client.objects.filter(pk=c.pk).update(credit_limit=Dc(limit), identity_updated_at=timezone.now())

    # ---- BUG-970 payload
    def test_970_payload_porte_les_deux_versions_iso(self):
        c = self._client()
        Client.objects.filter(pk=c.pk).update(identity_updated_at=timezone.now())
        d = self._rec(c)
        self.assertIn('updated_at', d)
        self.assertIn('identity_updated_at', d)
        timezone.datetime.fromisoformat(d['updated_at'])
        timezone.datetime.fromisoformat(d['identity_updated_at'])
        c2 = self._client()
        self.assertIsNone(self._rec(c2)['identity_updated_at'])  # jamais edite : null, cle presente

    def test_970_push_ancien_ne_ecrase_pas_edition_cloud_et_est_trace(self):
        c = self._client()
        rec = self._rec(c, credit_limit='60000.00', identity_updated_at=(timezone.now() - timedelta(hours=1)).isoformat())
        self._cloud_edit(c)
        r = self.push(self.raw1, CLI, rec)
        self.assertEqual(self.status_of(r), 'ACCEPTED')
        self.assertEqual(Client.objects.get(pk=c.pk).credit_limit, Dc('90000.00'))
        log = SyncConflictLog.objects.get(conflict_type='IDENTITE_OBSOLETE')
        self.assertEqual((log.model_label, log.object_id, log.node_id), (CLI, str(c.pk), self.n1.pk))
        self.assertEqual(SystemNotification.objects.filter(title=NOTIF_TITLE).count(), 1)

    def test_970_push_recent_applique_et_poste_ancien_sans_version_applique(self):
        c = self._client()
        self._cloud_edit(c)
        recent = self._rec(c, credit_limit='70000.00', identity_updated_at=(timezone.now() + timedelta(minutes=1)).isoformat())
        self.push(self.raw1, CLI, recent)
        self.assertEqual(Client.objects.get(pk=c.pk).credit_limit, Dc('70000.00'))
        old = {k: v for k, v in self._rec(c, credit_limit='55000.00').items()
               if k not in ('updated_at', 'identity_updated_at')}
        self.push(self.raw1, CLI, old)
        self.assertEqual(Client.objects.get(pk=c.pk).credit_limit, Dc('55000.00'))

    def test_970_repli_sur_updated_at_quand_identity_updated_at_nul(self):
        c = self._client()
        self._cloud_edit(c)
        stale = self._rec(c, credit_limit='60000.00', identity_updated_at=None,
                          updated_at=(timezone.now() - timedelta(hours=2)).isoformat())
        self.push(self.raw1, CLI, stale)
        self.assertEqual(Client.objects.get(pk=c.pk).credit_limit, Dc('90000.00'))
        self.assertTrue(SyncConflictLog.objects.filter(conflict_type='IDENTITE_OBSOLETE').exists())

    def test_970_dates_invalides_ou_naives_sans_500(self):
        c = self._client()
        self._cloud_edit(c)
        for bad in ('pas-une-date', '2020-01-01T10:00:00', 12345, [], {}, '２０２０-01-01T10:00:00+00:00'):
            r = self.push(self.raw1, CLI, self._rec(c, credit_limit='1.00', identity_updated_at=bad,
                                                   updated_at=(timezone.now() - timedelta(hours=2)).isoformat()))
            self.assertEqual(r.status_code, 200)
        self.assertEqual(Client.objects.get(pk=c.pk).credit_limit, Dc('90000.00'),
                         "une version invalide ne doit jamais s'imposer a l'edition du Cloud")

    # ---- BUG-969
    def test_969_rejeu_identique_a_l_etat_cloud_sans_bruit(self):
        c = self._client()
        self._cloud_edit(c, '60000')
        rec = self._rec(c, credit_limit='60000.00', identity_updated_at=(timezone.now() - timedelta(hours=1)).isoformat())
        self.push(self.raw1, CLI, rec)
        self.assertFalse(SyncConflictLog.objects.exists())
        self.assertFalse(SystemNotification.objects.filter(title=NOTIF_TITLE).exists())

    def test_969_conflit_consultable_par_direction_comptable_admin_pas_par_gerant(self):
        c = self._client()
        self._cloud_edit(c)
        self.push(self.raw1, CLI, self._rec(c, credit_limit='60000.00',
                                            identity_updated_at=(timezone.now() - timedelta(hours=1)).isoformat()))
        for u, code in ((self.dirn, 200), (self.compt, 200), (self.adm, 200), (self.g1, 403), (self.fac, 403),
                        (self.liv, 403)):
            r = cl(u).get('/api/sync/conflicts/')
            self.assertEqual(r.status_code, code, (u.role, r.content))
        body = cl(self.dirn).get('/api/sync/conflicts/').content.decode()
        self.assertIn('IDENTITE_OBSOLETE', body)
        self.assertEqual(push_client(self.raw1).get('/api/sync/status/').data['unresolved_conflicts'], 1)

    @expectedFailure
    def test_BUG_982_pushs_obsoletes_repetes_ne_creent_pas_une_notification_chacun(self):
        """BUG-723 : une seule ligne de conflit non resolue, `occurrences` incrementee. Mais la
        notification WARNING est recreee a chaque push obsolete : un noeud defaillant inonde le
        centre de notifications du siege."""
        c = self._client()
        self._cloud_edit(c)
        for i in range(5):
            self.push(self.raw1, CLI, self._rec(c, credit_limit=f'{60000 + i}.00',
                                                identity_updated_at=(timezone.now() - timedelta(hours=1)).isoformat()))
        self.assertEqual(SyncConflictLog.objects.filter(conflict_type='IDENTITE_OBSOLETE').count(), 1)
        self.assertEqual(SyncConflictLog.objects.get(conflict_type='IDENTITE_OBSOLETE').occurrences, 5)
        self.assertLessEqual(SystemNotification.objects.filter(title=NOTIF_TITLE).count(), 1)

    # ---- derive d'horloge
    def test_derive_poste_en_retard_edition_legitime_ignoree_mais_tracee(self):
        c = self._client()
        self._cloud_edit(c)          # edition Cloud a T
        # le poste a edite APRES T (reellement) mais son horloge retarde de 3 h
        rec = self._rec(c, credit_limit='60000.00', identity_updated_at=(timezone.now() - timedelta(hours=3)).isoformat())
        self.push(self.raw1, CLI, rec)
        self.assertTrue(SyncConflictLog.objects.filter(conflict_type='IDENTITE_OBSOLETE', object_id=str(c.pk)).exists(),
                        "perte non tracee")

    @expectedFailure
    def test_BUG_981_derive_poste_en_avance_ecrase_l_edition_cloud_sans_trace(self):
        """Horloge du poste en avance de 2 h : une edition du poste anterieure (en temps reel) a
        celle du Cloud porte une version plus recente, s'impose et ecrase le plafond de la direction.
        Ni SyncConflictLog ni ActivityLog ne conserve la valeur ecrasee (perte non tracee)."""
        from core.models import ActivityLog
        c = self._client()
        self._cloud_edit(c)          # direction : 90 000
        rec = self._rec(c, credit_limit='60000.00', identity_updated_at=(timezone.now() + timedelta(hours=2)).isoformat())
        self.push(self.raw1, CLI, rec)
        c.refresh_from_db()
        traced = (c.credit_limit == Dc('90000.00') or SyncConflictLog.objects.filter(object_id=str(c.pk)).exists()
                  or ActivityLog.objects.filter(description__icontains=c.code).exists())
        self.assertTrue(traced, "plafond 90000 ecrase par 60000 sans aucune trace")

    def test_version_future_ne_empoisonne_pas_les_editions_suivantes_du_cloud(self):
        c = self._client()
        far = (timezone.now() + timedelta(days=3650)).isoformat()
        self.push(self.raw1, CLI, self._rec(c, credit_limit='60000.00', identity_updated_at=far))
        c.refresh_from_db()
        self.assertEqual(c.credit_limit, Dc('60000.00'))
        self.assertLess(c.identity_updated_at, timezone.now() + timedelta(minutes=1))
        # edition Cloud ensuite, puis push du poste date de maintenant : doit etre ignore (poste ancien)
        self._cloud_edit(c, '80000')
        self.push(self.raw1, CLI, self._rec(c, credit_limit='61000.00',
                                            identity_updated_at=(timezone.now() - timedelta(seconds=30)).isoformat()))
        self.assertEqual(Client.objects.get(pk=c.pk).credit_limit, Dc('80000.00'))

    # ---- BUG-972 (1) clients dupliques dans un lot
    def _new(self, **kw):
        d = {'id': str(uuid.uuid4()), 'node': 'C1', 'first_name': 'Premier', 'last_name': 'Fictif',
             'phone': '', 'address': '', 'node_origin': 'C1'}
        d.update(kw)
        return d

    def test_972_meme_id_deux_fois_dans_un_lot_premier_gagne(self):
        a = self._new()
        b = dict(a, first_name='Second')
        r = self.batch(self.raw1, {CLI: [a, b]})
        self.assertEqual([x['status'] for x in r.data['results'][CLI]], ['ACCEPTED', 'ACCEPTED'])
        self.assertEqual(Client.objects.get(pk=a['id']).first_name, 'Premier')
        self.assertEqual(Client.objects.filter(pk=a['id']).count(), 1)

    @expectedFailure
    def test_BUG_984_meme_id_casse_ou_format_different_est_le_meme_client(self):
        """BUG-972 (1) contourne : `process_push_batch` dedoublonne sur la chaine brute AVANT la
        normalisation UUID du preflight ; l'id en majuscules, sans tirets ou entre accolades passe
        pour un autre enregistrement et le second ecrase le premier dans le meme lot."""
        a = self._new()
        for variant in (a['id'].upper(), a['id'].replace('-', ''), '{' + a['id'] + '}'):
            self.batch(self.raw1, {CLI: [a, dict(a, id=variant, first_name='Intrus')]})
            self.assertEqual(Client.objects.get(pk=a['id']).first_name, 'Premier', variant)
            Client.objects.all().delete()
            a = self._new()

    def test_972_autre_lot_peut_modifier_l_identite(self):
        a = self._new()
        self.batch(self.raw1, {CLI: [a]})
        self.batch(self.raw1, {CLI: [dict(a, first_name='Corrige')]})
        self.assertEqual(Client.objects.get(pk=a['id']).first_name, 'Corrige')

    def test_972_ids_differents_meme_code_second_refuse_et_trace(self):
        a, b = self._new(code='DUP-C14'), self._new(code='DUP-C14')
        r = self.batch(self.raw1, {CLI: [a, b]})
        self.assertEqual([x['status'] for x in r.data['results'][CLI]], ['ACCEPTED', 'REJECTED'])
        self.assertTrue(SyncConflictLog.objects.filter(conflict_type='CODE_CLIENT_DUPLIQUE').exists())
        self.assertFalse(Client.objects.filter(pk=b['id']).exists())

    def test_972_doublon_de_lot_sur_autre_modele_non_regresse(self):
        r1, r2 = self.rep(), None
        r2 = dict(r1, total_cash_sales='1')
        self.batch(self.raw1, {RAP: [r1, r2]})
        self.assertEqual(FacturierReport.objects.filter(pk=r1['id']).count(), 1)
        self.assertEqual(FacturierReport.objects.get(pk=r1['id']).total_cash_sales, Dc('10000.00'))

    # ---- BUG-972 (2) billets entiers
    ACCEPT = (('4', 4), ('4 ', 4), (' 4', 4), ('04', 4), (4, 4), ('0', 0), ('', 0), (None, 0))
    REJECT = ('+4', '2.0', '1e3', -1, '-1', True, False, 4.0, 1e3, '٤', '４', '4_0', '0x4', '4,0', '--4', ' ',
              [], {}, '9' * 30, 10 ** 30)

    def _closure_with(self, val):
        CashClosure.objects.all().delete()
        rec = self.clo(bills_1000=val)
        r = self.push(self.raw1, CLO, rec)
        self.assertEqual(r.status_code, 200)
        return CashClosure.objects.filter(pk=rec['id']).first()

    def test_972_billets_valeurs_acceptees(self):
        for raw, exp in self.ACCEPT:
            c = self._closure_with(raw)
            self.assertIsNotNone(c, repr(raw))
            self.assertEqual(c.bills_1000, exp, repr(raw))
            self.assertEqual(c.physical_cash_total, Dc(exp * 1000 + 10000), repr(raw))

    def test_972_billets_valeurs_refusees(self):
        bad = [repr(v) for v in self.REJECT if self._closure_with(v) is not None]
        self.assertEqual(bad, [])

    def test_972_billets_refuses_par_denomination(self):
        for name in ('bills_20000', 'bills_10000', 'bills_5000', 'bills_500', 'bills_200', 'bills_100', 'bills_50'):
            CashClosure.objects.all().delete()
            rec = self.clo(**{name: '2.0'})
            self.push(self.raw1, CLO, rec)
            self.assertFalse(CashClosure.objects.filter(pk=rec['id']).exists(), name)

    def test_972_bordereau_billets_stricts(self):
        self.fund_livre('50000')
        for v in ('+4', '2.0', '1e3', -1, True, 4.0, '٤'):
            rec = self.vou(bills_1000=v)
            self.push(self.raws, VOU, rec)
            self.assertFalse(DisbursementVoucher.objects.filter(pk=rec['id']).exists(), repr(v))
        ok = self.vou(bills_1000=' 4 ', bills_500='02')
        self.push(self.raws, VOU, ok)
        v = DisbursementVoucher.objects.get(pk=ok['id'])
        self.assertEqual((v.bills_1000, v.bills_500), (4, 2))
        last = CashbookEntry.objects.order_by(*CashbookEntry.chain_order_desc()).first()
        self.assertEqual(last.running_balance, Dc('50000') - Dc('5000'))
        self.assertTrue(self.chain_ok())

    def test_972_billets_rest_vs_sync_memes_verdicts_sur_les_cas_courants(self):
        self.report(self.n1, 'A', '10000')
        for bad in ('1e3', -1, True):
            r = self.close(self.g1, {'bills_1000': bad})
            self.assertNotEqual(r.status_code, 201, repr(bad))
            self.assertLess(r.status_code, 500, repr(bad))


class V14_Voisins(Base13):
    def test_push_tous_modeles_hors_perimetre_rejetes_sans_500(self):
        for label in ('treasury.CashbookEntry', 'treasury.JournalEntry', 'treasury.DailySavings',
                      'blockchain.TamperAlert', 'blockchain.BlockchainSnapshot', 'core.User', 'sync.SyncConflictLog',
                      'finance.FinancialYear', 'commissions.ClientCommission'):
            for raw in (self.raw1, self.raws):
                r = push_client(raw).post(PUSH, {'batch_id': str(uuid.uuid4()),
                                                 'records': {label: [{'id': str(uuid.uuid4())}]}}, format='json')
                self.assertLess(r.status_code, 500, (label, r.content))
                for x in self.results_of(r):
                    self.assertNotEqual(x['status'], 'ACCEPTED', label)
        self.assertEqual(CashbookEntry.objects.count(), 0)

    def test_pull_ne_fuit_ni_livre_ni_clotures_d_un_autre_noeud(self):
        self.report(self.n2, 'A', '10000')
        d = self.close(self.g2, {'bills_10000': 1}).json()
        self.assertEqual(self.valider(d['id']).status_code, 200)
        self.assertEqual(self.verser(d['id']).status_code, 201)
        r = push_client(self.raw1).get('/api/sync/pull/')
        self.assertEqual(r.status_code, 200)
        blob = r.content.decode()
        self.assertNotIn(d['id'], blob)
        self.assertNotIn('running_balance', blob)
        self.assertNotIn('piece_number', blob)

    def test_aucune_notification_parasite_sur_flux_nominal(self):
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='10000', bills_10000=1)
        self.push(self.raw1, CLO, rec)
        before = SystemNotification.objects.count()
        for _ in range(3):
            self.push(self.raw1, CLO, rec)
        self.assertEqual(SystemNotification.objects.count(), before)
        self.assertFalse(SyncConflictLog.objects.exists())

    def test_depense_apres_validation_rejetee_laisse_un_conflit_ou_motif_precis(self):
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='10000', bills_10000=1)
        self.push(self.raw1, CLO, rec)
        self.valider(rec['id'], self.dirn)
        r = self.push(self.raw1, EXP, self.exp_rec(amount='500'))
        row = self.results_of(r)[0]
        self.assertEqual(row['status'], 'REJECTED')
        self.assertTrue(row.get('reason'))
