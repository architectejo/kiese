"""
Authentification de nœud — distincte des JWT utilisateur
(docs/architecture/SYNC.md §8, cahierDesCharges.md §6.3.1).

Utilisée exclusivement sur les routes `/api/sync/*`. Un utilisateur
individuel authentifié par son propre JWT ne peut jamais appeler ces
routes : seul un `NodeAuthToken` valide, émis depuis le siège pour une
boulangerie précise, est accepté ici.
"""

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication

from .models import NodeAuthToken


class NodeTokenAuthentication(BaseAuthentication):
    keyword = 'Bearer'

    def authenticate(self, request):
        header = request.headers.get('Authorization', '')
        if not header.startswith(f'{self.keyword} '):
            return None
        raw_token = header[len(self.keyword) + 1:].strip()
        if not raw_token:
            return None
        token = NodeAuthToken.authenticate(raw_token)
        if token is None:
            return None
        # Pas d'utilisateur Django associé à un jeton de nœud : on renvoie
        # un utilisateur anonyme pour satisfaire l'API DRF, l'identité
        # réelle de la requête est `request.auth` (le NodeAuthToken), pas
        # `request.user`.
        return (AnonymousUser(), token)

    def authenticate_header(self, request):
        return self.keyword
