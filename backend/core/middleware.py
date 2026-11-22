from django.http import JsonResponse
from core.models import Config

class OnlineOfflineRoutingMiddleware:
    """
    Optional middleware that can enforce online/offline routing at the API level
    if needed. For our SPA, routing is primarily handled client-side.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # We can add custom header or checks here
        response = self.get_response(request)
        
        # Inject system status header
        try:
            config = Config.get_instance()
            response['X-Kiese-Online'] = 'True' if config.on_line else 'False'
        except Exception:
            pass
            
        return response


class AdminLoginThrottleMiddleware:
    """BUG-704 : limite les échecs de connexion sur /admin/login/ (comme l'API).

    Compteurs par compte visé et par IP (plafond plus large), fenêtre glissante
    via le cache. Au-delà : HTTP 429. Une connexion réussie remet le compte à 0.
    Réglages : DJANGO_ADMIN_LOGIN_MAX_ATTEMPTS (défaut 10), DJANGO_ADMIN_LOGIN_WINDOW (secondes, défaut 900).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _limits():
        import os
        try:
            maxi = int(os.environ.get('DJANGO_ADMIN_LOGIN_MAX_ATTEMPTS', '10'))
            window = int(os.environ.get('DJANGO_ADMIN_LOGIN_WINDOW', '900'))
        except ValueError:
            maxi, window = 10, 900
        return maxi, window

    def __call__(self, request):
        if request.method != 'POST' or not request.path.rstrip('/').endswith('/admin/login'):
            return self.get_response(request)
        from django.core.cache import cache
        maxi, window = self._limits()
        ip = request.META.get('REMOTE_ADDR', '')
        user = str(request.POST.get('username', '')).strip().lower()[:150]
        keys = {f'adminlogin:ip:{ip}': maxi * 3, f'adminlogin:user:{user}': maxi}
        if any(cache.get(k, 0) >= lim for k, lim in keys.items()):
            return JsonResponse({'detail': 'Trop de tentatives de connexion. Réessayez plus tard.'}, status=429)
        response = self.get_response(request)
        if response.status_code == 302:
            cache.delete(f'adminlogin:user:{user}')
        else:
            for k in keys:
                cache.add(k, 0, window)
                try:
                    cache.incr(k)
                except ValueError:
                    cache.set(k, 1, window)
        return response
