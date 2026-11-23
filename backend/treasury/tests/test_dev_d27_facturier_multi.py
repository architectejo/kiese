"""d27 (dev-backend) : non-regression du push FacturierReport apres BUG-911.
REST autorise deux facturiers distincts sur la meme vacation (boulangerie, equipe, date) ;
le push ne rejette le doublon que pour le meme facturier (ou indetermine des deux cotes).
Donnees fictives."""
from core.testing import make_user
from treasury.models import FacturierReport
from treasury.tests.test_verif_tresorerie_c9_v8 import PushBase
from treasury.tests.test_cycle1_tresorerie_c import today


class PushFacturiersDistincts(PushBase):
    def _count(self):
        return FacturierReport.objects.filter(node=self.n1, team='A', date=today()).count()

    def test_deux_facturiers_distincts_meme_vacation_acceptes(self):
        f1 = make_user('FACTURIER', self.n1, 'A')
        f2 = make_user('FACTURIER', self.n1, 'A')
        self.push(self.raw1, 'treasury.FacturierReport', self.rep(facturier=str(f1.pk)))
        self.push(self.raw1, 'treasury.FacturierReport', self.rep(facturier=str(f2.pk)))
        self.assertEqual(self._count(), 2)

    def test_meme_facturier_deux_fois_rejete(self):
        f1 = make_user('FACTURIER', self.n1, 'A')
        self.push(self.raw1, 'treasury.FacturierReport', self.rep(facturier=str(f1.pk)))
        self.push(self.raw1, 'treasury.FacturierReport', self.rep(facturier=str(f1.pk)))
        self.assertEqual(self._count(), 1)
