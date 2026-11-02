"""
Tests API Client — permissions et recherche prédictive (CLAUDE.md §5.1,
BUG-012).
"""
import io

from decimal import Decimal

from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.test import TestCase

from core.testing import make_node, make_user, make_client
from clients.models import Client


class FacturierCrossNodeSearchTests(TestCase):
    """remarque.md l.10-12 : un facturier peut voir/rechercher les clients
    des AUTRES boulangeries (règle prioritaire sur un filtrage strict par
    nœud)."""

    def setUp(self):
        self.k1 = make_node(code='K1', name='K1 - TABORA')
        self.k3 = make_node(code='K3', name='K3 - ATHENEE')
        self.client_k3 = make_client(self.k3, first_name='DEMO', last_name='DeK3')
        self.facturier_k1 = make_user(role='FACTURIER', node=self.k1)
        self.api = APIClient()
        self.api.force_authenticate(user=self.facturier_k1)

    def test_facturier_can_find_client_from_other_node_by_partial_name(self):
        resp = self.api.get('/api/clients/clients/', {'search': 'DeK3'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        results = data.get('results', data)
        codes = [c['code'] for c in results]
        self.assertIn(self.client_k3.code, codes)

    def test_facturier_can_find_client_from_other_node_by_code(self):
        resp = self.api.get('/api/clients/clients/', {'search': self.client_k3.code})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        results = data.get('results', data)
        codes = [c['code'] for c in results]
        self.assertIn(self.client_k3.code, codes)

    def test_gerant_of_k1_cannot_see_clients_of_k3(self):
        """Contraste : seul le facturier (et le livreur) bénéficie de
        l'exception de visibilité inter-boulangeries ; un gérant reste
        limité à son propre nœud."""
        gerant_k1 = make_user(role='GERANT', node=self.k1)
        api = APIClient()
        api.force_authenticate(user=gerant_k1)
        resp = api.get('/api/clients/clients/', {'search': self.client_k3.code})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        results = data.get('results', data)
        codes = [c['code'] for c in results]
        self.assertNotIn(self.client_k3.code, codes)


class ClientCreditLimitPermissionTests(TestCase):
    """CLAUDE.md §5.1 : modification du plafond crédit autorisée pour
    gérant/direction, refusée pour facturier/livreur."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.client = make_client(self.node, credit_limit=Decimal('50000.00'))

    def _patch_credit_limit(self, user, new_limit='120000.00'):
        api = APIClient()
        api.force_authenticate(user=user)
        return api.patch(
            f'/api/clients/clients/{self.client.pk}/',
            {'credit_limit': new_limit},
            format='json',
        )

    def test_gerant_can_modify_credit_limit(self):
        gerant = make_user(role='GERANT', node=self.node)
        resp = self._patch_credit_limit(gerant)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.client.refresh_from_db()
        self.assertEqual(self.client.credit_limit, Decimal('120000.00'))

    def test_direction_can_modify_credit_limit(self):
        direction = make_user(role='DIRECTION', node=None)
        resp = self._patch_credit_limit(direction)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_facturier_cannot_modify_credit_limit(self):
        facturier = make_user(role='FACTURIER', node=self.node)
        resp = self._patch_credit_limit(facturier)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.client.refresh_from_db()
        self.assertEqual(self.client.credit_limit, Decimal('50000.00'))

    def test_livreur_cannot_modify_credit_limit(self):
        livreur = make_user(role='LIVREUR', node=self.node)
        resp = self._patch_credit_limit(livreur)
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.client.refresh_from_db()
        self.assertEqual(self.client.credit_limit, Decimal('50000.00'))


class ClientCreationCreditLimitApiTests(TestCase):
    """remarque.md l.172 au niveau API : le champ "Plafond Crédit (FC)" du
    formulaire de création doit être pris en compte même > défaut."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node)
        self.api = APIClient()
        self.api.force_authenticate(user=self.gerant)

    def test_custom_credit_limit_survives_creation_via_api(self):
        resp = self.api.post('/api/clients/clients/', {
            'first_name': 'DEMO', 'last_name': 'Grossiste-API',
            'node': str(self.node.pk),
            'credit_limit': '750000.00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        created = Client.objects.get(last_name='Grossiste-API')
        self.assertEqual(created.credit_limit, Decimal('750000.00'))


class ClientCreateResponseContractTests(TestCase):
    """BUG-088 (docs/qa/REGISTRE_BUGS.md) : la réponse de création d'un
    client doit contenir son `id` (et son `code` auto-généré) pour que le
    frontend puisse l'utiliser immédiatement (ex. création automatique du
    « Client Occasionnel » dans `Clients.tsx`, qui lit `res.data.id` juste
    après l'appel `clientsApi.create()`). `ClientCreateSerializer.Meta.fields`
    ne les liste pas aujourd'hui."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node)
        self.api = APIClient()
        self.api.force_authenticate(user=self.gerant)

    def test_create_response_is_missing_id_and_code_bug_088(self):
        resp = self.api.post('/api/clients/clients/', {
            'first_name': 'Client', 'last_name': 'Occasionnel-BUG088',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertTrue(
            Client.objects.filter(last_name='Occasionnel-BUG088').exists(),
            "Le client doit bel et bien être créé en base malgré la réponse incomplète."
        )
        self.assertIn(
            'id', resp.data,
            "La réponse de création d'un client doit contenir son `id` — "
            "sans cela, le frontend ne peut pas enchaîner immédiatement une "
            "facture pour ce client nouvellement créé (BUG-088)."
        )
        self.assertIn('code', resp.data)


class ClientPhotoValidationTests(TestCase):
    """CLAUDE.md §5.1 : photo (types/taille) — un fichier qui n'est pas une
    image réelle doit être rejeté (validation native Django ImageField)."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        self.gerant = make_user(role='GERANT', node=self.node)
        self.api = APIClient()
        self.api.force_authenticate(user=self.gerant)

    def test_non_image_file_is_rejected_as_photo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake_photo = SimpleUploadedFile(
            'fausse_photo.jpg', b'ceci-nest-pas-une-image', content_type='image/jpeg'
        )
        resp = self.api.post('/api/clients/clients/', {
            'first_name': 'DEMO', 'last_name': 'Photo-Invalide',
            'node': str(self.node.pk),
            'photo': fake_photo,
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('photo', resp.json())


class FacturierCanCreateClientTests(TestCase):
    """BUG-089 (docs/qa/REGISTRE_BUGS.md) : décision client (M. NDUNGA NSAYI
    PIERRE, 2026-10-30) — un FACTURIER doit pouvoir créer un « Client
    Occasionnel » pour une vente directe au comptant (CLAUDE.md §5.1,
    `Clients.tsx` `triggerCasualSale`). Assouplissement CIBLÉ sur `create`
    uniquement : les autres opérations sensibles restent réservées à
    GERANT+ (même motif que BUG-012/BUG-025/BUG-030/BUG-056)."""

    def setUp(self):
        self.k1 = make_node(code='K1', name='K1 - TABORA')
        self.k3 = make_node(code='K3', name='K3 - ATHENEE')
        self.facturier_k1 = make_user(role='FACTURIER', node=self.k1)
        self.api = APIClient()
        self.api.force_authenticate(user=self.facturier_k1)

    def test_facturier_can_create_client(self):
        resp = self.api.post('/api/clients/clients/', {
            'first_name': 'Client', 'last_name': 'Occasionnel-BUG089',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        self.assertTrue(
            Client.objects.filter(last_name='Occasionnel-BUG089').exists()
        )

    def test_facturier_created_client_is_forced_to_own_node_even_if_other_node_forged(self):
        """BUG-025/BUG-030 (même motif) : un FACTURIER ne doit jamais pouvoir
        rattacher le client créé à une autre boulangerie en forgeant `node`
        dans le payload."""
        resp = self.api.post('/api/clients/clients/', {
            'first_name': 'Client', 'last_name': 'Occasionnel-AutreNoeud',
            'node': str(self.k3.pk),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)
        created = Client.objects.get(last_name='Occasionnel-AutreNoeud')
        self.assertEqual(created.node_id, self.k1.pk)
        self.assertEqual(created.node_origin, self.k1.code)

    def test_facturier_cannot_update_client(self):
        existing = make_client(self.k1, first_name='Existant', last_name='BUG089')
        resp = self.api.patch(
            f'/api/clients/clients/{existing.pk}/',
            {'last_name': 'Modifie-Par-Facturier'},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_facturier_cannot_delete_client(self):
        existing = make_client(self.k1, first_name='Existant', last_name='ASupprimer')
        resp = self.api.delete(f'/api/clients/clients/{existing.pk}/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Client.objects.filter(pk=existing.pk).exists())

    def test_facturier_cannot_bulk_move_client(self):
        existing = make_client(self.k1, first_name='Existant', last_name='AMouvoir')
        resp = self.api.post('/api/clients/clients/bulk_move/', {
            'ids': [str(existing.pk)], 'node': str(self.k3.pk),
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        existing.refresh_from_db()
        self.assertEqual(existing.node_id, self.k1.pk)

    def test_gerant_create_still_works_after_bug089_fix(self):
        """Non-régression : un GERANT (déjà autorisé) peut toujours créer un
        client après l'assouplissement ciblé sur FACTURIER."""
        gerant = make_user(role='GERANT', node=self.k1)
        api = APIClient()
        api.force_authenticate(user=gerant)
        resp = api.post('/api/clients/clients/', {
            'first_name': 'Client', 'last_name': 'Occasionnel-Gerant-BUG089',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.content)

    def test_livreur_still_cannot_create_client(self):
        """Non-régression : LIVREUR n'est pas concerné par la décision
        client, qui vise explicitement le FACTURIER (vente directe au
        comptoir) — il reste exclu de `create`."""
        livreur = make_user(role='LIVREUR', node=self.k1)
        api = APIClient()
        api.force_authenticate(user=livreur)
        resp = api.post('/api/clients/clients/', {
            'first_name': 'Client', 'last_name': 'Occasionnel-Livreur',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class SearchRelevanceOrderingTests(TestCase):
    """BUG-095 : tri par pertinence de la recherche prédictive (remarque.md
    point 2) — exact > préfixe > substring, décision du coordinateur
    (pas de restriction stricte des résultats, juste l'ordre)."""

    def setUp(self):
        self.node = make_node(code='K1', name='K1 - TABORA')
        # "Makiese" ne correspond à "kiese" qu'en substring.
        self.makiese = make_client(self.node, first_name='Jean', last_name='Makiese')
        # "Kiese" correspond en préfixe à "kiese" (et en nom complet exact
        # si on cherche "kiese jean").
        self.kiese = make_client(self.node, first_name='Jean', last_name='Kiese')
        self.api = APIClient()
        self.api.force_authenticate(user=make_user(role='GERANT', node=self.node))

    def _codes(self, search_term):
        resp = self.api.get('/api/clients/clients/', {'search': search_term})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        results = data.get('results', data)
        return [c['code'] for c in results]

    def test_prefix_match_ranked_before_substring_only_match(self):
        """"kiese" doit faire apparaître "Kiese" (préfixe de last_name) avant
        "Makiese" (substring uniquement)."""
        codes = self._codes('kiese')
        self.assertIn(self.kiese.code, codes)
        self.assertIn(self.makiese.code, codes)
        self.assertLess(codes.index(self.kiese.code), codes.index(self.makiese.code))

    def test_exact_code_match_ranked_first(self):
        """Une recherche par code exact place ce client en tête, même si un
        autre client a un nom contenant une sous-chaîne correspondante."""
        codes = self._codes(self.kiese.code)
        self.assertEqual(codes[0], self.kiese.code)

    def test_explicit_ordering_param_overrides_relevance(self):
        """Non-régression : si l'appelant demande explicitement un tri
        (`?ordering=`), celui-ci reste respecté — on ne force pas la
        pertinence dans ce cas."""
        resp = self.api.get('/api/clients/clients/', {
            'search': 'kiese', 'ordering': '-last_name',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        results = data.get('results', data)
        codes = [c['code'] for c in results]
        # Ordre alphabétique descendant par last_name : "Makiese" > "Kiese".
        self.assertEqual(codes, [self.makiese.code, self.kiese.code])

    def test_substring_search_still_returns_all_matches(self):
        """Non-régression : le comportement de filtrage substring n'est pas
        restreint — les deux clients homonymes restent visibles."""
        codes = self._codes('kiese')
        self.assertEqual(set(codes), {self.kiese.code, self.makiese.code})
