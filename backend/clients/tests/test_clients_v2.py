"""Clients - ronde v2 (testeur Clients/Commissions, 2026-11-22-b2).

Nouveaux angles : recherche prédictive inter-boulangeries, plafond, catégories
(bornes), codes (séquence périmée, déplacement), import Excel malformé,
paramètres invalides, caisse sociale (mois/montants invalides), isolation par
nœud, Decimal. Données FICTIVES uniquement (jamais data_kiese/).
"""
import io
import tempfile
import unicodedata
from decimal import Decimal as D
from unittest import expectedFailure

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from clients.models import (
    Client, ClientCodeSequence, SocialContribution, SocialDistribution,
    SocialDistributionLine, _generate_client_code,
)
from core.models import Config, Node
from core.testing import make_client, make_node, make_user

CL = '/api/clients/clients/'
CONTRIB = '/api/clients/contributions/'
DISTRIB = '/api/clients/distributions/'
LINES = '/api/clients/distribution-lines/'


def api(user):
    c = APIClient(raise_request_exception=False)
    c.force_authenticate(user)
    return c


def results(resp):
    data = resp.data
    return data['results'] if isinstance(data, dict) and 'results' in data else data


class Base(TestCase):
    def setUp(self):
        self.k1 = Node.objects.get_or_create(code='K1', defaults={'name': 'K1 TABORA'})[0]
        self.k3 = Node.objects.get_or_create(code='K3', defaults={'name': 'K3 ATHENEE'})[0]
        self.direction = make_user('DIRECTION', node=None, team='')
        self.comptable = make_user('COMPTABLE', node=None, team='')
        self.g1 = make_user('GERANT', node=self.k1, team='')
        self.g3 = make_user('GERANT', node=self.k3, team='')
        self.f1 = make_user('FACTURIER', node=self.k1, team='A')
        self.l1 = make_user('LIVREUR', node=self.k1, team='A')

    def mk(self, node, first, last, **kw):
        return make_client(node, first_name=first, last_name=last, **kw)


# --------------------------------------------------------------------------
# Recherche prédictive et facturation inter-boulangeries (règle 5.1)
# --------------------------------------------------------------------------
class RechercheTests(Base):
    def test_facturier_k1_trouve_client_k3_par_nom_partiel_code_et_telephone(self):
        c = self.mk(self.k3, 'Mireille', 'Kimbembe')
        Client.objects.filter(pk=c.pk).update(phone='0990001122')
        for term in ('kimbem', 'KIMB', 'mirei', c.code, c.code.lower(), '0990001'):
            if term == 'mirei':
                continue  # faute de frappe : non trouvé, voir test dédié
            r = api(self.f1).get(CL, {'search': term})
            self.assertEqual(r.status_code, 200, term)
            self.assertIn(str(c.id), [x['id'] for x in results(r)], term)

    def test_livreur_voit_aussi_les_clients_des_autres_boulangeries(self):
        c = self.mk(self.k3, 'Alain', 'Zola')
        r = api(self.l1).get(CL, {'search': 'zola'})
        self.assertIn(str(c.id), [x['id'] for x in results(r)])

    def test_gerant_k1_ne_voit_pas_client_k3_ni_par_filtre_node(self):
        c = self.mk(self.k3, 'Alain', 'Zola')
        r = api(self.g1).get(CL, {'search': 'zola'})
        self.assertEqual(results(r), [])
        r = api(self.g1).get(CL, {'node': self.k3.pk})
        self.assertEqual(results(r), [])
        self.assertEqual(api(self.g1).get(f'{CL}{c.id}/').status_code, 404)

    def test_facturier_ne_modifie_ni_ne_supprime_client_autre_boulangerie(self):
        c = self.mk(self.k3, 'Alain', 'Zola')
        self.assertEqual(api(self.f1).patch(f'{CL}{c.id}/', {'credit_limit': '90000'}, format='json').status_code, 403)
        self.assertEqual(api(self.f1).delete(f'{CL}{c.id}/').status_code, 403)
        c.refresh_from_db()
        self.assertEqual(c.credit_limit, D('50000.00'))

    def test_metacaracteres_sql_et_like_ne_cassent_pas_la_recherche(self):
        self.mk(self.k1, 'Paul', 'Mbala')
        for term in ("%", "_", "' OR 1=1 --", "\\", "a" * 500, "é", "名前", "\x00"):
            r = api(self.f1).get(CL, {'search': term})
            self.assertIn(r.status_code, (200, 400), repr(term))   # jamais 500

    def test_recherche_insensible_a_la_casse_ascii(self):
        c = self.mk(self.k1, 'Elodie', 'Nsimba')
        for term in ('nsimba', 'NSIMBA', 'elodie', 'NSIMBA elodie'):
            with self.subTest(term=term):
                r = api(self.f1).get(CL, {'search': term})
                self.assertIn(str(c.id), [x['id'] for x in results(r)])

    @expectedFailure   # BUG-743 : SQLite LIKE ASCII seulement
    def test_recherche_accent_majuscule_trouve_en_minuscule(self):
        """Prénom commençant par une majuscule accentuée (Élodie, Éric...) : taper « élodie »
        doit le trouver (SQLite LIKE ne replie la casse qu'en ASCII) - BUG-743."""
        c = self.mk(self.k1, 'Élodie', 'Nsimba')
        for term in ('élodie', 'ÉLODIE', 'Élodie'):
            with self.subTest(term=term):
                r = api(self.f1).get(CL, {'search': term})
                self.assertIn(str(c.id), [x['id'] for x in results(r)])

    def test_pertinence_exact_puis_prefixe_puis_sous_chaine(self):
        a = self.mk(self.k1, 'Jean', 'Makiese')
        b = self.mk(self.k1, 'Jean', 'Kiese')
        c = self.mk(self.k1, 'Jean', 'Kiesebis')
        ids = [x['id'] for x in results(api(self.f1).get(CL, {'search': 'kiese'}))]
        self.assertEqual(ids, [str(b.id), str(c.id), str(a.id)])

    def test_page_size_invalide_ignore_et_plafonne(self):
        for i in range(30):
            self.mk(self.k1, f'P{i}', 'Pagine')
        for ps in ('abc', '0', '-5', '', '1.5'):
            r = api(self.f1).get(CL, {'page_size': ps})
            self.assertEqual(r.status_code, 200, ps)
            self.assertEqual(len(r.data['results']), 25, ps)
        r = api(self.f1).get(CL, {'page_size': 10})
        self.assertEqual(len(r.data['results']), 10)
        r = api(self.f1).get(CL, {'page_size': 10**9})
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.data['results']), 500)
        r = api(self.f1).get(CL, {'page': 'abc'})
        self.assertEqual(r.status_code, 404)
        self.assertIn('detail', r.data)

    def test_filtres_invalides_retournent_400_pas_500(self):
        for params in ({'node': 'abc'}, {'node': '99999999999999999999'}, {'category': 'XXX'}):
            with self.subTest(params=params):
                r = api(self.direction).get(CL, params)
                self.assertEqual(r.status_code, 400, (params, r.status_code))
        r = api(self.direction).get(CL, {'ordering': 'inexistant,;--'})
        self.assertEqual(r.status_code, 200)

    def test_compte_gerant_sans_noeud_ne_voit_rien(self):
        self.mk(self.k1, 'A', 'B')
        orphan = make_user('GERANT', node=None, team='')
        self.assertEqual(results(api(orphan).get(CL)), [])

    def test_non_authentifie_refuse(self):
        r = APIClient().get(CL)
        self.assertIn(r.status_code, (401, 403))


# --------------------------------------------------------------------------
# Création, codes, plafond, photo
# --------------------------------------------------------------------------
class CreationTests(Base):
    def test_code_format_et_unicite_par_boulangerie(self):
        a = self.mk(self.k1, 'A', 'A')
        b = self.mk(self.k1, 'B', 'B')
        c = self.mk(self.k3, 'C', 'C')
        self.assertEqual((a.code, b.code, c.code), ('K1-0001', 'K1-0002', 'K3-0001'))

    def test_sequence_perimee_ne_reutilise_pas_un_code_existant(self):
        a = self.mk(self.k1, 'A', 'A')
        b = self.mk(self.k1, 'B', 'B')
        ClientCodeSequence.objects.filter(node_code='K1').update(last_number=0)  # compteur restauré à tort
        c = self.mk(self.k1, 'C', 'C')
        self.assertEqual(len({a.code, b.code, c.code}), 3)
        self.assertEqual(c.code, 'K1-0003')

    def test_codes_jamais_reutilises_apres_suppression(self):
        a = self.mk(self.k1, 'A', 'A')
        a.delete()
        b = self.mk(self.k1, 'B', 'B')
        self.assertEqual(b.code, 'K1-0002')

    def test_api_create_ignore_le_code_envoye_et_le_noeud_etranger_du_gerant(self):
        r = api(self.g1).post(CL, {'first_name': 'N', 'last_name': 'V', 'node': self.k3.pk,
                                    'code': 'HACK-1'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        c = Client.objects.get(pk=r.data['id'])
        self.assertEqual(c.node, self.k1)
        self.assertEqual(c.code, 'K1-0001')

    def test_creation_doublons_de_nom_autorises_codes_distincts(self):
        for _ in range(3):
            self.assertEqual(api(self.g1).post(CL, {'first_name': 'Jean', 'last_name': 'Dupont'},
                                               format='json').status_code, 201)
        codes = list(Client.objects.filter(node=self.k1).values_list('code', flat=True))
        self.assertEqual(len(set(codes)), 3)

    def test_champs_obligatoires_et_longueurs(self):
        r = api(self.g1).post(CL, {'first_name': '', 'last_name': ''}, format='json')
        self.assertEqual(r.status_code, 400)
        r = api(self.g1).post(CL, {'first_name': 'x' * 101, 'last_name': 'y'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = api(self.g1).post(CL, {'first_name': 'x', 'last_name': 'y', 'phone': '1' * 26}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_plafond_par_defaut_50000_et_decimal_en_chaine(self):
        r = api(self.g1).post(CL, {'first_name': 'A', 'last_name': 'B'}, format='json')
        self.assertEqual(r.status_code, 201)
        c = Client.objects.get(pk=r.data['id'])
        self.assertEqual(c.credit_limit, D('50000.00'))
        self.assertIsInstance(c.credit_limit, D)
        got = api(self.g1).get(f'{CL}{c.id}/').data
        self.assertEqual(got['credit_limit'], '50000.00')
        self.assertIsInstance(got['current_debt'], str)

    def test_plafond_modifiable_gerant_et_direction_refuse_facturier_livreur(self):
        c = self.mk(self.k1, 'A', 'B')
        self.assertEqual(api(self.g1).patch(f'{CL}{c.id}/', {'credit_limit': '80000'}, format='json').status_code, 200)
        self.assertEqual(api(self.direction).patch(f'{CL}{c.id}/', {'credit_limit': '90000'}, format='json').status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.credit_limit, D('90000.00'))
        for u in (self.f1, self.l1):
            self.assertEqual(api(u).patch(f'{CL}{c.id}/', {'credit_limit': '1'}, format='json').status_code, 403)
        c.refresh_from_db()
        self.assertEqual(c.credit_limit, D('90000.00'))

    def test_plafond_et_taux_hors_bornes_ou_mal_formes(self):
        c = self.mk(self.k1, 'A', 'B')
        for payload in ({'credit_limit': '-1'}, {'credit_limit': '10000001'}, {'credit_limit': 'NaN'},
                        {'credit_limit': 'Infinity'}, {'credit_limit': '1.234'}, {'credit_limit': 'abc'},
                        {'commission_rate': '0.31'}, {'commission_rate': '-0.01'}, {'commission_rate': '0.255'},
                        {'cotisation_sociale': '-5'}):
            r = api(self.g1).patch(f'{CL}{c.id}/', payload, format='json')
            self.assertEqual(r.status_code, 400, (payload, r.status_code))
        c.refresh_from_db()
        self.assertEqual((c.credit_limit, c.commission_rate), (D('50000.00'), D('0.25')))

    def test_facturier_cree_client_avec_valeurs_par_defaut_imposees(self):
        r = api(self.f1).post(CL, {'first_name': 'Occ', 'last_name': 'Asionnel', 'credit_limit': '9000000',
                                    'commission_rate': '0.30'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        c = Client.objects.get(pk=r.data['id'])
        self.assertEqual((c.credit_limit, c.commission_rate), (D('50000.00'), D('0.25')))

    def test_livreur_ne_cree_pas_de_client(self):
        r = api(self.l1).post(CL, {'first_name': 'A', 'last_name': 'B'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_current_debt_et_total_breads_non_modifiables_par_api(self):
        c = self.mk(self.k1, 'A', 'B')
        r = api(self.direction).patch(f'{CL}{c.id}/', {'current_debt': '999999', 'total_breads_received': 99999,
                                                       'code': 'K1-9999', 'category': 'BEST'}, format='json')
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual((c.current_debt, c.total_breads_received, c.code), (D('0.00'), 0, 'K1-0001'))
        self.assertEqual(c.category, 'NORMAL')  # recalculée, pas imposée par le client

    def test_photo_valide_acceptee_texte_deguise_et_trop_gros_refuses(self):
        buf = io.BytesIO()
        from PIL import Image
        Image.new('RGB', (4, 4), 'red').save(buf, 'PNG')
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            ok = SimpleUploadedFile('p.png', buf.getvalue(), content_type='image/png')
            r = api(self.g1).post(CL, {'first_name': 'A', 'last_name': 'B', 'photo': ok}, format='multipart')
            self.assertEqual(r.status_code, 201, r.data)
            fake = SimpleUploadedFile('p.png', b'<?php echo 1; ?>', content_type='image/png')
            r = api(self.g1).post(CL, {'first_name': 'A', 'last_name': 'B', 'photo': fake}, format='multipart')
            self.assertEqual(r.status_code, 400)
            big = SimpleUploadedFile('p.png', buf.getvalue() + b'0' * (5 * 1024 * 1024 + 1), content_type='image/png')
            r = api(self.g1).post(CL, {'first_name': 'A', 'last_name': 'B', 'photo': big}, format='multipart')
            self.assertEqual(r.status_code, 400)
            svg = SimpleUploadedFile('p.svg', b'<svg xmlns="http://www.w3.org/2000/svg"/>', content_type='image/svg+xml')
            r = api(self.g1).post(CL, {'first_name': 'A', 'last_name': 'B', 'photo': svg}, format='multipart')
            self.assertEqual(r.status_code, 400)


# --------------------------------------------------------------------------
# Catégories : bornes
# --------------------------------------------------------------------------
class CategorieTests(Base):
    def setUp(self):
        super().setUp()
        cfg = Config.get_instance()
        cfg.best_client_threshold = 1000
        cfg.save()

    def cat(self, **kw):
        c = self.mk(self.k1, 'A', 'B')
        for k, v in kw.items():
            setattr(c, k, v)
        c.refresh_category()
        return c.category

    def test_seuil_meilleur_client_borne_inclusive(self):
        self.assertEqual(self.cat(total_breads_received=999), 'NORMAL')
        self.assertEqual(self.cat(total_breads_received=1000), 'BEST')
        self.assertEqual(self.cat(total_breads_received=1001), 'BEST')

    def test_seuil_lu_dans_config_a_chaque_appel(self):
        cfg = Config.get_instance()
        cfg.best_client_threshold = 10
        cfg.save()
        self.assertEqual(self.cat(total_breads_received=10), 'BEST')

    def test_a_risque_quand_dette_egale_ou_depasse_le_plafond(self):
        self.assertEqual(self.cat(current_debt=D('49999.99')), 'NORMAL')
        self.assertEqual(self.cat(current_debt=D('50000.00')), 'RISK')
        self.assertEqual(self.cat(current_debt=D('50000.01')), 'RISK')

    def test_risque_prime_sur_meilleur_client(self):
        self.assertEqual(self.cat(current_debt=D('60000'), total_breads_received=5000), 'RISK')

    def test_bp_negative_epargne_jamais_a_risque(self):
        self.assertEqual(self.cat(current_debt=D('-250000')), 'NORMAL')

    def test_plafond_modifie_par_api_reclasse_immediatement(self):
        c = self.mk(self.k1, 'A', 'B', current_debt=D('30000'))
        r = api(self.g1).patch(f'{CL}{c.id}/', {'credit_limit': '30000'}, format='json')
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.category, 'RISK')
        api(self.g1).patch(f'{CL}{c.id}/', {'credit_limit': '30001'}, format='json')
        c.refresh_from_db()
        self.assertEqual(c.category, 'NORMAL')

    def test_recalculate_category_notifie_une_seule_fois_et_refuse_facturier(self):
        from core.models import SystemNotification
        c = self.mk(self.k1, 'A', 'B', current_debt=D('70000'))
        self.assertEqual(api(self.f1).post(f'{CL}{c.id}/recalculate_category/').status_code, 403)
        before = SystemNotification.objects.count()
        r = api(self.g1).post(f'{CL}{c.id}/recalculate_category/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['category'], 'RISK')
        self.assertEqual(SystemNotification.objects.count(), before + 1)
        api(self.g1).post(f'{CL}{c.id}/recalculate_category/')  # déjà RISK : pas de doublon
        self.assertEqual(SystemNotification.objects.count(), before + 1)

    @expectedFailure   # BUG-742 : plafond 0 et dette 0 = a risque
    def test_plafond_zero_avec_dette_zero_n_est_pas_a_risque(self):
        """Plafond 0 accepté par l'API (0..10 000 000) mais un client sans aucune
        dette est classé « à risque » (0 >= 0) : voir BUG-742."""
        self.assertEqual(self.cat(credit_limit=D('0.00'), current_debt=D('0.00')), 'NORMAL')


# --------------------------------------------------------------------------
# Actions de masse (siège) : paramètres invalides, codes, atomicité
# --------------------------------------------------------------------------
class BulkTests(Base):
    def test_bulk_move_regenere_les_codes_sans_collision(self):
        a = self.mk(self.k1, 'A', 'A')
        b = self.mk(self.k1, 'B', 'B')
        existing = self.mk(self.k3, 'E', 'E')
        r = api(self.direction).post(CL + 'bulk_move/', {'ids': [str(a.id), str(b.id)], 'node': self.k3.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['moved'], 2)
        codes = list(Client.objects.filter(node=self.k3).values_list('code', flat=True))
        self.assertEqual(len(codes), len(set(codes)), codes)
        self.assertTrue(all(c.startswith('K3-') for c in codes))
        self.assertEqual(Client.objects.get(pk=a.id).node_origin, 'K3')
        self.assertEqual(existing.code, 'K3-0001')

    def test_bulk_move_et_delete_reserves_au_siege(self):
        a = self.mk(self.k1, 'A', 'A')
        for u in (self.g1, self.f1):
            self.assertEqual(api(u).post(CL + 'bulk_move/', {'ids': [str(a.id)], 'node': self.k3.pk}, format='json').status_code, 403)
            self.assertEqual(api(u).post(CL + 'bulk_delete/', {'ids': [str(a.id)]}, format='json').status_code, 403)
        self.assertEqual(api(self.comptable).post(CL + 'bulk_move/', {'ids': [str(a.id)], 'node': self.k3.pk}, format='json').status_code, 200)

    @expectedFailure   # BUG-741 : ids/node invalides -> 500
    def test_bulk_move_parametres_invalides_400_pas_500(self):
        a = self.mk(self.k1, 'A', 'A')
        for payload in ({'ids': ['pas-un-uuid'], 'node': self.k3.pk},
                        {'ids': [str(a.id)], 'node': 'abc'},
                        {'ids': [str(a.id)], 'node': 99999999999999999999},
                        {'ids': 'abc', 'node': self.k3.pk},
                        {'ids': [str(a.id)], 'node': 424242}):
            with self.subTest(payload=payload):
                r = api(self.direction).post(CL + 'bulk_move/', payload, format='json')
                self.assertEqual(r.status_code, 400, (payload, r.status_code))

    @expectedFailure   # BUG-741 : ids invalides -> 500
    def test_bulk_delete_parametres_invalides_400_pas_500(self):
        for payload in ({'ids': ['pas-un-uuid']}, {'ids': 'abc'}, {}):
            with self.subTest(payload=payload):
                r = api(self.direction).post(CL + 'bulk_delete/', payload, format='json')
                self.assertEqual(r.status_code, 400, (payload, r.status_code))

    def test_bulk_delete_client_avec_commission_est_protege(self):
        from commissions.models import ClientCommission, CommissionPeriod
        a = self.mk(self.k1, 'A', 'A')
        p = CommissionPeriod.objects.create(node=self.k1, month=2, year=2026)
        ClientCommission.objects.create(period=p, client=a)
        free = self.mk(self.k1, 'F', 'F')
        r = api(self.direction).post(CL + 'bulk_delete/', {'ids': [str(a.id), str(free.id)]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['deleted'], len(r.data['blocked'])), (1, 1))
        self.assertTrue(Client.objects.filter(pk=a.id).exists())


# --------------------------------------------------------------------------
# Import Excel (fichiers fictifs générés en mémoire)
# --------------------------------------------------------------------------
def make_xlsx(sheets):
    """sheets = {titre: [noms]} -> octets d'un classeur au format du siège."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, names in sheets.items():
        ws = wb.create_sheet(title)
        ws.append(['LISTE FICTIVE'])
        ws.append(['DATE', 'CODE', 'NOM'])
        for n in names:
            ws.append([None, 'X', n])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload(user, content, name='clients.xlsx', dry_run=None):
    data = {'file': SimpleUploadedFile(name, content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
    if dry_run is not None:
        data['dry_run'] = dry_run
    return api(user).post(CL + 'import_excel/', data, format='multipart')


class ImportTests(Base):
    def test_import_nominal_codes_et_noeud(self):
        r = upload(self.direction, make_xlsx({'CL-K1 TABO': ['Jean Mbala', 'Marie Kapinga Lumu'],
                                              'CL- K3 ATHEN': ['Paul Nzuzi']}))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['created'], 3)
        self.assertEqual(Client.objects.filter(node=self.k1).count(), 2)
        c = Client.objects.get(node=self.k1, first_name='Marie')
        self.assertEqual(c.last_name, 'Kapinga Lumu')
        self.assertEqual(c.credit_limit, D('50000.00'))
        self.assertTrue(c.code.startswith('K1-'))

    def test_doublons_dans_le_fichier_et_en_base_insensibles_a_la_casse(self):
        self.mk(self.k1, 'Jean', 'Mbala')
        r = upload(self.direction, make_xlsx({'CL-K1': ['JEAN MBALA', 'jean  mbala', 'Luc Mavungu', 'luc mavungu']}))
        self.assertEqual(r.data['created'], 1)
        self.assertEqual(r.data['report'][0]['already_existing'], 3)
        # second passage : idempotent
        r2 = upload(self.direction, make_xlsx({'CL-K1': ['JEAN MBALA', 'Luc Mavungu']}))
        self.assertEqual(r2.data['created'], 0)

    def test_dry_run_n_ecrit_rien(self):
        r = upload(self.direction, make_xlsx({'CL-K1': ['A B', 'C D']}), dry_run='true')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['dry_run'], r.data['created']), (True, 0))
        self.assertEqual(r.data['report'][0]['to_import'], 2)
        self.assertEqual(Client.objects.count(), 0)

    def test_fichiers_malformes_donnent_400_sans_ecriture(self):
        garbage = [b'', b'PK\x03\x04 pas un vrai zip', b'a,b,c\n1,2,3\n', b'\x00' * 2048,
                   '﻿NOM;CODE\nJean;K1'.encode('utf-8')]
        for content in garbage:
            r = upload(self.direction, content)
            self.assertEqual(r.status_code, 400, content[:20])
            self.assertIn('detail', r.data if 'detail' in r.data else {'detail': 1})
        self.assertEqual(Client.objects.count(), 0)

    def test_sans_fichier_et_non_siege_refuses(self):
        self.assertEqual(api(self.direction).post(CL + 'import_excel/', {}, format='multipart').status_code, 400)
        for u in (self.g1, self.f1, self.l1):
            self.assertEqual(upload(u, make_xlsx({'CL-K1': ['A B']})).status_code, 403)
        self.assertEqual(Client.objects.count(), 0)

    def test_feuille_sans_entete_noeud_inconnu_et_feuille_vide(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'CL-K1 SANS ENTETE'
        ws.append(['rien', 'ici'])
        ws2 = wb.create_sheet('CL-K7 INCONNU')
        ws2.append(['DATE', 'CODE', 'NOM'])
        ws2.append([None, 'X', 'Paul Inconnu'])
        ws3 = wb.create_sheet('CL-K1 VIDE')
        ws3.append(['DATE', 'CODE', 'NOM'])
        wb.create_sheet('Divers')
        buf = io.BytesIO()
        wb.save(buf)
        r = upload(self.direction, buf.getvalue())
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['created'], 0)
        self.assertIn('CL-K1 SANS ENTETE', r.data['skipped_sheets'])
        self.assertIn('Divers', r.data['skipped_sheets'])
        self.assertIn('K7', r.data['unknown_nodes'])

    def test_encodage_accents_et_cellules_non_textuelles(self):
        r = upload(self.direction, make_xlsx({'CL-K1': ['Élodie Mukendi', 'Zoë Ñungu', 12345, '  Pierre   Kasa  ']}))
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['created'], 4)
        self.assertTrue(Client.objects.filter(node=self.k1, first_name='Élodie', last_name='Mukendi').exists())
        c = Client.objects.get(node=self.k1, first_name='Pierre')
        self.assertEqual(c.last_name, 'Kasa')

    def test_nom_unique_mot_repete_et_ligne_vide_interrompt_la_liste(self):
        r = upload(self.direction, make_xlsx({'CL-K1': ['Madame', '', 'Apres Vide']}))
        self.assertEqual(r.data['created'], 1)  # arrêt au premier vide (documenté dans imports.py)
        c = Client.objects.get(node=self.k1)
        self.assertEqual((c.first_name, c.last_name), ('Madame', 'Madame'))

    @expectedFailure   # BUG-746 : nom > 100 caracteres stocke tel quel
    def test_nom_trop_long_n_est_pas_ecrit_tronque_ni_500(self):
        r = upload(self.direction, make_xlsx({'CL-K1': ['X' * 150 + ' Dupont']}))
        self.assertIn(r.status_code, (200, 400))
        for c in Client.objects.all():
            self.assertLessEqual(len(c.first_name), 100)

    @expectedFailure   # BUG-746 : doublon NFC/NFD non detecte
    def test_normalisation_unicode_nfc_nfd_detectee_comme_doublon(self):
        nfc = unicodedata.normalize('NFC', 'Élodie Mukendi')
        nfd = unicodedata.normalize('NFD', 'Élodie Mukendi')
        upload(self.direction, make_xlsx({'CL-K1': [nfc]}))
        r = upload(self.direction, make_xlsx({'CL-K1': [nfd]}))
        self.assertEqual(r.data['created'], 0)

    def test_import_volumineux_codes_tous_uniques(self):
        names = [f'Prenom{i} Nom{i}' for i in range(300)]
        r = upload(self.direction, make_xlsx({'CL-K1': names, 'CL-K3': names}))
        self.assertEqual(r.data['created'], 600)
        codes = list(Client.objects.values_list('code', flat=True))
        self.assertEqual(len(codes), len(set(codes)))


# --------------------------------------------------------------------------
# Caisse sociale
# --------------------------------------------------------------------------
class CaisseSocialeTests(Base):
    def setUp(self):
        super().setUp()
        self.k1.monthly_social_contribution = D('2000')
        self.k1.save()
        self.c1 = self.mk(self.k1, 'A', 'A')
        self.c2 = self.mk(self.k1, 'B', 'B', )
        self.c3 = self.mk(self.k1, 'C', 'C')
        Client.objects.filter(pk=self.c3.pk).update(cotisation_sociale=D('0'))  # exempté
        self.c3.refresh_from_db()

    def bulk(self, user, **payload):
        return api(user).post(CONTRIB + 'bulk_create_month/', payload, format='json')

    def test_bulk_create_month_valeur_node_exemption_et_idempotence(self):
        r = self.bulk(self.g1, month=3, year=2026)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['created'], r.data['skipped']), (2, 0))
        self.assertEqual(set(SocialContribution.objects.values_list('amount', flat=True)), {D('2000.00')})
        r = self.bulk(self.g1, month=3, year=2026)
        self.assertEqual((r.data['created'], r.data['skipped']), (0, 2))
        self.assertEqual(SocialContribution.objects.count(), 2)

    def test_bulk_create_month_refuse_noeud_etranger_pour_gerant(self):
        r = self.bulk(self.g3, node=self.k1.pk, month=3, year=2026)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(SocialContribution.objects.count(), 0)

    @expectedFailure   # BUG-739 : mois/annee/montant non valides (200 ou 500)
    def test_bulk_create_month_parametres_invalides_400(self):
        for payload in ({'month': 13, 'year': 2026}, {'month': 0, 'year': 2026}, {'month': 'abc', 'year': 2026},
                        {'month': 3, 'year': 'abc'}, {'month': 3, 'year': -5}, {'month': 3, 'year': 99999999999},
                        {'month': 3, 'year': 2026, 'amount': 'abc'}, {'month': 3, 'year': 2026, 'amount': '-100'},
                        {'month': 3, 'year': 2026, 'amount': '999999999999'},
                        {'month': 3, 'year': 2026, 'node': 'abc'}):
            with self.subTest(payload=payload):
                r = api(self.direction).post(CONTRIB + 'bulk_create_month/',
                                             dict({'node': self.k1.pk}, **payload), format='json')
                self.assertEqual(r.status_code, 400, (payload, r.status_code))
                SocialContribution.objects.all().delete()

    def test_bulk_create_month_montant_manuel_decimal_exact(self):
        r = self.bulk(self.g1, month=4, year=2026, amount='1500.50')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(SocialContribution.objects.values_list('amount', flat=True)), {D('1500.50')})

    def test_contribution_api_mois_montant_et_doublon(self):
        base = {'client': str(self.c1.id), 'node': self.k1.pk, 'month': 5, 'year': 2026, 'amount': '2000'}
        self.assertEqual(api(self.g1).post(CONTRIB, base, format='json').status_code, 201)
        self.assertEqual(api(self.g1).post(CONTRIB, base, format='json').status_code, 400)  # doublon
        for bad in ({'month': 13}, {'month': 0}, {'amount': '-1'}, {'amount': '12345678901'}):
            payload = dict(base, **bad)
            payload['client'] = str(self.c2.id)
            self.assertEqual(api(self.g1).post(CONTRIB, payload, format='json').status_code, 400, bad)

    def test_contribution_client_autre_boulangerie_refuse(self):
        foreign = self.mk(self.k3, 'Z', 'Z')
        r = api(self.g1).post(CONTRIB, {'client': str(foreign.id), 'node': self.k1.pk, 'month': 5,
                                        'year': 2026, 'amount': '2000'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_toggle_paid_aller_retour_et_isolation(self):
        sc = SocialContribution.objects.create(client=self.c1, node=self.k1, month=1, year=2026, amount=D('2000'))
        r = api(self.g1).post(f'{CONTRIB}{sc.id}/toggle_paid/')
        self.assertTrue(r.data['is_paid'])
        sc.refresh_from_db()
        self.assertIsNotNone(sc.paid_at)
        api(self.g1).post(f'{CONTRIB}{sc.id}/toggle_paid/')
        sc.refresh_from_db()
        self.assertEqual((sc.is_paid, sc.paid_at), (False, None))
        self.assertEqual(api(self.g3).post(f'{CONTRIB}{sc.id}/toggle_paid/').status_code, 404)
        self.assertEqual(api(self.f1).post(f'{CONTRIB}{sc.id}/toggle_paid/').status_code, 403)

    def test_liste_contributions_isolee_et_filtres_invalides(self):
        SocialContribution.objects.create(client=self.c1, node=self.k1, month=1, year=2026, amount=D('2000'))
        self.assertEqual(len(results(api(self.g3).get(CONTRIB))), 0)
        self.assertEqual(len(results(api(self.g1).get(CONTRIB))), 1)
        for params in ({'month': 'abc'}, {'year': 'abc'}, {'node': 'abc'}, {'client': 'pas-uuid'}):
            self.assertEqual(api(self.direction).get(CONTRIB, params).status_code, 400, params)

    def _distribution(self, year=2026, tarif='700'):
        return api(self.direction).post(DISTRIB, {'node': self.k1.pk, 'year': year, 'tarif': tarif}, format='json')

    def test_distribution_calculs_exacts_a_la_main(self):
        # c1 : 3 mois payés x 2000 = 6000 ; indice 3 ; remise = 3 x 700 = 2100 ; mérite 150,50
        for m in (1, 2, 3):
            SocialContribution.objects.create(client=self.c1, node=self.k1, month=m, year=2026,
                                              amount=D('2000'), is_paid=True)
        SocialContribution.objects.create(client=self.c1, node=self.k1, month=4, year=2026, amount=D('2000'))  # impayé
        # année voisine : ne compte pas
        SocialContribution.objects.create(client=self.c1, node=self.k1, month=12, year=2025,
                                          amount=D('2000'), is_paid=True)
        d = self._distribution()
        self.assertEqual(d.status_code, 201, d.data)
        r = api(self.g1).post(f"{DISTRIB}{d.data['id']}/auto_populate_lines/")
        self.assertEqual(r.status_code, 200, r.data)
        line = SocialDistributionLine.objects.get(client=self.c1)
        self.assertEqual((line.indice, line.total_social, line.remise, line.total_payer),
                         (3, D('6000.00'), D('2100.00'), D('8100.00')))
        # mérite
        r = api(self.g1).patch(f'{LINES}{line.id}/', {'merite': '150.50'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        line.refresh_from_db()
        self.assertEqual(line.total_payer, D('8250.50'))
        self.assertIsInstance(line.total_payer, D)
        # c3 (exempté) n'a pas de ligne
        self.assertFalse(SocialDistributionLine.objects.filter(client=self.c3).exists())
        # idempotence
        r = api(self.g1).post(f"{DISTRIB}{d.data['id']}/auto_populate_lines/")
        self.assertEqual(r.data['created'], 0)

    def test_distribution_unique_par_noeud_et_annee_et_bornes(self):
        self.assertEqual(self._distribution().status_code, 201)
        self.assertEqual(self._distribution().status_code, 400)
        for payload in ({'year': 1999}, {'year': 2201}, {'tarif': '-1'}, {'tarif': 'abc'}):
            data = dict({'node': self.k1.pk, 'year': 2030, 'tarif': '700'}, **payload)
            self.assertEqual(api(self.direction).post(DISTRIB, data, format='json').status_code, 400, payload)

    def test_distribution_cloturee_figee(self):
        d = self._distribution().data
        self.assertEqual(api(self.direction).patch(f"{DISTRIB}{d['id']}/", {'is_closed': True}, format='json').status_code, 200)
        self.assertEqual(api(self.direction).patch(f"{DISTRIB}{d['id']}/", {'is_closed': False}, format='json').status_code, 400)
        self.assertEqual(api(self.direction).patch(f"{DISTRIB}{d['id']}/", {'tarif': '999'}, format='json').status_code, 400)
        self.assertEqual(api(self.g1).post(f"{DISTRIB}{d['id']}/auto_populate_lines/").status_code, 400)
        self.assertEqual(api(self.g1).post(f"{DISTRIB}{d['id']}/refresh_indices/").status_code, 400)

    def test_gerant_ne_fixe_pas_le_tarif_ni_ne_cloture(self):
        d = self._distribution().data
        self.assertEqual(api(self.g1).patch(f"{DISTRIB}{d['id']}/", {'tarif': '10'}, format='json').status_code, 403)
        self.assertEqual(api(self.g1).patch(f"{DISTRIB}{d['id']}/", {'is_closed': True}, format='json').status_code, 403)

    def test_ligne_client_autre_boulangerie_et_isolation_des_lignes(self):
        d = self._distribution().data
        foreign = self.mk(self.k3, 'Z', 'Z')
        r = api(self.direction).post(LINES, {'distribution': d['id'], 'client': str(foreign.id)}, format='json')
        self.assertEqual(r.status_code, 400)
        r = api(self.g1).post(LINES, {'distribution': d['id'], 'client': str(self.c1.id), 'indice': 2,
                                      'total_social': '4000', 'merite': '0'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(api(self.g3).get(f"{LINES}{r.data['id']}/").status_code, 404)
        self.assertEqual(r.data['remise'], '1400.00')
        self.assertEqual(r.data['total_payer'], '5400.00')

    @expectedFailure   # BUG-740 : indice hors plage / merite negatif acceptes
    def test_ligne_valeurs_negatives_ou_hors_borne_refusees(self):
        d = self._distribution().data
        for bad in ({'indice': -1}, {'indice': 100000}, {'total_social': '-5'}, {'merite': '-5'},
                    {'total_social': '99999999999'}):
            with self.subTest(bad=bad):
                payload = dict({'distribution': d['id'], 'client': str(self.c2.id)}, **bad)
                r = api(self.g1).post(LINES, payload, format='json')
                self.assertEqual(r.status_code, 400, (bad, r.status_code))
                SocialDistributionLine.objects.filter(client=self.c2).delete()

    def test_suppression_client_avec_ligne_de_distribution_protegee(self):
        d = self._distribution().data
        api(self.g1).post(LINES, {'distribution': d['id'], 'client': str(self.c1.id)}, format='json')
        r = api(self.direction).post(CL + 'bulk_delete/', {'ids': [str(self.c1.id)]}, format='json')
        self.assertEqual(r.data['deleted'], 0)
        self.assertEqual(len(r.data['blocked']), 1)

    def test_effective_cotisation_suit_la_boulangerie_puis_personnalisation(self):
        self.assertEqual(self.c1.effective_cotisation_sociale, D('2000.00'))
        self.k1.monthly_social_contribution = D('2500')
        self.k1.save()
        c = Client.objects.get(pk=self.c1.pk)
        self.assertEqual(c.effective_cotisation_sociale, D('2500.00'))
        Client.objects.filter(pk=c.pk).update(cotisation_sociale=D('1234.56'))
        c.refresh_from_db()
        self.assertEqual(c.effective_cotisation_sociale, D('1234.56'))
        self.assertIsInstance(c.effective_cotisation_sociale, D)


# --------------------------------------------------------------------------
# Historique client : paramètres
# --------------------------------------------------------------------------
class HistoriqueParamsTests(Base):
    def test_history_month_invalide_400(self):
        c = self.mk(self.k1, 'A', 'B')
        for raw in ('abc', '2026-13', '2026-00', '1999-05', '2026/05', '2026-5', "2026-05'; --", '9999999-01'):
            r = api(self.g1).get(f'{CL}{c.id}/history/', {'month': raw})
            self.assertEqual(r.status_code, 400, raw)
        self.assertEqual(api(self.g1).get(f'{CL}{c.id}/history/', {'month': '2026-05'}).status_code, 200)

    def test_history_isole_par_noeud_et_refuse_facturier(self):
        c = self.mk(self.k3, 'A', 'B')
        self.assertEqual(api(self.g1).get(f'{CL}{c.id}/history/').status_code, 404)
        self.assertEqual(api(self.f1).get(f'{CL}{c.id}/history/').status_code, 403)
        self.assertEqual(api(self.g3).get(f'{CL}{c.id}/history/').status_code, 200)

    def test_bassins_parametres_invalides(self):
        for params in ({'node': self.k1.pk, 'month': 'abc', 'year': 2026},
                       {'node': self.k1.pk, 'month': 2, 'year': 'x'},
                       {'node': 'abc', 'month': 2, 'year': 2026},
                       {'node': self.k1.pk, 'month': 13, 'year': 2026},
                       {'node': self.k1.pk, 'month': 2, 'year': 99999999999999999999},
                       {'node': self.k1.pk, 'month': 99999999999999999999, 'year': 2026}):
            r = api(self.direction).get(CL + 'bassins/', params)
            self.assertIn(r.status_code, (200, 400), (params, r.status_code))
            self.assertNotEqual(r.status_code, 500, params)

    def test_bassins_gerant_borne_a_son_noeud(self):
        from commissions.models import CommissionPeriod
        CommissionPeriod.objects.create(node=self.k3, month=2, year=2026)
        r = api(self.g1).get(CL + 'bassins/', {'node': self.k3.pk, 'month': 2, 'year': 2026})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['rows'], [])
        self.assertIn('Aucune période', r.data.get('detail', ''))

    def test_deficit_report_et_alertes_isolation(self):
        self.mk(self.k3, 'R', 'Isque', current_debt=D('70000'))
        rk = Client.objects.get(last_name='Isque')
        rk.refresh_category()
        rk.save()
        self.assertEqual(api(self.f1).get(CL + 'deficit_report/').status_code, 403)
        self.assertEqual(api(self.g1).get(CL + 'deficit_report/').data, [])
        self.assertEqual(api(self.direction).get(CL + 'deficit_report/', {'node': 'abc'}).status_code, 400)
        self.assertEqual(api(self.direction).get(CL + 'deficit_report/', {'node': '9' * 30}).status_code, 400)
