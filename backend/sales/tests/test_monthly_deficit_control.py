"""
Vérification indépendante — contrôle complémentaire du déficit net du mois
(CLAUDE.md §5.2 : « Contrôle complémentaire existant : déficit net du mois
(commandé − versé − CM) ≥ plafond »), mentionné dans le cahier des charges
mais jusqu'ici jamais exercé par un test dédié : la suite historique
(`test_invoices.py::CreditBlockTests`) ne couvre que le plafond de dette
brute (`client.current_debt`), pas ce second contrôle distinct de
`sales/views.py` (variable `period_deficit`).

Rappel méthodologique (CLAUDE.md §7) : ce fichier n'écrit jamais sur le code
applicatif.

Le point clé isolé ici : le déficit net du mois (commandé − versé − commission
gagnée, calculé UNIQUEMENT sur les factures livrées du mois courant) peut
dépasser le plafond alors que la dette brute cumulative du client (jamais
remise à zéro, CLAUDE.md §5.2) reste largement sous ce même plafond — par
exemple quand le client est parti d'un solde créditeur important (BP très
négative) acquis un mois précédent. Les deux contrôles sont bien indépendants
et tous les deux actifs.
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import SystemNotification
from core.testing import make_node, make_user, make_bread_price, make_client
from sales.models import Invoice


def _api_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class MonthlyNetDeficitControlTests(TestCase):
    """CLAUDE.md §5.2 : déficit net du mois (commandé − versé − CM) ≥ plafond.

    Isolé de la dette brute en partant d'un client fortement créditeur
    (BP négative, acquise « le mois précédent » dans le scénario) : la dette
    brute reste sous le plafond pendant toute la série d'appels, seul le
    déficit net DE CE MOIS peut légitimement dépasser le plafond.
    """

    def setUp(self):
        self.node = make_node(code='K1')
        self.bp = make_bread_price('MOYEN', 'Pain 500 FC', 500)
        self.facturier = make_user('FACTURIER', node=self.node)
        self.api = _api_for(self.facturier)
        # BP fortement créditrice (-200 000 FC), simulant un gros versement
        # d'avance le mois précédent : la dette brute restera < 50 000 FC
        # pendant toute la série ci-dessous, uniquement le déficit NET DU
        # MOIS (qui ignore ce solde de départ) franchira le plafond.
        self.client_obj = make_client(
            self.node, credit_limit=Decimal('50000'), current_debt=Decimal('-200000'),
        )

    def _post(self, qty, payment, deliver=True):
        payload = {
            'client': str(self.client_obj.pk),
            'payment_type': 'CASH',
            'payment_amount': str(payment),
            'lines': [{'bread_price': self.bp.pk, 'quantity': qty}],
        }
        resp = self.api.post('/api/sales/invoices/', payload, format='json')
        # Le contrôle de déficit net du mois n'agrège que les factures
        # LIVRÉES (Invoice.Status.DELIVERED) — une facture encore PENDING
        # ne compte pas dans `period_agg`. On confirme systématiquement la
        # livraison ici pour exercer réellement ce contrôle.
        if deliver and resp.status_code == 201:
            deliver_resp = self.api.post(f"/api/sales/invoices/{resp.data['id']}/deliver/", {}, format='json')
            assert deliver_resp.status_code == 200, deliver_resp.data
        return resp

    def test_deficit_blocks_even_though_gross_debt_stays_under_ceiling(self):
        # Facture 1 : consomme la quasi-totalité du crédit d'avance.
        # qty=400 * 500 FC = 200 000 FC commandé, 0 versé.
        resp1 = self._post(qty=400, payment=0)
        self.assertEqual(resp1.status_code, 201, resp1.data)
        self.client_obj.refresh_from_db()
        # Dette brute après facture 1 : -200000 + 200000 = 0 (toujours < plafond).
        self.assertEqual(self.client_obj.current_debt, Decimal('0.00'))

        # Déficit net du mois à ce stade : commandé 200000 − versé 0 −
        # commission (0,25*200000=50000) = 150000 >= plafond 50000.
        # Facture 2 (petite, versement insuffisant) doit être bloquée par
        # CE contrôle, alors que la dette brute avant cette facture (0) est
        # très loin du plafond.
        before = SystemNotification.objects.filter(severity='DANGER').count()
        resp2 = self._post(qty=2, payment=0)  # commande 1000, versement 0 < 1000
        self.assertEqual(resp2.status_code, 403, resp2.data)
        self.assertIn('éficit', resp2.data['detail'])
        after = SystemNotification.objects.filter(severity='DANGER').count()
        self.assertEqual(after, before + 1)

        # Aucune facture 2 n'a été créée (refus propre, pas d'état fantôme).
        self.assertEqual(Invoice.objects.filter(client=self.client_obj).count(), 1)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.current_debt, Decimal('0.00'))

    def test_deficit_over_ceiling_still_accepted_when_payment_covers_the_order(self):
        resp1 = self._post(qty=400, payment=0)
        self.assertEqual(resp1.status_code, 201, resp1.data)

        # Déficit net du mois déjà >= plafond (comme ci-dessus), mais le
        # versement de la facture 2 couvre intégralement sa commande :
        # doit être accepté (même règle que le plafond de dette brute —
        # « payment >= order » neutralise le blocage).
        resp2 = self._post(qty=2, payment=1000)  # commande 1000, versement 1000
        self.assertEqual(resp2.status_code, 201, resp2.data)

    def test_no_deficit_block_when_period_deficit_still_negative(self):
        """Non-régression : un client qui paie plus qu'il ne commande ce
        mois (déficit négatif) n'est jamais bloqué par ce contrôle, même
        avec un solde de départ très créditeur."""
        resp1 = self._post(qty=10, payment=10000)  # commande 5000, versement 10000 -> déficit négatif
        self.assertEqual(resp1.status_code, 201, resp1.data)
        resp2 = self._post(qty=2, payment=0)  # commande 1000, versement 0
        self.assertEqual(resp2.status_code, 201, resp2.data)
