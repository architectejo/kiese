"""Clients - ronde v3 (testeur Clients/Commissions, 2026-11-22-b3).

Verification independante de BUG-739 a 741, 743, 746 et attaque des correctifs :
fonction SQL KIESE_FOLD, import Excel (NFC/NFD, 100 caracteres pile, rapport),
bulk_move (atomicite, cles du rapport), lignes de distribution (depassements
de colonnes). Donnees FICTIVES uniquement.
"""
import unicodedata
import uuid
from decimal import Decimal as D
from unittest import expectedFailure, mock

from django.db import connection
from django.test import TestCase

from clients.models import Client, SocialContribution, SocialDistributionLine
from clients.search import fold
from clients.tests.test_clients_v2 import (
    CL, CONTRIB, DISTRIB, LINES, Base, api, make_xlsx, results, upload,
)


class FoldSqlTests(Base):
    def test_fonction_python_fold_cas_limites(self):
        self.assertIsNone(fold(None))
        self.assertEqual(fold('ÉLODIE'), 'elodie')
        self.assertEqual(fold(unicodedata.normalize('NFD', 'Élodie')), 'elodie')
        self.assertEqual(fold(''), '')
        self.assertEqual(fold(123), '123')

    def test_fonction_sql_enregistree_et_null_safe(self):
        with connection.cursor() as cur:
            cur.execute("SELECT KIESE_FOLD(%s), KIESE_FOLD(NULL), KIESE_FOLD(%s)", ['ÉCOLE', "x'; DROP TABLE clients_client;--"])
            row = cur.fetchone()
        self.assertEqual(row[0], 'ecole')
        self.assertIsNone(row[1])
        self.assertEqual(row[2], "x'; drop table clients_client;--")
        self.assertTrue(Client.objects.count() >= 0)  # la table existe toujours

    def test_like_jokers_echappes_pas_de_faux_positifs(self):
        a = self.mk(self.k1, 'Paul', 'Mbala')
        b = self.mk(self.k1, 'Jean_Paul', 'Kasa')
        c = self.mk(self.k1, '100%', 'Pur')
        for term, expected in (('%', {str(c.id)}), ('_', {str(b.id)}), ('a_b', set()), ('\\', set())):
            with self.subTest(term=term):
                r = api(self.f1).get(CL, {'search': term})
                self.assertEqual(r.status_code, 200, term)
                self.assertEqual({x['id'] for x in results(r)}, expected, term)
        self.assertIsNotNone(a)

    def test_caracteres_exotiques_jamais_500(self):
        self.mk(self.k1, 'İstanbul', 'Straße')
        self.mk(self.k1, 'Zoë', 'Ñungu')
        for term in ('ß', 'strasse', 'STRASSE', 'ñ', 'ñ', '​', '\U0001F600', 'ﬁ', 'Σ', 'ς', '�',
                     'à́̂', 'x' * 5000):
            with self.subTest(term=repr(term)[:20]):
                r = api(self.f1).get(CL, {'search': term})
                self.assertIn(r.status_code, (200, 400))

    def test_equivalences_attendues(self):
        c = self.mk(self.k1, 'Zoë', 'Ñungu')
        s = self.mk(self.k1, 'Hans', 'Straße')
        for term, target in (('zoe', c), ('ÑUNGU', c), ('nungu', c), ('ñungu', c), ('strasse', s), ('STRAßE', s)):
            with self.subTest(term=term):
                r = api(self.f1).get(CL, {'search': term})
                self.assertIn(str(target.id), [x['id'] for x in results(r)])

    def test_recherche_par_code_et_telephone_et_valeur_null(self):
        c = self.mk(self.k3, 'Alain', 'Zola')
        Client.objects.filter(pk=c.pk).update(phone='0991112223')
        d = self.mk(self.k3, 'Sans', 'Telephone')
        for term in (c.code.lower(), c.code.upper(), '0991112', '99111'):
            self.assertIn(str(c.id), [x['id'] for x in results(api(self.f1).get(CL, {'search': term}))], term)
        r = api(self.f1).get(CL, {'search': 'sans telephone'})
        self.assertEqual([x['id'] for x in results(r)], [str(d.id)])

    def test_multi_termes_et_ordre_pertinence_avec_accents(self):
        a = self.mk(self.k1, 'Éric', 'Makiese')
        b = self.mk(self.k1, 'Éric', 'Kiese')
        ids = [x['id'] for x in results(api(self.f1).get(CL, {'search': 'KIÈSE'}))]
        self.assertEqual(ids, [str(b.id), str(a.id)])
        ids = [x['id'] for x in results(api(self.f1).get(CL, {'search': 'eric kiese'}))]
        self.assertIn(str(b.id), ids)

    def test_recherche_combinee_a_filtre_node_et_ordering_explicite(self):
        a = self.mk(self.k1, 'Élodie', 'Zeta')
        b = self.mk(self.k3, 'Élodie', 'Alpha')
        r = api(self.direction).get(CL, {'search': 'elodie', 'node': self.k3.pk})
        self.assertEqual([x['id'] for x in results(r)], [str(b.id)])
        r = api(self.direction).get(CL, {'search': 'elodie', 'ordering': '-last_name'})
        self.assertEqual([x['id'] for x in results(r)], [str(a.id), str(b.id)])

    def test_gerant_reste_isole_avec_recherche_repliee(self):
        self.mk(self.k3, 'Élodie', 'Autre')
        r = api(self.g1).get(CL, {'search': 'elodie'})
        self.assertEqual(results(r), [])


class ImportV3Tests(Base):
    def test_100_caracteres_pile_accepte_101_refuse(self):
        ok = 'A' * 100 + ' ' + 'B' * 100
        ko_first = 'A' * 101 + ' Dupont'
        ko_last = 'Jean ' + 'B' * 101
        r = upload(self.direction, make_xlsx({'CL-K1': [ok, ko_first, ko_last]}))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['created'], 1)
        rep = r.data['report'][0]
        self.assertEqual((rep['total_in_file'], rep['to_import'], rep['already_existing'], rep['invalid']), (3, 1, 0, 2))
        self.assertEqual(len(rep['invalid_names']), 2)
        c = Client.objects.get(node=self.k1)
        self.assertEqual((len(c.first_name), len(c.last_name)), (100, 100))

    def test_nom_unique_de_100_et_101_caracteres(self):
        r = upload(self.direction, make_xlsx({'CL-K1': ['C' * 100, 'D' * 101]}))
        self.assertEqual((r.data['created'], r.data['report'][0]['invalid']), (1, 1))

    def test_nom_nfd_court_apres_nfc_est_accepte_et_stocke_nfc(self):
        # 100 'é' en NFD = 200 points de code, 100 en NFC : accepte.
        nfd = unicodedata.normalize('NFD', 'é' * 100)
        r = upload(self.direction, make_xlsx({'CL-K1': [nfd]}))
        self.assertEqual(r.data['created'], 1, r.data)
        c = Client.objects.get(node=self.k1)
        self.assertEqual(c.first_name, unicodedata.normalize('NFC', c.first_name))
        self.assertEqual(len(c.first_name), 100)

    def test_doublon_nfd_contre_client_deja_en_base_nfd(self):
        """Client historique stocke en NFD : l'import NFC doit le reconnaitre."""
        nfd = unicodedata.normalize('NFD', 'Élodie')
        Client.objects.create(node=self.k1, node_origin='K1', first_name=nfd, last_name='Mukendi')
        r = upload(self.direction, make_xlsx({'CL-K1': ['Élodie Mukendi']}))
        self.assertEqual((r.data['created'], r.data['report'][0]['already_existing']), (0, 1))

    def test_doublon_dans_le_meme_fichier_nfc_nfd_et_casse(self):
        names = [unicodedata.normalize('NFC', 'Éric Kasa'), unicodedata.normalize('NFD', 'éRIC KASA')]
        r = upload(self.direction, make_xlsx({'CL-K1': names}))
        self.assertEqual((r.data['created'], r.data['report'][0]['already_existing']), (1, 1))

    def test_dry_run_rapport_identique_au_reel(self):
        names = ['A' * 101 + ' X', 'Jean Mbala', 'Jean Mbala', 'Paul Nzuzi']
        dry = upload(self.direction, make_xlsx({'CL-K1': names}), dry_run='true')
        self.assertEqual(Client.objects.count(), 0)
        real = upload(self.direction, make_xlsx({'CL-K1': names}))
        self.assertEqual(dry.data['report'], real.data['report'])
        self.assertEqual(real.data['created'], 2)
        self.assertEqual(real.data['report'][0]['to_import'], 2)

    def test_invalid_names_limite_a_20_et_tronque_a_60(self):
        names = [f'{"Z" * 120}{i} Dupont' for i in range(30)]
        r = upload(self.direction, make_xlsx({'CL-K1': names}))
        rep = r.data['report'][0]
        self.assertEqual(rep['invalid'], 30)
        self.assertEqual(len(rep['invalid_names']), 20)
        self.assertTrue(all(len(n) <= 60 for n in rep['invalid_names']))
        self.assertEqual(r.data['created'], 0)

    def test_espaces_insecables_et_tabulations(self):
        r = upload(self.direction, make_xlsx({'CL-K1': ['Jean Mbala', 'Jean\tMbala', ' Jean   Mbala ']}))
        self.assertEqual(r.data['created'], 1)

    def test_import_ne_cree_pas_de_client_pour_noeud_inconnu_et_cles_du_rapport(self):
        r = upload(self.direction, make_xlsx({'CL-K1': ['A B'], 'CL-K7': ['C D']}))
        self.assertEqual(set(r.data), {'dry_run', 'created', 'report', 'skipped_sheets', 'unknown_nodes'})
        self.assertEqual(set(r.data['report'][0]),
                         {'node', 'node_name', 'total_in_file', 'to_import', 'already_existing', 'invalid', 'invalid_names'})
        self.assertEqual(r.data['unknown_nodes'], ['K7'])

    def test_total_invariant_total_egal_somme_des_categories(self):
        self.mk(self.k1, 'Deja', 'La')
        names = ['Deja La', 'Nouveau Un', 'Nouveau Un', 'X' * 120 + ' Y', 'Autre Deux']
        rep = upload(self.direction, make_xlsx({'CL-K1': names})).data['report'][0]
        self.assertEqual(rep['total_in_file'], rep['to_import'] + rep['already_existing'] + rep['invalid'])


class BulkMoveV3Tests(Base):
    def test_cles_de_reponse_et_node_introuvable_sous_detail(self):
        r = api(self.direction).post(CL + 'bulk_move/', {'ids': [str(uuid.uuid4())], 'node': 999999}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('detail', r.data)
        self.assertNotIn('node', r.data)
        c = self.mk(self.k1, 'A', 'B')
        r = api(self.direction).post(CL + 'bulk_move/', {'ids': [str(c.id)], 'node': self.k3.pk}, format='json')
        self.assertEqual(set(r.data), {'moved', 'requested'})
        self.assertEqual((r.data['moved'], r.data['requested']), (1, 1))

    def test_ids_formes_invalides(self):
        c = self.mk(self.k1, 'A', 'B')
        for ids in ('abc', str(c.id), {'a': 1}, [1, 2], [None], ['x'], [[str(c.id)]], 12, True):
            with self.subTest(ids=ids):
                r = api(self.direction).post(CL + 'bulk_move/', {'ids': ids, 'node': self.k3.pk}, format='json')
                self.assertEqual(r.status_code, 400, (ids, r.status_code))
        c.refresh_from_db()
        self.assertEqual(c.node_id, self.k1.id)

    def test_node_formes_invalides(self):
        c = self.mk(self.k1, 'A', 'B')
        for node in ('abc', -1, 0, 10 ** 30, [1], {'a': 1}, 1.5, '1; DROP'):
            with self.subTest(node=node):
                r = api(self.direction).post(CL + 'bulk_move/', {'ids': [str(c.id)], 'node': node}, format='json')
                self.assertEqual(r.status_code, 400, (node, r.status_code))

    def test_lot_atomique_en_cas_d_erreur_au_milieu(self):
        cs = [self.mk(self.k1, f'P{i}', 'Q') for i in range(3)]
        calls = {'n': 0}
        real = __import__('clients.models', fromlist=['x'])._generate_client_code

        def flaky(code):
            calls['n'] += 1
            if calls['n'] == 2:
                raise RuntimeError('boom')
            return real(code)

        with mock.patch('clients.views._generate_client_code', side_effect=flaky):
            r = api(self.direction).post(CL + 'bulk_move/', {'ids': [str(c.id) for c in cs], 'node': self.k3.pk}, format='json')
        self.assertEqual(r.status_code, 500)
        self.assertEqual(Client.objects.filter(node=self.k1).count(), 3)
        self.assertEqual(Client.objects.filter(node=self.k3).count(), 0)

    def test_ids_en_double_et_inconnus_et_deja_dans_le_noeud(self):
        a = self.mk(self.k1, 'A', 'A')
        b = self.mk(self.k3, 'B', 'B')
        r = api(self.direction).post(CL + 'bulk_move/', {
            'ids': [str(a.id), str(a.id), str(b.id), str(uuid.uuid4())], 'node': self.k3.pk}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['moved'], 1)
        a.refresh_from_db()
        self.assertTrue(a.code.startswith('K3-'))
        self.assertEqual(a.node_origin, 'K3')

    def test_ids_au_format_uuid_sans_tirets_et_majuscules(self):
        a = self.mk(self.k1, 'A', 'A')
        r = api(self.direction).post(CL + 'bulk_move/', {'ids': [a.id.hex.upper()], 'node': self.k3.pk}, format='json')
        self.assertEqual((r.status_code, r.data['moved']), (200, 1))

    def test_bulk_delete_memes_garde_fous(self):
        for ids in ('abc', [1], {'a': 1}, ['zz']):
            self.assertEqual(api(self.direction).post(CL + 'bulk_delete/', {'ids': ids}, format='json').status_code, 400, ids)


class CaisseV3Tests(Base):
    def setUp(self):
        super().setUp()
        self.k1.monthly_social_contribution = D('2000')
        self.k1.save()
        self.c1 = self.mk(self.k1, 'A', 'A')

    def bulk(self, user, **payload):
        return api(user).post(CONTRIB + 'bulk_create_month/', payload, format='json')

    def test_bornes_exactes_mois_annee_montant(self):
        for month, year in ((1, 2000), (12, 2100)):
            r = self.bulk(self.direction, node=self.k1.pk, month=month, year=year)
            self.assertEqual(r.status_code, 200, (month, year, r.data))
        for payload in ({'month': 12, 'year': 2101}, {'month': 12, 'year': 1999}, {'month': 1.0, 'year': 2026},
                        {'month': True, 'year': 2026}, {'month': [3], 'year': 2026}):
            r = self.bulk(self.direction, node=self.k1.pk, **payload)
            self.assertEqual(r.status_code, 400, payload)

    def test_montant_limites(self):
        r = self.bulk(self.direction, node=self.k1.pk, month=5, year=2026, amount='99999999.99')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SocialContribution.objects.get().amount, D('99999999.99'))
        SocialContribution.objects.all().delete()
        for amount in ('100000000', 'NaN', 'Infinity', '-0.01', [1], {'a': 1}, True, '1e9'):
            r = self.bulk(self.direction, node=self.k1.pk, month=5, year=2026, amount=amount)
            self.assertEqual(r.status_code, 400, amount)
        self.assertEqual(SocialContribution.objects.count(), 0)

    def test_montant_exposant_gigantesque_400(self):
        r = self.bulk(self.direction, node=self.k1.pk, month=5, year=2026, amount='1E999999999')
        self.assertEqual(r.status_code, 400, r.status_code)

    @expectedFailure  # BUG-748
    def test_montant_zero_explicite_est_ignore_silencieusement(self):
        """amount='0' (cotisation nulle demandee) : l'API applique le tarif de la boulangerie."""
        r = self.bulk(self.direction, node=self.k1.pk, month=6, year=2026, amount='0')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(SocialContribution.objects.get().amount, D('0.00'))

    def test_arrondi_du_montant_manuel(self):
        r = self.bulk(self.direction, node=self.k1.pk, month=7, year=2026, amount='1500.555')
        self.assertEqual(r.status_code, 200)
        self.assertIn(SocialContribution.objects.get().amount, (D('1500.56'), D('1500.55')))

    def test_ligne_distribution_bornes(self):
        d = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2026, 'tarif': '700'}, format='json').data
        for good in ({'indice': 0}, {'indice': 12}, {'merite': '0'}, {'total_social': '0'}):
            SocialDistributionLine.objects.all().delete()
            r = api(self.g1).post(LINES, dict({'distribution': d['id'], 'client': str(self.c1.id)}, **good), format='json')
            self.assertEqual(r.status_code, 201, (good, r.data))
        for bad in ({'indice': 13}, {'indice': '12.5'}, {'indice': 'abc'}, {'merite': 'NaN'}, {'total_social': 'Infinity'}):
            SocialDistributionLine.objects.all().delete()
            r = api(self.g1).post(LINES, dict({'distribution': d['id'], 'client': str(self.c1.id)}, **bad), format='json')
            self.assertEqual(r.status_code, 400, (bad, r.status_code))

    def test_ligne_total_payer_ne_depasse_pas_la_colonne(self):
        """total_social et merite valides (< 10^8 chacun) mais leur somme + remise depasse
        max_digits=10 : doit etre un 400, jamais un 500."""
        d = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2026, 'tarif': '700'}, format='json').data
        r = api(self.g1).post(LINES, {'distribution': d['id'], 'client': str(self.c1.id),
                                      'total_social': '99999999.99', 'merite': '99999999.99'}, format='json')
        self.assertLess(r.status_code, 500, r.status_code)

    def test_ligne_remise_depasse_la_colonne_avec_gros_tarif(self):
        d = api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': 2026, 'tarif': '99999999.99'}, format='json')
        self.assertEqual(d.status_code, 201, d.data)
        r = api(self.g1).post(LINES, {'distribution': d.data['id'], 'client': str(self.c1.id), 'indice': 12}, format='json')
        self.assertLess(r.status_code, 500, r.status_code)
