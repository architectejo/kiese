"""Cycle 16 partie C (testeur-tresorerie, 2026-11-23-c16) : verification independante de BUG-985
(resubmit_count), BUG-987 (dedoublonnage notification), BUG-988 (ventes/ajustements sur jour confirme),
pistes voisines et journee complete 2 postes + cloud. Donnees fictives. Code applicatif non modifie.
"""
import datetime as dt
from datetime import timedelta
from decimal import Decimal as Dc
from unittest import expectedFailure

from core.models import Config, Node, SystemNotification
from core.testing import make_bread_price, make_client, make_user
from sync.management.commands.sync_now import build_outbound_payload
from treasury.models import CashbookEntry, CashClosure
from treasury.tests.test_cycle1_tresorerie_c import BILLS, cl, today
from treasury.tests.test_verif_tresorerie_c10_v9 import CLO
from treasury.tests.test_verif_tresorerie_c13_v12 import Base13

INV = '/api/sales/invoices/'
MIDNIGHT = dt.time(0, 0)


class R985(Base13):
    def _pushed_rejected(self, **kw):
        self.report(self.n1, 'A', '10000')
        rec = self.clo(total_entries='10000', **kw)
        self.push(self.raw1, CLO, rec)
        self._reject(rec)
        return rec

    def _reject(self, rec):
        r = cl(self.dirn).post(f"/api/treasury/closures/{rec['id']}/reject/", {'reason': 'recompter'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def _rejected(self, rec):
        return CashClosure.objects.get(pk=rec['id']).is_rejected

    def _put(self, rec, **bills):
        body = {'date': str(today()), **{b: 0 for b in BILLS}, 'bills_10000': 1, **bills}
        return cl(self.g1).put(f"/api/treasury/closures/{rec['id']}/", body, format='json')

    def test_migration_defaut_zero_et_rest_incremente(self):
        rec = self._pushed_rejected()
        self.assertEqual(CashClosure.objects.get(pk=rec['id']).resubmit_count, 0)
        self.assertEqual(self._put(rec).status_code, 200)
        self.assertEqual(CashClosure.objects.get(pk=rec['id']).resubmit_count, 1)
        self._reject(rec)
        self.assertEqual(self._put(rec).status_code, 200)
        self.assertEqual(CashClosure.objects.get(pk=rec['id']).resubmit_count, 2)

    def test_payload_exporte_le_compteur(self):
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self._reject(d)  # BUG-996 : seule une resoumission apres infirmation incremente le compteur
        self.assertEqual(self._put({'id': d['id']}).status_code, 200)
        rows = build_outbound_payload('C1')['records'][CLO]
        self.assertEqual([x['resubmit_count'] for x in rows if x['id'] == d['id']], [1])

    def test_compteur_superieur_leve_a_contenu_identique_jamais_confirmee(self):
        rec = self._pushed_rejected()
        self.push(self.raw1, CLO, dict(rec, resubmit_count=1, is_validated=True))
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual((c.is_rejected, c.is_validated, c.resubmit_count), (False, False, 1))
        self.assertFalse(CashbookEntry.objects.exists())

    def test_compteur_egal_ou_inferieur_est_un_rejeu(self):
        rec = self._pushed_rejected()
        for n in (0, -1):
            self.push(self.raw1, CLO, dict(rec, resubmit_count=n))
            self.assertTrue(self._rejected(rec), n)

    def test_compteur_de_type_invalide_ne_leve_pas(self):
        rec = self._pushed_rejected()
        for bad in (True, '5', 2.5, [], {}, None):
            self.push(self.raw1, CLO, dict(rec, resubmit_count=bad))
            self.assertTrue(self._rejected(rec), repr(bad))

    def test_compteur_rejoue_ne_leve_pas_une_seconde_infirmation(self):
        rec = self._pushed_rejected()
        self.push(self.raw1, CLO, dict(rec, resubmit_count=1))
        self.assertFalse(self._rejected(rec))
        self._reject(rec)
        self.push(self.raw1, CLO, dict(rec, resubmit_count=1))  # rejeu du meme lot
        self.assertTrue(self._rejected(rec))
        self.push(self.raw1, CLO, dict(rec, resubmit_count=2))  # vraie 2e resoumission
        self.assertFalse(self._rejected(rec))

    def test_compteur_enorme_borne_et_autre_noeud_refuse(self):
        rec = self._pushed_rejected()
        self.push(self.raw2, CLO, dict(rec, node='C2', resubmit_count=5))
        self.assertTrue(self._rejected(rec))
        self.push(self.raw1, CLO, dict(rec, resubmit_count=10 ** 12))
        self.assertEqual(CashClosure.objects.get(pk=rec['id']).resubmit_count, 10 ** 6)

    def test_ancien_chemin_resubmitted_true_sans_compteur(self):
        rec = self._pushed_rejected()
        self.push(self.raw1, CLO, dict(rec, resubmitted=True))
        c = CashClosure.objects.get(pk=rec['id'])
        self.assertEqual((c.is_rejected, c.resubmit_count), (False, 1))
        # observation : chaque infirmation est relevee par un simple push du poste, sans recomptage
        for i in range(2, 5):
            self._reject(rec)
            self.push(self.raw1, CLO, dict(rec, resubmitted=True))
            self.assertFalse(self._rejected(rec))
            self.assertEqual(CashClosure.objects.get(pk=rec['id']).resubmit_count, i)

    def test_compteur_forge_observation(self):
        """Le compteur n'est pas un secret : tout porteur du jeton du noeud peut le forger (comme il
        peut deja changer un billet). Pas d'escalade de privilege. Documente."""
        rec = self._pushed_rejected()
        self.push(self.raw1, CLO, dict(rec, resubmit_count=99))
        self.assertFalse(self._rejected(rec))

    def test_rejeu_d_un_enregistrement_anterieur_a_l_infirmation(self):
        """Poste : edition (PUT) d'une cloture NON infirmee -> compteur local 1 (le cloud reste a 0 car
        il n'incremente que sur une cloture infirmee). La direction infirme ; le rejeu du MEME
        enregistrement (compteur 1 > 0), jamais incremente apres l'infirmation, leve l'infirmation sans
        que le gerant ait recompte."""
        self.report(self.n1, 'A', '10000')
        d = self.close(self.g1, {'bills_10000': 1}).json()
        self.assertEqual(self._put(d).status_code, 200)
        rec = next(x for x in build_outbound_payload('C1')['records'][CLO] if x['id'] == d['id'])
        self.assertEqual(rec['resubmit_count'], 0)  # BUG-996 : une edition non infirmee n'incremente plus
        CashClosure.objects.filter(pk=d['id']).delete()           # cloud : premiere remontee
        self.push(self.raw1, CLO, dict(rec, resubmit_count=0))     # (cloud a 0)
        self._reject(rec)
        self.push(self.raw1, CLO, rec)                             # rejeu du lot ancien, compteur 1
        self.assertTrue(self._rejected(rec), "infirmation levee par un enregistrement anterieur")


class R987_988(Base13):
    def setUp(self):
        self.bpx = make_bread_price('MOYEN', 'Pain 500', 500)
        self.cli = make_client(self.n1)

    def cfg(self, enabled=True):
        Node.objects.filter(pk=self.n1.pk).update(block_sales_after_closure=enabled, handover_time=MIDNIGHT)
        self.n1.refresh_from_db()

    def backdate_on(self):
        c = Config.get_instance()
        c.allow_backdated_sales = True
        c.save()

    def sale(self, user=None, client=None, **extra):
        body = {'payment_type': 'CREDIT', 'payment_amount': 0, 'client': str(client or self.cli.pk),
                'lines': [{'bread_price': self.bpx.pk, 'quantity': 2}]}
        body.update(extra)
        return cl(user or self.fac).post(INV, body, format='json')

    def validated(self, day, **kw):
        return CashClosure.objects.create(node=self.n1, date=day, node_origin='C1', **{'is_validated': True, **kw})

    def blocked_count(self, **f):
        return SystemNotification.objects.filter(title__startswith='Ventes bloquées', **f).count()

    # ---- 987
    def test_987_rafale_une_notification(self):
        self.cfg()
        for _ in range(10):
            self.assertEqual(self.sale().status_code, 403)
        self.assertEqual(self.blocked_count(), 1)

    def test_987_apres_lecture_nouvelle_notification(self):
        self.cfg()
        self.sale()
        SystemNotification.objects.filter(title__startswith='Ventes bloquées').update(is_read=True)
        self.sale()
        self.assertEqual(self.blocked_count(), 2)

    def test_987_notification_d_un_autre_jour_ne_masque_pas(self):
        self.cfg()
        self.sale()
        SystemNotification.objects.filter(title__startswith='Ventes bloquées').update(
            created_at=SystemNotification.objects.first().created_at - timedelta(days=2))
        self.sale()
        self.assertEqual(self.blocked_count(), 2)

    def test_987_par_boulangerie(self):
        self.cfg()
        Node.objects.filter(pk=self.n2.pk).update(block_sales_after_closure=True, handover_time=MIDNIGHT)
        fac2 = make_user('FACTURIER', self.n2, 'A')
        cli2 = make_client(self.n2)
        self.sale()
        self.sale(user=make_user('FACTURIER', self.n1, 'B'))
        self.sale(user=fac2, client=cli2.pk)
        self.assertEqual(self.blocked_count(node_origin='C1'), 1)
        self.assertEqual(self.blocked_count(node_origin='C2'), 1)

    # ---- 988
    def test_988_vente_antidatee_jour_confirme_refusee(self):
        self.backdate_on()
        hier = today() - timedelta(days=1)
        self.validated(hier)
        r = self.sale(invoice_date=str(hier))
        self.assertEqual(r.status_code, 403, r.content)
        self.assertIn('confirmée', r.json()['detail'])

    def test_988_vente_antidatee_jour_non_cloture_ou_infirme_permise(self):
        self.backdate_on()
        j1, j2 = today() - timedelta(days=1), today() - timedelta(days=2)
        self.assertEqual(self.sale(invoice_date=str(j1)).status_code, 201)
        self.validated(j2, is_validated=False, is_rejected=True, rejection_reason='x')
        self.assertEqual(self.sale(invoice_date=str(j2)).status_code, 201)

    def test_988_vente_antidatee_autre_boulangerie_non_affectee(self):
        self.backdate_on()
        hier = today() - timedelta(days=1)
        CashClosure.objects.create(node=self.n2, date=hier, is_validated=True, node_origin='C2')
        self.assertEqual(self.sale(invoice_date=str(hier)).status_code, 201)

    def test_988_remboursement_antidate_permis_meme_jour_confirme(self):
        self.backdate_on()
        hier = today() - timedelta(days=1)
        self.validated(hier)
        r = self.sale(invoice_date=str(hier), is_debt_repayment=True, lines=[], payment_amount=100)
        self.assertEqual(r.status_code, 201, r.content)

    def _adj(self, sign, **extra):
        inv = self.sale().json()
        body = {'adjustment_sign': sign, 'payment_amount': 0,
                'lines': [{'bread_price': self.bpx.pk, 'quantity': 1}], **extra}
        return cl(self.g1).post(f"{INV}{inv['id']}/adjust/", body, format='json')

    def test_988_ajustement_plus_jour_confirme_refuse_moins_permis(self):
        self.backdate_on()
        hier = today() - timedelta(days=1)
        self.validated(hier)
        r = self._adj(1, invoice_date=str(hier))
        self.assertEqual(r.status_code, 403, r.content)
        self.assertIn('Ajustement refusé', r.json()['detail'])
        r = self._adj(-1, invoice_date=str(hier))
        self.assertEqual(r.status_code, 201, r.content)

    def test_988_ajustement_sur_aujourd_hui_confirme(self):
        self.validated(today())
        self.assertEqual(self._adj(1).status_code, 403)
        self.assertEqual(self._adj(-1).status_code, 201)

    def test_988_ajustement_plus_jour_non_confirme_permis(self):
        self.assertEqual(self._adj(1).status_code, 201)

    def test_988_observation_vente_du_jour_apres_confirmation(self):
        """Verrou ON, cloture du jour confirmee : la vente du jour est acceptee (deblocage a la
        confirmation, BUG-986 a clarifier) et n'entre dans aucune cloture. Observation, non ticket."""
        self.cfg()
        self.validated(today())
        self.assertEqual(self.sale().status_code, 201)


class R_Journee(Base13):
    def test_journee_2_postes_rejet_recomptage_resoumission_versement(self):
        self.report(self.n1, 'A', '15000')
        self.report(self.n2, 'A', '20000')
        ids = {}
        for code, raw, ent in (('C1', self.raw1, '15000'), ('C2', self.raw2, '20000')):
            rec = self.clo(node=code, total_entries=ent, bills_10000=0, bills_5000=int(Dc(ent) // 5000))
            self.assertEqual(self.status_of(self.push(raw, CLO, rec)), 'ACCEPTED')
            ids[code] = rec
        rec1 = ids['C1']
        r = cl(self.dirn).post(f"/api/treasury/closures/{rec1['id']}/reject/", {'reason': 'recompter'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        # recomptage identique, resoumission (compteur 1) puis rejeu du lot : une seule levee
        self.push(self.raw1, CLO, dict(rec1, resubmit_count=1))
        self.push(self.raw1, CLO, dict(rec1, resubmit_count=1))
        c1 = CashClosure.objects.get(pk=rec1['id'])
        self.assertEqual((c1.is_rejected, c1.is_validated, c1.resubmit_count), (False, False, 1))
        for rec in ids.values():
            self.assertEqual(self.valider(rec['id']).status_code, 200)
            self.assertEqual(self.verser(rec['id']).status_code, 201)
        self.assertEqual(CashbookEntry.objects.count(), 2)
        self.assertEqual(sum(e.entry_amount for e in CashbookEntry.objects.all()), Dc('35000'))
        self.assertTrue(self.chain_ok())
        # vente antidatee sur le jour confirme : refusee
        cfg = Config.get_instance()
        cfg.allow_backdated_sales = True
        cfg.save()
        hier = today() - timedelta(days=1)
        CashClosure.objects.filter(pk=rec1['id']).update(date=hier)
        bpx = make_bread_price('MOYEN', 'Pain 500', 500)
        cli = make_client(self.n1)
        r = cl(self.fac).post(INV, {'payment_type': 'CREDIT', 'payment_amount': 0, 'client': str(cli.pk),
                                    'invoice_date': str(hier),
                                    'lines': [{'bread_price': bpx.pk, 'quantity': 1}]}, format='json')
        self.assertEqual(r.status_code, 403, r.content)
        # rejeu apres versement : rien ne change
        self.push(self.raw1, CLO, dict(rec1, resubmit_count=9, is_validated=True))
        self.assertEqual(CashbookEntry.objects.count(), 2)
        self.assertTrue(self.chain_ok())
