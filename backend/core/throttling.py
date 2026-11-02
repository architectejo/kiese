"""Throttles dédiés à l'authentification (BUG-087, suite de BUG-006).

`ScopedRateThrottle` (DRF) clé son compteur sur l'IP dès que la vue n'a pas
d'utilisateur authentifié — c'est le cas de `/api/core/auth/login/`
(`AllowAny`). Conséquence : toutes les tentatives de connexion venant d'une
même IP partagent le même compteur, *y compris les connexions réussies* et
*peu importe le compte visé*. Dans une boulangerie, plusieurs employés se
connectant l'un après l'autre depuis le même poste/réseau local se
bloquaient donc mutuellement dès la 6e connexion (BUG-087).

Deux throttles remplacent `ScopedRateThrottle` sur cette vue :

- `LoginAccountRateThrottle` : clé = compte visé (`username` du payload,
  normalisé). C'est la vraie protection anti-brute-force : marteler UN
  compte reste limité, quelle que soit l'IP d'origine.
- `LoginIPRateThrottle` : clé = IP, avec un plafond plus large, conservé en
  complément pour freiner le credential-stuffing / l'énumération de comptes
  distincts depuis une même source (ex. script automatisé testant de
  nombreux identifiants).

Si le payload ne contient pas de `username` exploitable (requête
malformée), `LoginAccountRateThrottle` retombe sur l'IP afin que l'endpoint
reste toujours protégé.
"""
from rest_framework.throttling import SimpleRateThrottle


class LoginAccountRateThrottle(SimpleRateThrottle):
    """Limite les tentatives de connexion par compte visé (pas par IP)."""

    scope = 'login'

    def get_cache_key(self, request, view):
        username = (request.data.get('username') or '').strip().lower()
        ident = username or self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class LoginIPRateThrottle(SimpleRateThrottle):
    """Garde-fou large par IP, en complément, contre le credential-stuffing."""

    scope = 'login_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }
