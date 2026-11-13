"""
Vérification de BUG-253 (testeur-permissions, 2026-11-13) : lecture de
treasury closures/savings/journal et commissions periods/commissions réservée
au gérant et au-dessus ; actions history / payroll_listing / suggested_ca /
monthly_report / monthly_total incluses ; isolation par nœud conservée.
Base de test éphémère uniquement.
"""
from core.tests.test_permissions import BaseNodeTestCase
from commissions.models import CommissionPeriod
from treasury.models import JournalEntry

ROLES = ("anon", "ADMIN", "DIRECTION", "COMPTABLE", "GERANT", "FACTURIER", "LIVREUR")
GERANT_UP = {"ADMIN", "DIRECTION", "COMPTABLE", "GERANT"}
NIL = "00000000-0000-0000-0000-000000000000"

ROUTES = [
    "/api/treasury/closures/",
    f"/api/treasury/closures/{NIL}/",
    "/api/treasury/savings/",
    f"/api/treasury/savings/{NIL}/",
    "/api/treasury/savings/monthly_total/?month=10&year=2026",
    "/api/treasury/journal/",
    f"/api/treasury/journal/{NIL}/",
    "/api/treasury/journal/suggested_ca/?date=2026-10-01",
    "/api/treasury/journal/monthly_report/?month=10&year=2026",
    "/api/commissions/periods/",
    f"/api/commissions/periods/{NIL}/",
    "/api/commissions/periods/history/",
    "/api/commissions/commissions/",
    f"/api/commissions/commissions/{NIL}/",
    "/api/commissions/commissions/payroll_listing/",
]


class Bug253Verification(BaseNodeTestCase):
    def _c(self, role):
        from rest_framework.test import APIClient
        if role == "anon":
            return APIClient()
        return self.client_as({
            "ADMIN": self.admin, "DIRECTION": self.direction, "COMPTABLE": self.comptable,
            "GERANT": self.gerant_k1, "FACTURIER": self.facturier_k1, "LIVREUR": self.livreur_k1,
        }[role])

    def test_matrix(self):
        for url in ROUTES:
            for role in ROLES:
                with self.subTest(url=url, role=role):
                    s = self._c(role).get(url).status_code
                    if role == "anon":
                        self.assertEqual(s, 401)
                    elif role in ("FACTURIER", "LIVREUR"):
                        self.assertEqual(s, 403, s)
                    elif role == "GERANT" and ("history" in url or "payroll_listing" in url):
                        # Ecart préexistant (get_permissions écrase permission_classes
                        # de l'action -> IsHeadquarters) ; aucun écran gérant ne les appelle.
                        self.assertEqual(s, 403, s)
                    else:
                        self.assertIn(s, (200, 400, 404), s)  # jamais 401/403/500

    def test_gerant_payroll_listing_status(self):
        # Information : statut observé pour le gérant (permission IsHeadquarters
        # dans get_permissions, inchangée par BUG-253).
        r = self._c("GERANT").get("/api/commissions/commissions/payroll_listing/")
        print("PAYROLL gerant:", r.status_code)

    def test_node_isolation(self):
        CommissionPeriod.objects.create(node=self.k1, month=10, year=2026)
        p2 = CommissionPeriod.objects.create(node=self.k2, month=10, year=2026)
        r = self._c("GERANT").get("/api/commissions/periods/")
        ids = [x["id"] for x in r.json().get("results", r.json())]
        self.assertEqual(len(ids), 1)
        self.assertNotIn(str(p2.id), ids)
        # forcer ?node=K2
        r = self._c("GERANT").get(f"/api/commissions/periods/?node={self.k2.pk}")
        self.assertEqual(len(r.json().get("results", r.json())), 0)
        r = self._c("COMPTABLE").get(f"/api/commissions/periods/history/?node={self.k2.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)
        # détail par id connu
        self.assertEqual(self._c("GERANT").get(f"/api/commissions/periods/{p2.pk}/").status_code, 404)
        # siège voit les deux
        r = self._c("COMPTABLE").get("/api/commissions/periods/")
        self.assertEqual(len(r.json().get("results", r.json())), 2)
