"""
BUG-284 : changement de mot de passe obligatoire.

Tant que `user.must_change_password` est True, toute route de l'API est refusée
(403, code `password_change_required`) sauf login, refresh, logout, profil et
changement de mot de passe. Centralisé dans l'authentification pour couvrir
toutes les vues, quelles que soient leurs `permission_classes`.
"""
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

EXEMPT_PATHS = (
    '/api/core/auth/login/',
    '/api/core/auth/login/refresh/',
    '/api/core/auth/logout/',
    '/api/core/auth/me/',
    '/api/core/auth/change-password/',
)


class PasswordChangeRequired(PermissionDenied):
    default_code = 'password_change_required'

    def __init__(self):
        super().__init__(
            detail={
                'detail': "Changement de mot de passe obligatoire avant de poursuivre.",
                'code': 'password_change_required',
            },
            code='password_change_required',
        )


def _check(request, result):
    if result is None:
        return result
    user = result[0]
    if getattr(user, 'must_change_password', False):
        path = request.path.rstrip('/') + '/'
        if path not in EXEMPT_PATHS:
            raise PasswordChangeRequired()
    return result


class ForcedPasswordJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        return _check(request, super().authenticate(request))


class ForcedPasswordSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        return _check(request, super().authenticate(request))
