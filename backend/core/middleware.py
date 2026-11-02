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
