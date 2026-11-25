"""D38 / BUG-973 : blocage des ventes après l'heure de clôture (remarque.md l.464/488).
Heure de clôture = Node.handover_time ; interrupteur Node.block_sales_after_closure.
Données fictives. Pas de rotation 24 h (Q-017 à Q-021 sans réponse).

BUG-1130 (Q-018, 2026-11-24) : journée comptable de midi à midi. Le verrou exige la
validation de la clôture de la journée qui vient de SE TERMINER (jour de travail - 1) ;
« avant l'heure » signifie donc : la clôture de la journée terminée est validée et la
journée en cours se poursuit. Tests adaptés en conséquence (une clôture validée pour le
jour calendaire courant ne débloque plus rien)."""
import datetime as dt

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Node, SystemNotification
from core.testing import make_bread_price, make_client, make_node, make_user
from core.workday import work_date_for
from treasury.closure_lock import SALES_BLOCKED_DETAIL, closure_status, sales_blocked_for
from treasury.models import CashClosure

INV = '/api/sales/invoices/'
STATUS = '/api/treasury/closure-status/'
PASSED = dt.time(0, 0)       # heure déjà atteinte à tout instant de la journée
FUTURE = dt.time(23, 59, 59)


def api(user):
    c = APIClient()
    c.raise_request_exception = False
    c.force_authenticate(user)
    return c


class D38(TestCase):
    def setUp(self):
        self.n1 = make_node(code='DB1')
        self.n2 = make_node(code='DB2')
        self.fa1 = make_user('FACTURIER', node=self.n1, team='A', username='db1_fa')
        self.fa2 = make_user('FACTURIER', node=self.n2, team='A', username='db2_fa')
        self.lv1 = make_user('LIVREUR', node=self.n1, team='A', username='db1_lv')
        self.dirn = make_user('DIRECTION', node=None, username='db_dir')
        self.bp = make_bread_price('DB3', 'Pain 300', 300)
        self.cl1 = make_client(self.n1)
        self.cl2 = make_client(self.n2)

    def cfg(self, node, enabled=True, hour=PASSED):
        node.block_sales_after_closure = enabled
        node.handover_time = hour
        node.save()

    def sale(self, user, client, **extra):
        body = {'payment_type': 'CREDIT', 'payment_amount': 0, 'client': str(client.pk),
                'lines': [{'bread_price': self.bp.pk, 'quantity': 2}]}
        body.update(extra)
        return api(user).post(INV, body, format='json')

    def validate_closure(self, node, day=None):
        # BUG-1130 : par défaut, la clôture de la journée comptable qui vient de se terminer.
        return CashClosure.objects.create(
            node=node, date=day or (work_date_for(node) - dt.timedelta(days=1)), is_validated=True,
            node_origin=node.code)

    def test_interrupteur_off_comportement_inchange(self):
        self.cfg(self.n1, enabled=False)
        self.assertEqual(self.sale(self.fa1, self.cl1).status_code, 201)
        self.assertFalse(sales_blocked_for(self.n1))

    def test_defaut_desactive(self):
        self.assertFalse(Node.objects.get(pk=self.n1.pk).block_sales_after_closure)

    def test_apres_heure_sans_validation_403(self):
        self.cfg(self.n1)
        r = self.sale(self.fa1, self.cl1)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['detail'], SALES_BLOCKED_DETAIL)
        self.assertTrue(SystemNotification.objects.filter(title__startswith='Ventes bloquées').exists())

    def test_avant_heure_pas_de_blocage(self):
        # BUG-1130 : journée en cours (heure de clôture pas encore atteinte) et clôture de la
        # journée terminée validée -> pas de blocage ; sans cette validation -> blocage.
        self.cfg(self.n1, hour=FUTURE)
        self.assertEqual(self.sale(self.fa1, self.cl1).status_code, 403)
        self.validate_closure(self.n1)
        self.assertEqual(self.sale(self.fa1, self.cl1).status_code, 201)

    def test_apres_validation_direction_201(self):
        self.cfg(self.n1)
        self.assertEqual(self.sale(self.fa1, self.cl1).status_code, 403)
        self.validate_closure(self.n1)
        self.assertEqual(self.sale(self.fa1, self.cl1).status_code, 201)

    def test_cloture_non_validee_ne_debloque_pas(self):
        self.cfg(self.n1)
        CashClosure.objects.create(node=self.n1, date=work_date_for(self.n1) - dt.timedelta(days=1),
                                   is_validated=False, node_origin='DB1')
        self.assertEqual(self.sale(self.fa1, self.cl1).status_code, 403)

    def test_jour_suivant_reblocage(self):
        self.cfg(self.n1)
        self.validate_closure(self.n1)
        demain = timezone.now() + dt.timedelta(days=1)
        self.assertTrue(sales_blocked_for(self.n1, demain))
        self.assertFalse(sales_blocked_for(self.n1))

    def test_instant_explicite_avant_apres_heure(self):
        self.cfg(self.n1, hour=dt.time(18, 0))
        d = timezone.localdate()

        def mk(h):
            return timezone.make_aware(dt.datetime.combine(d, dt.time(h, 0)))
        # BUG-1130 : à 17:00 on est encore dans la journée de la veille (clôture à 18:00) dont la
        # précédente (d-2) est validée ; à 18:00 la journée d-1 se termine : sa clôture est exigée.
        self.validate_closure(self.n1, d - dt.timedelta(days=2))
        self.assertFalse(sales_blocked_for(self.n1, mk(17)))
        self.assertTrue(sales_blocked_for(self.n1, mk(18)))

    def test_autre_boulangerie_non_touchee(self):
        self.cfg(self.n1)
        self.assertEqual(self.sale(self.fa2, self.cl2).status_code, 201)
        self.validate_closure(self.n2)
        self.assertEqual(self.sale(self.fa1, self.cl1).status_code, 403)

    def test_remboursement_et_livraison_non_bloques(self):
        self.cfg(self.n1, enabled=False)
        inv = self.sale(self.fa1, self.cl1).json()
        self.cfg(self.n1)
        r = self.sale(self.fa1, self.cl1, is_debt_repayment=True, lines=[], payment_amount=100)
        self.assertEqual(r.status_code, 201, r.content)
        r = api(self.lv1).post(f"{INV}{inv['id']}/deliver/", {}, format='json')
        self.assertNotEqual(r.status_code, 403, r.content)

    def test_vente_retroactive_non_bloquee(self):
        self.cfg(self.n1)
        hier = str(timezone.localdate() - dt.timedelta(days=1))
        r = self.sale(self.fa1, self.cl1, invoice_date=hier)
        self.assertNotEqual(r.json().get('detail'), SALES_BLOCKED_DETAIL)

    def test_siege_jamais_bloque(self):
        siege, _ = Node.objects.get_or_create(code='SIEGE', defaults={'name': 'Siege'})
        siege.block_sales_after_closure = True
        siege.save()
        self.assertFalse(sales_blocked_for(siege))
        self.assertFalse(sales_blocked_for(None))
        self.assertFalse(closure_status(None)['blocked'])

    # -- endpoint closure-status ----------------------------------------
    def test_status_contrat(self):
        self.cfg(self.n1, hour=dt.time(12, 0))
        r = api(self.fa1).get(STATUS)
        self.assertEqual(r.status_code, 200)
        d = r.json()
        for k in ('closure_hour', 'blocked', 'reason', 'closure_date', 'validated'):
            self.assertIn(k, d)
        self.assertEqual(d['closure_hour'], '12:00')
        # BUG-1130 : journée terminée à valider = jour de travail - 1.
        self.assertEqual(d['closure_date'], str(work_date_for(self.n1) - dt.timedelta(days=1)))

    def test_status_bloque_puis_valide(self):
        self.cfg(self.n1)
        d = api(self.fa1).get(STATUS).json()
        self.assertTrue(d['blocked'])
        self.assertFalse(d['validated'])
        self.validate_closure(self.n1)
        d = api(self.fa1).get(STATUS).json()
        self.assertFalse(d['blocked'])
        self.assertTrue(d['validated'])

    def test_status_permissions(self):
        self.cfg(self.n1)
        self.assertEqual(APIClient().get(STATUS).status_code, 401)
        self.assertEqual(api(self.fa2).get(STATUS + '?node=DB1').status_code, 403)
        self.assertFalse(api(self.fa2).get(STATUS).json()['blocked'])
        self.assertTrue(api(self.dirn).get(STATUS + '?node=DB1').json()['blocked'])
        self.assertEqual(api(self.dirn).get(STATUS + '?node=ZZZ').status_code, 404)
        self.assertFalse(api(self.dirn).get(STATUS).json()['blocked'])  # sans nœud
