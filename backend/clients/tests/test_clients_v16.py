"""
Ronde b20 (testeur clients/commissions, 2026-11-23) : verification independante de BUG-1010 (curseur de page
plafonne au plus grand updated_at reel ; BUG-785 conserve). Donnees FICTIVES. Code applicatif non modifie.
"""
from datetime import timedelta

from django.utils import timezone

from clients.models import Client
from clients.tests.test_clients_v14 import Base14


class Futur(Base14):
    PAGE = 2

    def future(self, hours, ids=None):
        qs = Client.objects.all() if ids is None else Client.objects.filter(pk__in=ids)
        qs.update(updated_at=timezone.now() + timedelta(hours=hours))

    def test_3h_cinq_clients_sans_perte_ni_doublon_et_borne(self):
        ids = self.mk_many(5, node=self.k3)
        self.future(3)
        pages, seen = self.walk(self.k1, limit=12)
        self.assertEqual(set(ids), set(seen))
        self.assertEqual(len(seen), len(set(seen)))
        self.assertLessEqual(len(pages), 4)

    def test_3h_ex_aequo_a_cheval_sur_une_frontiere_de_page(self):
        ids = self.mk_many(7, node=self.k3)
        self.future(3)
        pages, seen = self.walk(self.k1, limit=12)
        self.assertEqual(sorted(ids), sorted(seen))

    def test_melange_passe_et_futurs_3h_et_30min(self):
        ids = self.mk_many(9, node=self.k3)
        objs = list(Client.objects.filter(pk__in=ids).order_by('pk'))
        self.future(3, [o.pk for o in objs[:3]])
        self.future(0.5, [o.pk for o in objs[3:6]])
        pages, seen = self.walk(self.k1, limit=15)
        self.assertEqual(sorted(ids), sorted(seen))

    def test_incremental_avec_lignes_futures_3h(self):
        self.mk_many(5, node=self.k3)
        self.future(3)
        pages, seen = self.walk(self.k1, limit=12)
        cursor = pages[-1]['since_client_debt']
        again, seen2 = self.walk(self.k1, first={'since_client_debt': cursor}, limit=12)
        # Comportement documente (option (b) de BUG-1010 ecartee) : le curseur final est `now`, donc les lignes
        # datees dans le futur sont relivrees a chaque cycle jusqu'a ce que l'horloge les rattrape. Idempotent
        # et borne (aucun doublon dans une marche, aucune perte).
        self.assertEqual(sorted(seen2), sorted(seen))
        self.assertEqual(len(seen2), len(set(seen2)))

    def test_curseur_force_au_dela_du_plafond_traite_comme_absent_bug785(self):
        self.mk_many(3, node=self.k3)
        self.future(3)
        top = Client.objects.order_by('-updated_at').first().updated_at
        r = self.get(self.k1, since_client_debt=(top + timedelta(seconds=5)).isoformat(),
                     client_after_id='ffffffff-ffff-ffff-ffff-ffffffffffff')
        self.assertEqual(len(r['clients']), 2)  # page 1 : curseur ignore

    def test_curseur_force_sans_after_id_dans_le_futur_absent(self):
        self.mk_many(3, node=self.k3)
        self.future(3)
        r = self.get(self.k1, since_client_debt=(timezone.now() + timedelta(hours=2)).isoformat())
        self.assertEqual(len(r['clients']), 2)

    def test_curseur_force_sous_le_plafond_ne_fuit_pas_hors_perimetre(self):
        self.mk_many(4, node=self.k3)
        self.future(3)
        full = set(self.walk(self.k1, limit=12)[1])
        r = self.get(self.k1, since_client_debt=(timezone.now() + timedelta(hours=2)).isoformat(),
                     client_after_id='00000000-0000-0000-0000-000000000000')
        self.assertLessEqual({x['id'] for x in r['clients']}, full)

    def test_plafond_qui_baisse_entre_deux_pages_termine_sans_boucle(self):
        ids = self.mk_many(6, node=self.k3)
        self.future(3)

        def between(i, data):
            if i == 0:  # horloge corrigee : toutes les lignes ramenees a maintenant
                Client.objects.update(updated_at=timezone.now())
        pages, seen = self.walk(self.k1, limit=15, between=between)
        self.assertTrue(set(ids) <= set(seen))

    def test_perimetre_inter_boulangeries_conserve_avec_plafond(self):
        mine = self.mk_many(3, node=self.k1)
        other = self.mk_many(3, node=self.k3)
        self.future(3)
        pages, seen = self.walk(self.k1, limit=12)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertTrue(set(mine + other) <= set(seen))
