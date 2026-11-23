"""
Q-025 / BUG-507 / BUG-1106 : « en ligne » = le poste peut joindre le cloud (etskiese.com).

Definition unique, utilisee par `clients.views.ClientViewSet.get_queryset` :

* CLOUD (deploiement serveur, mode de test inclus) : `settings.KIESE_CLOUD_URL` est
  absent ou vide (seul `kiese/settings_desktop.py` le lit dans l'environnement) ->
  tout utilisateur est par definition en ligne : toujours True.
* POSTE LOCAL (settings desktop, `KIESE_CLOUD_URL` renseigne) : en ligne si le dernier
  echange de synchronisation REUSSI avec le cloud (push ou pull, memorise en memoire
  par `sync.desktop_client`, ou `Node.last_sync` de la boulangerie) date de moins de
  N minutes. N = `KIESE_ONLINE_WINDOW_MINUTES` (parametre ou variable d'environnement,
  defaut 15 ; la boucle de synchronisation tourne toutes les 30 s). Jamais synchronise
  ou echange perime : hors ligne. Toute valeur invalide de N retombe sur 15.
"""
import os
import time

from django.conf import settings
from django.utils import timezone

DEFAULT_ONLINE_WINDOW_MINUTES = 15


def is_local_post() -> bool:
    return bool(getattr(settings, 'KIESE_CLOUD_URL', '') or '')


def online_window_minutes() -> float:
    raw = getattr(settings, 'KIESE_ONLINE_WINDOW_MINUTES', None)
    if raw in (None, ''):
        raw = os.environ.get('KIESE_ONLINE_WINDOW_MINUTES')
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_ONLINE_WINDOW_MINUTES
    return value if value > 0 else DEFAULT_ONLINE_WINDOW_MINUTES


def _last_exchange_epoch(node):
    """Epoch (secondes) du dernier echange reussi connu, ou None."""
    candidates = []
    try:
        from sync.desktop_client import get_local_sync_state
        state = get_local_sync_state()
        candidates += [state.get('last_push_at'), state.get('last_pull_at')]
    except Exception:  # module desktop indisponible : on retombe sur Node.last_sync
        pass
    last_sync = getattr(node, 'last_sync', None)
    if last_sync is not None:
        candidates.append(last_sync.timestamp())
    candidates = [c for c in candidates if isinstance(c, (int, float))]
    return max(candidates) if candidates else None


def node_is_online(node, now=None) -> bool:
    """True si la boulangerie `node` est consideree en ligne (voir le docstring du module)."""
    if not is_local_post():
        return True
    last = _last_exchange_epoch(node)
    if last is None:
        return False
    now_epoch = time.time() if now is None else now.timestamp()
    return 0 <= now_epoch - last <= online_window_minutes() * 60
