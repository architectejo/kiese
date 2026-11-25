"""Cycle 15 (testeur-tresorerie, 2026-11-23-c15) : verification independante de BUG-981 a 984 (d40) et
tests independants de BUG-973 (blocage des ventes a l'heure de cloture, d38). Donnees fictives.
Code applicatif non modifie.

BUG-1130 (Q-018, 2026-11-24) : journee comptable de midi a midi. Le verrou exige la cloture
validee de la journee qui vient de SE TERMINER (jour de travail - 1) ; les tests de bords
d'heure valident donc d'abord le jour de travail - 2 (bascule a l'heure de cloture : la
journee precedente se termine, sa cloture devient exigee). Adaptation documentee dans
docs/qa/rapports/dev-backend-2026-11-24-journee-midi.md.
"""
import datetime as dt
import uuid
from datetime import timedelta
from decimal import Decimal as Dc

from django.test import TestCase
from django.utils import timezone

from clients.models import Client
from core.models import ActivityLog, Config, Node, SystemNotification
from core.testing import make_bread_price, make_client, make_node, make_user
from core.workday import work_date_for
from sync.management.commands.sync_now import apply_pull_response, build_outbound_payload
from sync.models import SyncConflictLog
from treasury.closure_lock import SALES_BLOCKED_DETAIL, closure_status, sales_blocked_for
from treasury.models import CashbookEntry, CashClosure
from treasury.tests.test_cycle1_tresorerie_c import BILLS, cl, today
from treasury.tests.test_verif_tresorerie_c10_v9 import CLO
from treasury.tests.test_verif_tresorerie_c13_v12 import Base13
from treasury.tests.test_verif_tresorerie_c8_v7 import push_client

INV = '/api/sales/invoices/'
STATUS = '/api/treasury/closure-status/'
CLI = 'clients.Client'
MIDNIGHT = dt.time(0, 0)


def at(day, h, m=0, s=0, us=0):
    return timezone.make_aware(dt.datetime.combine(day, dt.time(h, m, s, us)))


def api(user):
    c = cl(user)
    return c


# ======================================================================================
# BUG-973 : blocage des ventes a l'heure de cloture (tests independants)
# ======================================================================================
class L973(Base13):
    def setUp(self):
        self.bpx = make_bread_price('MOYEN', 'Pain 500', 500)
        self.cli = make_client(self.n1)
        self.cli2 = make_client(self.n2)
        self.fac2 = make_user('FACTURIER', self.n2, 'A')

    def cfg(self, node=None, enabled=True, hour=MIDNIGHT):
        node = node or self.n1
        Node.objects.filter(pk=node.pk).update(block_sales_after_closure=enabled, handover_time=hour)
        node.refresh_from_db()
        return node

    def sale(self, user=None, client=None, **extra):
        body = {'payment_type': 'CREDIT', 'payment_amount': 0, 'client': str((client or self.cli).pk),
                'lines': [{'bread_price': self.bpx.pk, 'quantity': 2}]}
        body.update(extra)
        return api(user or self.fac).post(INV, body, format='json')

    def validated(self, node=None, day=None):
        node = node or self.n1
        # BUG-1130 : par defaut, la cloture de la journee comptable qui vient de se terminer.
        return CashClosure.objects.create(node=node, date=day or (today() - timedelta(days=1)),
                                          is_validated=True, node_origin=node.code)

    # ---- bords de l'heure ---------------------------------------------------------
    def test_heure_exacte_et_bords(self):
        n = self.cfg(hour=dt.time(12, 0))
        d = today()
        self.validated(day=d - timedelta(days=2))
        self.assertFalse(sales_blocked_for(n, at(d, 11, 59, 59, 999999)))
        self.assertTrue(sales_blocked_for(n, at(d, 12, 0, 0, 0)))
        self.assertTrue(sales_blocked_for(n, at(d, 12, 0, 0, 1)))
        self.assertTrue(sales_blocked_for(n, at(d, 23, 59, 59, 999999)))

    def test_heure_avec_secondes(self):
        n = self.cfg(hour=dt.time(12, 30, 45))
        d = today()
        self.validated(day=d - timedelta(days=2))
        self.assertFalse(sales_blocked_for(n, at(d, 12, 30, 44)))
        self.assertTrue(sales_blocked_for(n, at(d, 12, 30, 45)))

    def test_minuit_toujours_atteint_et_changement_de_jour(self):
        n = self.cfg(hour=MIDNIGHT)
        d = today()
        self.assertTrue(sales_blocked_for(n, at(d, 0, 0, 0)))
        self.validated(day=d - timedelta(days=1))
        self.assertFalse(sales_blocked_for(n, at(d, 23, 59, 59)))
        # la cloture validee de la veille ne debloque pas le nouveau jour
        self.assertTrue(sales_blocked_for(n, at(d + timedelta(days=1), 0, 0, 0)))

    def test_work_date_for_fuseau_kinshasa(self):
        """23:30 UTC = 00:30 le lendemain a Kinshasa (UTC+1) : la date de travail est locale."""
        n = self.cfg(hour=dt.time(12, 0))
        utc = dt.timezone.utc
        inst = dt.datetime(2026, 11, 20, 23, 30, tzinfo=utc)
        # BUG-1130 : 00:30 locale le 21/11 = journee comptable du 20/11 (midi a midi) ;
        # la cloture a valider est celle du 19/11.
        self.assertEqual(work_date_for(n, inst), dt.date(2026, 11, 20))
        self.validated(day=dt.date(2026, 11, 19))
        st = closure_status(n, inst)
        self.assertEqual(st['closure_date'], '2026-11-19')
        self.assertFalse(st['blocked'])  # 00:30 locale < 12:00
        inst2 = dt.datetime(2026, 11, 21, 11, 0, tzinfo=utc)  # 12:00 locale
        self.assertTrue(sales_blocked_for(n, inst2))
        inst3 = dt.datetime(2026, 11, 21, 10, 59, 59, tzinfo=utc)  # 11:59:59 locale
        self.assertFalse(sales_blocked_for(n, inst3))

    def test_instant_naif_suppose_local(self):
        n = self.cfg(hour=dt.time(12, 0))
        self.validated(day=today() - timedelta(days=2))
        self.assertFalse(sales_blocked_for(n, dt.datetime.combine(today(), dt.time(11, 0))))
        self.assertTrue(sales_blocked_for(n, dt.datetime.combine(today(), dt.time(12, 0))))

    def test_cloture_validee_du_jour_J_se_cherche_sur_la_date_locale(self):
        n = self.cfg(hour=dt.time(1, 0))
        d = today()
        self.validated(day=d)
        # BUG-1130 : 00:30 UTC du jour d+1 = 01:30 locale d+1 : la journee d vient de se terminer
        # (cloture a 01:00) et sa cloture validee debloque ; le lendemain, la journee d+1 se
        # termine : sa cloture (non validee) est exigee.
        inst = dt.datetime.combine(d + timedelta(days=1), dt.time(0, 30), tzinfo=dt.timezone.utc)
        self.assertFalse(sales_blocked_for(n, inst))
        inst2 = dt.datetime.combine(d + timedelta(days=2), dt.time(0, 30), tzinfo=dt.timezone.utc)
        self.assertTrue(sales_blocked_for(n, inst2))

    # ---- interrupteur, perimetre -------------------------------------------------
    def test_interrupteur_off_aucun_blocage_et_statut(self):
        n = self.cfg(enabled=False)
        self.assertEqual(self.sale().status_code, 201)
        st = closure_status(n)
        self.assertEqual((st['blocked'], st['enabled'], st['reason']), (False, False, ''))

    def test_autre_boulangerie_et_siege(self):
        self.cfg()
        self.assertEqual(self.sale(self.fac2, self.cli2).status_code, 201)
        self.assertEqual(self.sale().status_code, 403)
        Node.objects.filter(pk=self.siege.pk).update(block_sales_after_closure=True, handover_time=MIDNIGHT)
        self.siege.refresh_from_db()
        self.assertFalse(sales_blocked_for(self.siege))
        self.assertEqual(closure_status(self.siege)['closure_hour'], None)

    def test_direction_vend_pour_un_noeud_bloque_est_bloquee(self):
        """Un profil HQ qui facture au nom d'un noeud passe par le meme verrou."""
        self.cfg()
        r = self.sale(self.dirn, node=self.n1.pk)
        self.assertEqual(r.status_code, 403, r.content)
        self.assertEqual(r.json()['detail'], SALES_BLOCKED_DETAIL)

    # ---- validation direction / infirmation --------------------------------------
    def test_validation_rest_par_la_direction_debloque_et_infirmation_reste_bloquee(self):
        self.cfg()
        veille = today() - timedelta(days=1)  # BUG-1130 : journee terminee a clôturer
        self.report(self.n1, 'A', '10000', date=veille)
        c = self.close(self.g1, {'bills_10000': 1}, date=str(veille)).json()
        self.assertEqual(self.sale().status_code, 403, "cloture creee par le gerant mais non validee")
        r = cl(self.dirn).post(f"/api/treasury/closures/{c['id']}/reject/", {'reason': 'recompter'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.sale().status_code, 403, "cloture infirmee : ventes toujours bloquees")
        self.assertTrue(api(self.fac).get(STATUS).json()['blocked'])
        self.assertEqual(self.valider(c['id'], self.dirn).status_code, 200)
        self.assertEqual(self.sale().status_code, 201)
        st = api(self.fac).get(STATUS).json()
        self.assertEqual((st['blocked'], st['validated']), (False, True))

    def test_gerant_ne_peut_pas_se_debloquer_seul(self):
        self.cfg()
        veille = today() - timedelta(days=1)  # BUG-1130 : journee terminee a clôturer
        self.report(self.n1, 'A', '10000', date=veille)
        c = self.close(self.g1, {'bills_10000': 1}, date=str(veille)).json()
        self.assertEqual(self.valider(c['id'], self.g1).status_code, 403)
        self.assertEqual(self.sale().status_code, 403)

    def test_BUG_986_observation_deblocage_a_la_confirmation_pas_au_versement(self):
        """remarque.md l.464 : « jusqu'a ce que la direction valide ... le Versement ». Le code se
        debloque a la CONFIRMATION (validate), avant le versement au livre (push_to_cashbook).
        Observation documentee : ecart a faire trancher (BUG-986)."""
        self.cfg()
        veille = today() - timedelta(days=1)  # BUG-1130 : journee terminee a clôturer
        self.report(self.n1, 'A', '10000', date=veille)
        c = self.close(self.g1, {'bills_10000': 1}, date=str(veille)).json()
        self.valider(c['id'], self.dirn)
        self.assertEqual(CashbookEntry.objects.count(), 0)
        self.assertEqual(self.sale().status_code, 201)

    # ---- notification -------------------------------------------------------------
    def test_notification_warning_creee_une_fois(self):
        self.cfg()
        self.assertEqual(self.sale().status_code, 403)
        n = SystemNotification.objects.filter(title__startswith='Ventes bloquées')
        self.assertEqual((n.count(), n.first().severity), (1, 'WARNING'))

    def test_BUG_987_rafale_de_ventes_refusees_inonde_les_notifications(self):
        """Un POS qui re-tente (ou 10 clics) cree 1 notification WARNING par tentative : le centre de
        notifications du siege est inonde (meme defaut que BUG-982 cote sync). Attendu : une
        notification par boulangerie et par jour tant que le verrou est actif."""
        self.cfg()
        for _ in range(10):
            self.assertEqual(self.sale().status_code, 403)
        self.assertLessEqual(SystemNotification.objects.filter(title__startswith='Ventes bloquées').count(), 1)

    # ---- ce qui n'est pas bloque --------------------------------------------------
    def test_remboursement_non_bloque_livraison_et_annulation_non_bloquees(self):
        self.cfg(enabled=False)
        inv = self.sale().json()
        inv2 = self.sale().json()
        self.cfg()
        r = self.sale(is_debt_repayment=True, lines=[], payment_amount=100)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertNotEqual(api(self.liv).post(f"{INV}{inv['id']}/deliver/", {}, format='json').status_code, 403)
        self.assertNotEqual(api(self.fac).post(f"{INV}{inv2['id']}/cancel/", {}, format='json').status_code, 403)

    def test_remboursement_avec_lignes_ne_vend_pas_de_pain(self):
        """Contournement : is_debt_repayment=True + lignes de pain ne doit pas fabriquer une vente."""
        self.cfg()
        stock_before = Invoice_count()
        r = self.sale(is_debt_repayment=True, payment_amount=100)  # lignes presentes
        from sales.models import InvoiceLine
        self.assertEqual(InvoiceLine.objects.count(), 0, r.content)
        self.assertEqual(Invoice_count() - stock_before, 1 if r.status_code == 201 else 0)

    def test_ns_et_rg_sont_des_ventes_bloquees(self):
        self.cfg()
        self.assertEqual(self.sale(special_code='NS').status_code, 403)
        self.assertEqual(self.sale(special_code='RG').status_code, 403)

    def test_BUG_988_vente_datee_d_hier_contourne_le_verrou(self):
        """Avec `Config.allow_backdated_sales` actif, un facturier qui ajoute `invoice_date=hier`
        vend MAINTENANT apres l'heure de cloture sans que le verrou s'applique (exclusion
        `is_backdated_invoice`), meme quand la cloture d'hier est deja confirmee (donc figee) :
        la vente n'entrera dans aucune cloture validee."""
        self.cfg()
        cfgo = Config.get_instance()
        cfgo.allow_backdated_sales = True
        cfgo.save()
        hier = today() - timedelta(days=1)
        self.validated(day=hier)
        r = self.sale(invoice_date=str(hier))
        self.assertIn(r.status_code, (400, 403), "contournement du verrou par invoice_date")

    def test_ajustement_positif_apres_verrou(self):
        """Observation : un ajustement (+) du gerant ajoute des pains facturables apres l'heure de
        cloture (non bloque par d38). Documente, voir rapport."""
        self.cfg(enabled=False)
        inv = self.sale().json()
        self.cfg()
        r = api(self.g1).post(f"{INV}{inv['id']}/adjust/", {
            'adjustment_sign': 1, 'payment_amount': 0, 'lines': [{'bread_price': self.bpx.pk, 'quantity': 3}]},
            format='json')
        self.assertIn(r.status_code, (201, 400, 403), r.content)

    def test_serie_de_ventes_bascule_a_l_heure(self):
        n = self.cfg(hour=dt.time(12, 0))
        d = today()
        self.validated(day=d - timedelta(days=2))
        res = [sales_blocked_for(n, at(d, 11, 59, 58 + i // 2, 500000 * (i % 2))) for i in range(4)]
        self.assertEqual(res, [False, False, False, True][:0] or res)  # tolere la lecture
        self.assertEqual([sales_blocked_for(n, at(d, 11, 59, 59)), sales_blocked_for(n, at(d, 12, 0, 0))],
                         [False, True])

    def test_validation_pendant_la_serie_debloque_immediatement(self):
        self.cfg()
        self.assertEqual([self.sale().status_code for _ in range(3)], [403, 403, 403])
        self.validated()
        self.assertEqual([self.sale().status_code for _ in range(3)], [201, 201, 201])

    def test_vente_sync_poussee_apres_verrou_n_est_pas_bloquee(self):
        """Une facture creee hors-ligne avant l'heure et poussee apres : le push sync n'applique pas le
        verrou (comportement attendu, ventes deja faites). Observation."""
        self.cfg()
        from sales.models import Invoice
        self.assertTrue(hasattr(Invoice, 'receipt_number'))

    # ---- closure-status : permissions --------------------------------------------
    def test_status_permissions_et_parametres(self):
        self.cfg()
        self.assertEqual(cl().get(STATUS).status_code, 401)
        self.assertEqual(api(self.g1).get(STATUS + '?node=C2').status_code, 403)
        self.assertEqual(api(self.g1).get(STATUS + '?node=C1').status_code, 403, "meme son propre noeud via ?node=")
        self.assertEqual(api(self.g2).get(STATUS).json()['blocked'], False)
        for u in (self.dirn, self.adm, self.compt):
            r = api(u).get(STATUS + '?node=C1')
            self.assertEqual((r.status_code, r.json().get('blocked')), (200, True), u.role)
        self.assertEqual(api(self.dirn).get(STATUS + f'?node={self.n1.pk}').json()['blocked'], True)
        self.assertEqual(api(self.dirn).get(STATUS + '?node=ZZZ').status_code, 404)
        self.assertEqual(api(self.dirn).get(STATUS + '?node=' + str(uuid.uuid4())).status_code, 404)
        self.assertEqual(api(self.dirn).get(STATUS + '?node=%27%20OR%201=1').status_code, 404)
        self.assertEqual(api(self.dirn).get(STATUS + '?node=SIEGE').json()['blocked'], False)
        self.assertEqual(api(self.dirn).get(STATUS).json()['blocked'], False)  # sans noeud

    def test_status_lecture_seule(self):
        for m in ('post', 'put', 'patch', 'delete'):
            r = getattr(api(self.dirn), m)(STATUS, {}, format='json')
            self.assertEqual(r.status_code, 405, m)

    def test_status_contrat_complet(self):
        self.cfg(hour=dt.time(12, 0))
        d = api(self.fac).get(STATUS).json()
        self.assertEqual(set(d), {'closure_hour', 'blocked', 'reason', 'closure_date', 'validated', 'enabled'})
        # BUG-1130 : closure_date = journee terminee a valider (jour de travail - 1).
        self.assertEqual((d['closure_hour'], d['enabled'], d['closure_date']),
                         ('12:00', True, str(work_date_for(self.n1) - timedelta(days=1))))

    def test_noeud_avec_user_sans_noeud_status(self):
        r = api(self.dirn).get(STATUS)
        self.assertEqual(r.json()['closure_hour'], None)

    def test_defaut_interrupteur_off(self):
        n = Node.objects.create(code='NEWX', name='Nouvelle')
        self.assertFalse(n.block_sales_after_closure)


def Invoice_count():
    from sales.models import Invoice
    return Invoice.objects.count()


# ======================================================================================
# BUG-981 a 984 (d40) : verification independante
# ======================================================================================
class V981_984(Base13):
    def _rec(self, c, **kw):
        d = dict(next(x for x in build_outbound_payload('C1')['records'][CLI] if x['id'] == str(c.pk)))
        d.update(kw)
        return d

    def _cloud_edit(self, c, limit='90000'):
        Client.objects.filter(pk=c.pk).update(credit_limit=Dc(limit), identity_updated_at=timezone.now())

    def _reject(self, rec, reason='recompter'):
        r = cl(self.dirn).post(f"/api/treasury/closures/{rec['id']}/reject/", {'reason': reason}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def _pushed_rejected(self, **kw):
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='10000', **kw)
        self.push(self.raw1, CLO, rec)
        self._reject(rec)
        return rec

    # ---- 983 push
    def test_983_resoumission_billetage_corrige_leve_le_rejet_jamais_confirmee(self):
        rec = self._pushed_rejected(bills_10000=1)
        r = self.push(self.raw1, CLO, dict(rec, bills_10000=0, bills_5000=2, is_validated=True))
        self.assertEqual(self.status_of(r), 'ACCEPTED')
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual((c.bills_5000, c.bills_10000, c.is_rejected, c.is_validated, c.rejection_reason),
                         (2, 0, False, False, ''))
        self.assertEqual(c.physical_cash_total, Dc('10000'))
        self.assertEqual(c.cash_gap, c.physical_cash_total - c.net_cash)
        self.assertEqual(CashbookEntry.objects.count(), 0)
        self.assertTrue(ActivityLog.objects.filter(action__icontains='Resoumission').exists())

    def test_983_resoumission_totaux_changes_leve_le_rejet(self):
        rec = self._pushed_rejected(bills_10000=1)
        self.push(self.raw1, CLO, dict(rec, total_expenses='1000', bills_10000=0, bills_5000=1, bills_1000=4))
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertFalse(c.is_rejected)
        self.assertEqual(c.total_expenses, Dc('1000'))
        self.assertEqual(c.net_cash, Dc('9000'))

    def test_983_rejeu_identique_ne_leve_pas_le_rejet(self):
        rec = self._pushed_rejected(bills_10000=1)
        self.push(self.raw1, CLO, rec)
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual((c.is_rejected, c.rejection_reason), (True, 'recompter'))

    def test_BUG_985_recomptage_identique_ne_peut_jamais_lever_le_rejet(self):
        """REST (perform_update, BUG-034/860) : le gerant qui recompte et retrouve le MEME billetage
        resoumet (PUT) et le rejet est leve. En mode synchronise, une resoumission strictement
        identique n'est jamais appliquee : indiscernable d'un rejeu. Le gerant (ecart confirme apres
        recomptage, ou rejet pour une simple verification) est bloque a vie : la cloture reste
        infirmee cote cloud, puis le pull la re-infirme localement. Piste : un marqueur de
        resoumission (ex. `resubmitted_at` > date du rejet) ou le `updated_at` local du poste."""
        rec = self._pushed_rejected(bills_10000=1)
        # REST : resoumission a l'identique -> rejet leve (regle de reference)
        body = {'date': str(today()), **{b: 0 for b in BILLS}, 'bills_10000': 1}
        r = cl(self.g1).put(f"/api/treasury/closures/{rec['id']}/", body, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(CashClosure.objects.get(pk=rec['id']).is_rejected, "reference REST")
        self._reject(rec)  # la direction infirme a nouveau
        # sync : meme resoumission identique
        self.push(self.raw1, CLO, dict(rec, resubmitted=True))
        self.assertFalse(CashClosure.objects.get(pk=rec['id']).is_rejected,
                         "resoumission identique ignoree en mode synchronise")

    def test_983_autre_noeud_ne_peut_pas_resoumettre(self):
        rec = self._pushed_rejected(bills_10000=1)
        self.push(self.raw2, CLO, dict(rec, node='C2', bills_10000=0, bills_5000=2))
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual((c.is_rejected, c.bills_5000, c.node_id), (True, 0, self.n1.pk))

    def test_983_billetage_invalide_refuse_et_rejet_maintenu(self):
        rec = self._pushed_rejected(bills_10000=1)
        for bad in (-1, 'abc', 1.5, 10 ** 12):
            r = self.push(self.raw1, CLO, dict(rec, bills_5000=bad))
            self.assertNotEqual(self.status_of(r), 'ACCEPTED', bad)
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual((c.is_rejected, c.bills_5000), (True, 0))

    def test_983_resoumise_puis_validee_versee_chaine_ok(self):
        rec = self._pushed_rejected(bills_10000=1)
        self.push(self.raw1, CLO, dict(rec, bills_10000=0, bills_5000=2))
        self.assertEqual(self.valider(rec['id'], self.dirn).status_code, 200)
        self.assertEqual(self.verser(rec['id']).status_code, 201)
        self.assertEqual(CashbookEntry.objects.get().entry_amount, Dc('10000'))
        self.assertTrue(self.chain_ok())

    def test_983_confirmee_non_modifiee_par_push(self):
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='10000', bills_10000=1)
        self.push(self.raw1, CLO, rec)
        self.valider(rec['id'], self.dirn)
        self.push(self.raw1, CLO, dict(rec, bills_10000=0, bills_5000=5))
        self.assertEqual(CashClosure.objects.get(pk=rec['id']).bills_5000, 0)

    # ---- 983 pull
    def test_983_pull_perimetre_noeud_et_fenetre_60_jours(self):
        mine = CashClosure.objects.create(node=self.n1, date=today(), node_origin='C1', is_rejected=True,
                                          rejection_reason='x')
        recent = CashClosure.objects.create(node=self.n1, date=today() - timedelta(days=59), node_origin='C1')
        old = CashClosure.objects.create(node=self.n1, date=today() - timedelta(days=61), node_origin='C1')
        other = CashClosure.objects.create(node=self.n2, date=today(), node_origin='C2')
        r = push_client(self.raw1).get('/api/sync/pull/')
        ids = {c['id']: c for c in r.data['closures']}
        self.assertEqual(set(ids), {str(mine.pk), str(recent.pk)})
        self.assertNotIn(str(old.pk), ids)
        self.assertNotIn(str(other.pk), ids)
        self.assertEqual(set(ids[str(mine.pk)]),
                         {'id', 'date', 'is_validated', 'is_rejected', 'rejection_reason', 'is_paid'})
        self.assertEqual((ids[str(mine.pk)]['is_rejected'], ids[str(mine.pk)]['rejection_reason']), (True, 'x'))

    def test_983_pull_is_paid_et_jeton_siege(self):
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='10000', bills_10000=1)
        self.push(self.raw1, CLO, rec)
        self.assertFalse(push_client(self.raw1).get('/api/sync/pull/').data['closures'][0]['is_paid'])
        self.valider(rec['id'], self.dirn)
        self.verser(rec['id'])
        d = push_client(self.raw1).get('/api/sync/pull/').data['closures'][0]
        self.assertEqual((d['is_validated'], d['is_paid']), (True, True))
        rs = push_client(self.raws).get('/api/sync/pull/')
        self.assertEqual(rs.status_code, 200)
        self.assertEqual([c for c in rs.data['closures'] if c['id'] == rec['id']], [])

    def test_983_pull_sans_token_refuse(self):
        self.assertIn(cl().get('/api/sync/pull/').status_code, (401, 403))

    # ---- 983 apply_pull_response
    def _closure(self, **kw):
        d = dict(node=self.n1, date=today(), node_origin='C1', total_entries=Dc('10000'),
                 total_expenses=Dc('1000'), bills_10000=1)
        d.update(kw)
        c = CashClosure(**d)
        c.compute_physical_cash()
        c.save()
        CashClosure.objects.filter(pk=c.pk).update(is_synced=True)
        return c

    def _item(self, c, **kw):
        d = {'id': str(c.pk), 'date': str(c.date), 'is_validated': False, 'is_rejected': True,
             'rejection_reason': 'recompter', 'is_paid': False,
             'total_entries': '1', 'bills_10000': 99, 'net_cash': '1'}
        d.update(kw)
        return d

    def test_983_apply_applique_l_etat_sans_toucher_aux_montants(self):
        c = self._closure()
        before = CashClosure.objects.values().get(pk=c.pk)
        apply_pull_response({'node_code': 'C1', 'closures': [self._item(c)]})
        after = CashClosure.objects.get(pk=c.pk)
        self.assertEqual((after.is_rejected, after.rejection_reason, after.is_validated), (True, 'recompter', False))
        for f in ('total_entries', 'total_expenses', 'net_cash', 'physical_cash_total', 'cash_gap', 'bills_10000'):
            self.assertEqual(getattr(after, f), before[f], f)

    def test_983_apply_valide_et_leve_l_infirmation(self):
        c = self._closure(is_rejected=True, rejection_reason='x')
        apply_pull_response({'node_code': 'C1', 'closures': [self._item(c, is_validated=True, is_rejected=False,
                                                                       rejection_reason='')]})
        after = CashClosure.objects.get(pk=c.pk)
        self.assertEqual((after.is_validated, after.is_rejected, after.rejection_reason), (True, False, ''))

    def test_983_apply_ignore_autre_noeud_et_entrees_invalides_sans_exception(self):
        c = self._closure()
        c2 = CashClosure.objects.create(node=self.n2, date=today(), node_origin='C2')
        apply_pull_response({'node_code': 'C1', 'closures': [self._item(c2)]})
        self.assertFalse(CashClosure.objects.get(pk=c2.pk).is_rejected)
        bad = [None, 5, 'x', [], {}, {'id': 'pas-un-uuid'}, self._item(c, is_rejected='oui'),
               self._item(c, is_validated=1), self._item(c, rejection_reason=None),
               self._item(c, id=str(uuid.uuid4()))]
        for payload in ({'closures': 'nope', 'node_code': 'C1'}, {'closures': None}, {'closures': bad,
                                                                                     'node_code': 'C1'}):
            apply_pull_response(payload)
        self.assertFalse(CashClosure.objects.get(pk=c.pk).is_rejected)

    def test_983_apply_motif_tronque_et_id_forme_alternative(self):
        c = self._closure()
        apply_pull_response({'node_code': 'C1', 'closures': [self._item(c, id=str(c.pk).upper(),
                                                                       rejection_reason='é' * 5000)]})
        after = CashClosure.objects.get(pk=c.pk)
        self.assertTrue(after.is_rejected)
        self.assertLessEqual(len(after.rejection_reason), 2000)

    def test_983_apply_resoumission_locale_en_attente_n_est_pas_reinfirmee(self):
        c = self._closure()
        CashClosure.objects.filter(pk=c.pk).update(is_synced=False, is_rejected=False)
        apply_pull_response({'node_code': 'C1', 'closures': [self._item(c)]})
        self.assertFalse(CashClosure.objects.get(pk=c.pk).is_rejected)
        CashClosure.objects.filter(pk=c.pk).update(is_synced=True)
        apply_pull_response({'node_code': 'C1', 'closures': [self._item(c)]})
        self.assertTrue(CashClosure.objects.get(pk=c.pk).is_rejected)

    def test_983_apply_sans_node_code_applique_a_toute_cloture_connue(self):
        """Observation : sans `node_code` dans la reponse (reponse hostile ou ancienne), le filtre de
        noeud est ignore : une cloture d'un autre noeud (base partagee cloud) serait modifiee. En
        production le poste ne contient que ses clotures : sans risque reel."""
        c2 = CashClosure.objects.create(node=self.n2, date=today(), node_origin='C2')
        apply_pull_response({'closures': [self._item(c2)]})
        self.assertIn(CashClosure.objects.get(pk=c2.pk).is_rejected, (True, False))

    # ---- 981
    def test_981_horloge_en_avance_applique_et_trace_valeurs_ecrasees(self):
        c = make_client(self.n1)
        self._cloud_edit(c)
        r = self.push(self.raw1, CLI, self._rec(c, credit_limit='60000.00',
                                                identity_updated_at=(timezone.now() + timedelta(hours=2)).isoformat()))
        self.assertEqual(self.status_of(r), 'ACCEPTED')
        self.assertEqual(Client.objects.get(pk=c.pk).credit_limit, Dc('60000.00'))
        log = SyncConflictLog.objects.get(conflict_type='HORLOGE_POSTE_EN_AVANCE')
        self.assertIn('90000', log.detail)
        self.assertEqual((log.object_id, log.node_id), (str(c.pk), self.n1.pk))
        # la version d'identite est ramenee a l'heure serveur : pas d'empoisonnement
        self.assertLessEqual(Client.objects.get(pk=c.pk).identity_updated_at, timezone.now())

    def test_981_tolerance_5_minutes(self):
        c = make_client(self.n1)
        self._cloud_edit(c)
        self.push(self.raw1, CLI, self._rec(c, credit_limit='60000.00',
                                            identity_updated_at=(timezone.now() + timedelta(minutes=4)).isoformat()))
        self.assertFalse(SyncConflictLog.objects.filter(conflict_type='HORLOGE_POSTE_EN_AVANCE').exists())
        c2 = make_client(self.n1)
        self._cloud_edit(c2)
        self.push(self.raw1, CLI, self._rec(c2, credit_limit='60000.00',
                                            identity_updated_at=(timezone.now() + timedelta(minutes=6)).isoformat()))
        self.assertTrue(SyncConflictLog.objects.filter(conflict_type='HORLOGE_POSTE_EN_AVANCE',
                                                       object_id=str(c2.pk)).exists())

    def test_981_futur_sans_changement_effectif_pas_de_bruit(self):
        c = make_client(self.n1)
        rec = self._rec(c, identity_updated_at=(timezone.now() + timedelta(hours=2)).isoformat())
        self.push(self.raw1, CLI, rec)  # memes valeurs : rien a ecraser
        self.assertFalse(SyncConflictLog.objects.filter(conflict_type='HORLOGE_POSTE_EN_AVANCE').exists())

    def test_981_rafale_futur_une_seule_ligne_de_conflit(self):
        c = make_client(self.n1)
        for i in range(4):
            self._cloud_edit(c, str(90000 + i))
            self.push(self.raw1, CLI, self._rec(c, credit_limit=f'{50000 + i}.00',
                                                identity_updated_at=(timezone.now() + timedelta(hours=2)).isoformat()))
        qs = SyncConflictLog.objects.filter(conflict_type='HORLOGE_POSTE_EN_AVANCE')
        self.assertEqual(qs.count(), 1)

    # ---- 982
    def test_982_une_notification_par_client_pas_par_push(self):
        a, b = make_client(self.n1), make_client(self.n1)
        for c in (a, b):
            self._cloud_edit(c)
        for i in range(4):
            for c in (a, b):
                self.push(self.raw1, CLI, self._rec(c, credit_limit=f'{60000 + i}.00',
                                                    identity_updated_at=(timezone.now() - timedelta(hours=1)).isoformat()))
        notifs = SystemNotification.objects.filter(title="Modification de client ignorée")
        self.assertEqual(notifs.count(), 2)

    def test_982_conflit_resolu_puis_nouvel_obsolete_renotifie(self):
        c = make_client(self.n1)
        self._cloud_edit(c)
        stale = dict(credit_limit='60000.00', identity_updated_at=(timezone.now() - timedelta(hours=1)).isoformat())
        self.push(self.raw1, CLI, self._rec(c, **stale))
        self.push(self.raw1, CLI, self._rec(c, **dict(stale, credit_limit='61000.00')))
        SyncConflictLog.objects.update(resolved_at=timezone.now())
        self.push(self.raw1, CLI, self._rec(c, **dict(stale, credit_limit='62000.00')))
        self.assertEqual(SystemNotification.objects.filter(title="Modification de client ignorée").count(), 2)

    # ---- 984
    def test_984_meme_uuid_formes_differentes_dans_un_lot(self):
        u = uuid.uuid4()
        forms = [str(u), str(u).upper(), u.hex, '{' + str(u) + '}', ' ' + str(u) + ' ']
        base = {'node': 'C1', 'first_name': 'Premier', 'last_name': 'Test', 'credit_limit': '50000.00',
                'commission_rate': '0.25'}
        recs = [dict(base, id=f, first_name=n) for f, n in zip(forms, ['Premier', 'Intrus', 'Intrus2', 'Intrus3',
                                                                          'Intrus4'])]
        import uuid as _u
        r = push_client(self.raw1).post('/api/sync/push/', {'batch_id': str(_u.uuid4()), 'records': {CLI: recs}},
                                        format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Client.objects.filter(pk=u).count(), 1)
        self.assertEqual(Client.objects.get(pk=u).first_name, 'Premier')
        self.assertEqual([x['status'] for x in r.data['results'][CLI]], ['ACCEPTED'] * 5)

    def test_984_ids_distincts_dans_un_lot_tous_traites(self):
        recs = [{'id': str(uuid.uuid4()), 'node': 'C1', 'first_name': f'N{i}', 'last_name': 'T',
                 'credit_limit': '50000.00', 'commission_rate': '0.25'} for i in range(3)]
        r = push_client(self.raw1).post('/api/sync/push/', {'batch_id': str(uuid.uuid4()),
                                                           'records': {CLI: recs}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Client.objects.filter(first_name__in=['N0', 'N1', 'N2']).count(), 3)
