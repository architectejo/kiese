import os
import sys

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# Put our app folder FIRST so it wins over any other Django app on the server
sys.path = [APP_ROOT] + [p for p in sys.path if p != APP_ROOT]

# override=True ensures our .env values win over any existing env vars
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(APP_ROOT, '.env'), override=True)
except ImportError:
    pass

# Direct assignment (not setdefault) to override any DJANGO_SETTINGS_MODULE set by another app
os.environ['DJANGO_SETTINGS_MODULE'] = 'kiese.settings'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
