"""
Ronde b19 (testeur clients/commissions, 2026-11-23) : verification independante de BUG-1008 (inactifs sur toutes
les pages d'un pull a curseur, tolerance 1 h du curseur de page). Donnees FICTIVES. Code applicatif non modifie.
"""
from datetime import timedelta
from unittest import expectedFailure

from django.utils import timezone

from clients.models import Client
from clients.tests.test_clients_v12 import cloud_rows
from clients.tests.test_clients_v14 import Base14
from sync.management.commands.sync_now import apply_pull_response


class Curseur1h(Base14):
    PAGE = 2

    def test_inactif_autre_noeud_livre_sur_pull_incremental_toutes_pages(self):
        a = self.mk(self.k3, 'A', 'Un')
        b = self.mk(self.k3, 'B', 'Deux')
        c = self.mk(self.k3, 'C', 'Trois')
        first = self.get(self.k1)
        for x in (a, b, c):
            self.patch_active(x, False)
        pages, seen = self.walk(self.k1, first={'since_client_debt': first['since_client_debt']})
        self.assertGreaterEqual(len(pages), 2)
        self.assertEqual({str(a.id), str(b.id), str(c.id)}, set(seen))
        self.assertEqual(len(seen), len(set(seen)))

    def test_pull_initial_page_1_sans_inactif_et_page_2_peut_en_livrer_un(self):
        ids = self.mk_many(3, node=self.k3)
        dead = self.mk(self.k3, 'Mort', 'Inactif')
        Client.objects.filter(pk=dead.pk).update(is_active=False, updated_at=timezone.now() - timedelta(minutes=1))
        p1 = self.get(self.k1)
        self.assertNotIn(str(dead.id), [x['id'] for x in p1['clients']])
        self.assertTrue(p1['has_more'])
        pages, seen = self.walk(self.k1)
        # Effet de bord documente : l'inactif peut apparaitre en page 2+ ; le poste neuf l'ignore.
        row = {'id': str(dead.id), **cloud_rows('K3', 1)[0], 'is_active': False}
        row['id'] = str(dead.id)
        Client.objects.filter(pk=dead.pk).delete()
        apply_pull_response({'clients': [row], 'node_code': 'K1'})
        self.assertFalse(Client.objects.filter(pk=dead.pk).exists())

    def test_curseur_futur_30min_avec_after_id_accepte_sans_400(self):
        c = self.mk(self.k3, 'F', 'Utur')
        fut = timezone.now() + timedelta(minutes=30)
        Client.objects.filter(pk=c.pk).update(updated_at=fut)
        r = self.get(self.k1, since_client_debt=fut.isoformat(), client_after_id='00000000-0000-0000-0000-000000000000')
        self.assertEqual([x['id'] for x in r['clients']], [str(c.id)])

    def test_curseur_futur_30min_avec_after_id_ne_saute_que_ce_qui_precede(self):
        """Curseur forge (futur 30 min + after_id) : renvoie seulement les lignes strictement apres lui, soit
        rien (aucune ligne n'est plus recente). Equivalent a since=maintenant : aucune donnee d'un autre perimetre."""
        self.mk_many(3, node=self.k3)
        r = self.get(self.k1, since_client_debt=(timezone.now() + timedelta(minutes=30)).isoformat(),
                     client_after_id='ffffffff-ffff-ffff-ffff-ffffffffffff')
        self.assertEqual(r['clients'], [])
        self.assertFalse(r['has_more'])

    def test_curseur_futur_sans_after_id_traite_comme_absent_bug785(self):
        self.mk_many(3, node=self.k3)
        r = self.get(self.k1, since_client_debt=(timezone.now() + timedelta(minutes=30)).isoformat())
        self.assertEqual(len(r['clients']), 2)  # pull complet, page 1
        self.assertTrue(r['has_more'])

    def test_curseur_futur_plus_de_1h_avec_after_id_traite_comme_absent(self):
        self.mk_many(3, node=self.k3)
        r = self.get(self.k1, since_client_debt=(timezone.now() + timedelta(hours=2)).isoformat(),
                     client_after_id='ffffffff-ffff-ffff-ffff-ffffffffffff')
        self.assertEqual(len(r['clients']), 2)

    def test_curseur_juste_sous_et_juste_au_dessus_de_1h(self):
        self.mk_many(3, node=self.k3)
        ok = self.get(self.k1, since_client_debt=(timezone.now() + timedelta(minutes=59)).isoformat(),
                      client_after_id='ffffffff-ffff-ffff-ffff-ffffffffffff')
        self.assertEqual(ok['clients'], [])
        ko = self.get(self.k1, since_client_debt=(timezone.now() + timedelta(minutes=61)).isoformat(),
                      client_after_id='ffffffff-ffff-ffff-ffff-ffffffffffff')
        self.assertEqual(len(ko['clients']), 2)

    def test_after_id_invalide_avec_curseur_futur_400(self):
        r = self.get(self.k1, since_client_debt=(timezone.now() + timedelta(minutes=5)).isoformat(),
                     client_after_id='pas-un-uuid')
        self.assertIn('detail', r)

    def test_marche_avec_lignes_datees_futur_30min_sans_perte_ni_boucle(self):
        ids = self.mk_many(5, node=self.k3)
        Client.objects.update(updated_at=timezone.now() + timedelta(minutes=30))
        pages, seen = self.walk(self.k1)
        self.assertEqual(set(ids) & set(seen), set(ids))
        self.assertEqual(len(seen), len(set(seen)))

    @expectedFailure  # BUG-1010
    def test_marche_avec_lignes_datees_futur_3h_ne_boucle_pas(self):
        """Horloge Cloud derivee de 3 h : le curseur de page est rejete (> 1 h) -> retour page 1 ?"""
        self.mk_many(5, node=self.k3)
        Client.objects.update(updated_at=timezone.now() + timedelta(hours=3))
        pages, seen = self.walk(self.k1, limit=12)
        self.assertEqual(len(seen), len(set(seen)), 'pagination en boucle : memes clients re-livres')
