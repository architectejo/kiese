"""
Client de synchronisation embarqué, exécuté en tâche de fond par
`desktop_server.py` sur un poste desktop (DESKTOP.md §5/§9, SYNC.md §3/§8).

Ce module ne réimplémente pas le protocole déjà conçu et livré par
`architecte-sync` : il réutilise directement les fonctions de
`sync.management.commands.sync_now` (`build_outbound_payload`,
`apply_push_response`, `apply_pull_response`) et se contente d'orchestrer
leur exécution périodique avec deux garanties que la commande manuelle ne
fournit pas (et n'a pas besoin de fournir pour un usage ponctuel en ligne de
commande) :

1. **BUG-067** (docs/qa/REGISTRE_BUGS.md) : un `503` de `/api/sync/push/`,
   `/handshake/` ou `/pull/` signifie « échec transitoire d'infrastructure
   côté Cloud, aucun `SyncBatchLog` n'a été persisté — réessayez EXACTEMENT
   le même lot plus tard ». Ce n'est jamais une erreur métier définitive
   (contrairement à 400/401/403) : ce module ne régénère JAMAIS un nouveau
   `batch_id` après un 503, et ne marque jamais rien `is_synced=True` tant
   qu'une réponse définitive n'a pas été reçue.
2. **Persistance locale du lot en attente** (`<data_dir>/sync_outbox.json`,
   l'« OutboxBatch » informel décrit par SYNC.md §3.6/§7.1) : si le
   processus backend est arrêté/redémarré pendant qu'un lot attend sa
   confirmation, le même lot (mêmes enregistrements, même `batch_id`) est
   rechargé au redémarrage plutôt que d'en construire un nouveau à partir
   des lignes encore `is_synced=False` — évite de dépendre uniquement de la
   mémoire du processus pour cette garantie.

Volontairement séparé de `sync_now.py` : aucun fichier déjà livré par
`architecte-sync` n'est modifié ici, seulement appelé/étendu.

Historique (BUG-072) : à l'origine, `sync_now.py` seul, sans ce module, ne
respectait pas BUG-067 pour un usage en ligne de commande répétée
manuellement (il régénérait un nouveau `batch_id` à chaque invocation et
traitait le 503 comme une erreur fatale identique aux autres). Corrigé
depuis par `dev-backend` (BUG-067/BUG-072) : `sync_now.py` gère désormais
lui aussi le 503 comme « réessayer avec le même batch_id », avec un
nombre borné de tentatives et un backoff — pour un usage ponctuel en ligne
de commande, pas pour une boucle de fond infinie. Ce module (`desktop_client`)
reste nécessaire pour la boucle automatique du poste desktop : il ajoute la
persistance du lot en attente entre deux cycles de 30 s
(`sync_outbox.json`) et ne s'arrête jamais après N tentatives (la boucle
externe `run_sync_forever` rejoue indéfiniment), ce que `sync_now.py` ne
fait volontairement pas (un outil en ligne de commande doit se terminer).
"""

import json
import logging
import random
import time
import uuid
from pathlib import Path

import requests

POLL_INTERVAL_SECONDS = 30
PUSH_TIMEOUT = 60
PULL_TIMEOUT = 30

# État exposé localement pour le bandeau frontend (SYNC.md §9), lu par
# `sync.desktop_status.LocalSyncStatusView` (authentification JWT humaine
# classique, PAS un jeton de nœud — ce n'est pas la même route que
# `/api/sync/status/`, qui reste côté Cloud et authentifiée par
# `NodeTokenAuthentication`).
_STATE = {
    'connection': 'OFFLINE',  # ONLINE | OFFLINE | SYNC_ERROR
    'last_push_at': None,
    'last_pull_at': None,
    'pending_count': 0,
    'last_error': None,
}


def get_local_sync_state() -> dict:
    return dict(_STATE)


def _outbox_path(data_dir: str) -> Path:
    return Path(data_dir) / 'sync_outbox.json'


def _load_pending_batch(data_dir: str, node_code: str):
    path = _outbox_path(data_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return None
    if data.get('node_code') != node_code:
        return None
    return data


def _save_pending_batch(data_dir: str, payload: dict) -> None:
    _outbox_path(data_dir).write_text(json.dumps(payload), encoding='utf-8')


def _clear_pending_batch(data_dir: str) -> None:
    path = _outbox_path(data_dir)
    if path.exists():
        path.unlink()


def run_sync_cycle(logger: logging.Logger, data_dir: str, node_code: str, cloud_url: str, node_token: str) -> None:
    """Un cycle push (+ pull si le push réussit). Ne lève jamais d'exception
    vers l'appelant : toute erreur est journalisée et reflétée dans
    `_STATE`, pour ne jamais interrompre la boucle de fond ni Waitress."""
    from sync.management.commands.sync_now import (
        TRANSIENT_STATUS_CODES,
        apply_pull_response,
        apply_push_response,
        build_outbound_payload,
    )

    headers = {'Authorization': f'Bearer {node_token}'}

    payload = _load_pending_batch(data_dir, node_code)
    if payload is None:
        payload = build_outbound_payload(node_code)
        pending_total = sum(len(v) for v in payload['records'].values())
        if pending_total == 0:
            _STATE['pending_count'] = 0
            _pull_only(logger, cloud_url, headers, data_dir, node_code)
            return
        _save_pending_batch(data_dir, payload)

    _STATE['pending_count'] = sum(len(v) for v in payload['records'].values())

    try:
        response = requests.post(f'{cloud_url}/api/sync/push/', json=payload, headers=headers, timeout=PUSH_TIMEOUT)
    except requests.RequestException as exc:
        logger.warning('Synchronisation : coupure réseau au push (%s) — même lot rejoué au prochain cycle.', exc)
        _STATE['connection'] = 'OFFLINE'
        _STATE['last_error'] = str(exc)
        return

    if response.status_code in TRANSIENT_STATUS_CODES:
        # BUG-067 : échec transitoire, aucun SyncBatchLog persisté côté
        # Cloud — le lot (même batch_id) est conservé pour le prochain cycle.
        logger.warning('Synchronisation : 503 transitoire du Cloud au push — même lot réessayé plus tard.')
        _STATE['connection'] = 'SYNC_ERROR'
        _STATE['last_error'] = 'Service cloud temporairement indisponible (503) — nouvel essai programmé.'
        return

    if response.status_code in (401, 403):
        logger.error('Synchronisation : jeton de nœud rejeté (%s) — mode dégradé jusqu\'à nouveau jeton.', response.status_code)
        _STATE['connection'] = 'SYNC_ERROR'
        _STATE['last_error'] = f'Authentification refusée ({response.status_code}) — jeton de nœud invalide ou révoqué.'
        # Le lot reste en attente (même batch_id) : un jeton invalide ne
        # rend pas le contenu du lot invalide, voir SYNC.md §8 (révocation).
        return

    if response.status_code >= 400:
        logger.error('Synchronisation : push refusé définitivement (%s) : %s', response.status_code, response.text[:500])
        _STATE['connection'] = 'SYNC_ERROR'
        _STATE['last_error'] = f'Push refusé ({response.status_code}).'
        # Erreur définitive non liée à l'infrastructure (ex. 400 payload
        # malformé) : on abandonne ce batch_id précis pour éviter une boucle
        # infinie. Rien n'est marqué `is_synced=True` : un nouveau lot sera
        # reconstruit au prochain cycle à partir des enregistrements
        # toujours `is_synced=False` (upsert idempotent côté Cloud, SYNC.md
        # §3.3 — sans risque de doublon même si une partie avait déjà été
        # traitée avant le rejet global).
        _clear_pending_batch(data_dir)
        return

    apply_push_response(response.json())
    _clear_pending_batch(data_dir)
    _STATE['connection'] = 'ONLINE'
    _STATE['last_push_at'] = time.time()
    _STATE['last_error'] = None
    logger.info('Synchronisation : push accepté (batch %s).', response.json().get('batch_id'))

    _pull_only(logger, cloud_url, headers, data_dir, node_code)


_PULL_CURSOR_KEYS = ('since_config', 'since_client_debt', 'client_after_id', 'since_consumables')  # BUG-998 : after_id = pagination
# Curseur de pull en mémoire (repli quand aucun répertoire de données n'est
# fourni) ; indexé par URL du Cloud.
_PULL_CURSORS: dict = {}


def _cursor_path(data_dir: str) -> Path:
    return Path(data_dir) / 'sync_pull_cursor.json'


def _default_node_code() -> str:
    from django.conf import settings
    return getattr(settings, 'KIESE_NODE_CODE', '') or ''


def _valid_cursor_value(value) -> bool:
    """BUG-785 : un curseur doit être une date ISO 8601 lisible et non future
    (curseur futur = Cloud restauré / horloge déréglée : il masquerait tout)."""
    from datetime import datetime, timedelta, timezone as _tz

    if not isinstance(value, str) or not value or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_tz.utc)
        return parsed <= datetime.now(_tz.utc) + timedelta(minutes=5)
    except (ValueError, OverflowError, OSError):
        return False


def load_pull_cursor(data_dir, cloud_url: str, node_code=None) -> dict:
    """BUG-784 : curseur de pull (`since_config`, `since_client_debt`) du
    dernier pull appliqué, persisté sur disque pour survivre à un redémarrage.
    Vide (pull complet) si absent, illisible, émis pour un autre Cloud
    (BUG-784) ou un autre nœud (BUG-786), ou si une valeur n'est pas une date
    ISO valide non future (BUG-785)."""
    node_code = _default_node_code() if node_code is None else node_code
    entry = _PULL_CURSORS.get(cloud_url)
    if entry is None and data_dir:
        try:
            data = json.loads(_cursor_path(data_dir).read_text(encoding='utf-8'))
        except (ValueError, OSError):
            data = None
        if isinstance(data, dict) and data.get('cloud_url') == cloud_url:
            entry = {'node_code': data.get('node_code') if isinstance(data.get('node_code'), str) else '',
                     'cursor': {k: data[k] for k in _PULL_CURSOR_KEYS
                                if isinstance(data.get(k), str) and data[k]}}
    if not entry or entry['node_code'] != node_code:
        return {}
    out = {}
    for k, v in entry['cursor'].items():
        if k == 'client_after_id':  # BUG-998 : UUID de pagination, valable seulement avec since_client_debt
            try:
                uuid.UUID(v)
            except (TypeError, ValueError, AttributeError):
                continue
            out[k] = v
        elif _valid_cursor_value(v):
            out[k] = v
    if 'client_after_id' in out and 'since_client_debt' not in out:
        out.pop('client_after_id')
    return out


def save_pull_cursor(data_dir, cloud_url: str, response_data, node_code=None) -> None:
    if not isinstance(response_data, dict):
        return
    node_code = _default_node_code() if node_code is None else node_code
    cursor = {k: response_data[k] for k in _PULL_CURSOR_KEYS
              if isinstance(response_data.get(k), str) and response_data[k]}
    if not cursor:
        return
    _PULL_CURSORS[cloud_url] = {'node_code': node_code, 'cursor': cursor}
    if data_dir:
        try:
            _cursor_path(data_dir).write_text(
                json.dumps({'cloud_url': cloud_url, 'node_code': node_code, **cursor}), encoding='utf-8')
        except OSError:
            pass  # curseur en mémoire conservé ; au pire un pull complet au redémarrage


def _pull_only(logger: logging.Logger, cloud_url: str, headers: dict, data_dir=None, node_code=None) -> None:
    """BUG-998 : boucle de pull tant que le cloud annonce `has_more` (bornée)."""
    for _ in range(_PULL_MAX_PAGES):
        data = _pull_page(logger, cloud_url, headers, data_dir, node_code)
        if not (isinstance(data, dict) and data.get('has_more') is True):
            return None


_PULL_MAX_PAGES = 200


def _pull_page(logger: logging.Logger, cloud_url: str, headers: dict, data_dir=None, node_code=None):
    from sync.management.commands.sync_now import TRANSIENT_STATUS_CODES, apply_pull_response

    try:
        response = requests.get(
            f'{cloud_url}/api/sync/pull/', headers=headers, timeout=PULL_TIMEOUT,
            params=load_pull_cursor(data_dir, cloud_url, node_code),
        )
    except requests.RequestException as exc:
        logger.warning('Synchronisation : coupure réseau au pull (%s).', exc)
        _STATE['connection'] = 'OFFLINE'
        _STATE['last_error'] = str(exc)
        return None

    if response.status_code in TRANSIENT_STATUS_CODES:
        logger.warning('Synchronisation : 503 transitoire au pull — nouvel essai au prochain cycle.')
        _STATE['connection'] = 'SYNC_ERROR'
        _STATE['last_error'] = 'Service cloud temporairement indisponible (503) au pull.'
        return None

    if response.status_code == 400 and 'Paramètre' in (getattr(response, 'text', '') or ''):
        # BUG-785 : le Cloud refuse le curseur lui-même : on l'oublie, le
        # prochain cycle fera un pull complet au lieu de rejouer le 400.
        _PULL_CURSORS.pop(cloud_url, None)
        if data_dir:
            try:
                _cursor_path(data_dir).unlink()
            except OSError:
                pass

    if response.status_code >= 400:
        logger.error('Synchronisation : pull refusé (%s).', response.status_code)
        _STATE['connection'] = 'SYNC_ERROR'
        _STATE['last_error'] = f'Pull refusé ({response.status_code}).'
        return None

    data = response.json()
    apply_pull_response(data)
    # Le curseur n'avance qu'une fois la descente appliquée.
    save_pull_cursor(data_dir, cloud_url, data, node_code)
    _STATE['connection'] = 'ONLINE'
    _STATE['last_pull_at'] = time.time()
    _STATE['last_error'] = None
    return data


def run_sync_forever(logger: logging.Logger) -> None:
    from django.conf import settings

    data_dir = getattr(settings, 'KIESE_DATA_DIR', None)
    node_code = getattr(settings, 'KIESE_NODE_CODE', '')
    cloud_url = (getattr(settings, 'KIESE_CLOUD_URL', '') or '').rstrip('/')
    node_token = getattr(settings, 'KIESE_NODE_TOKEN', '')

    if not (data_dir and node_code and cloud_url and node_token):
        logger.info('Service de synchronisation inactif (configuration incomplète — mode hors-ligne volontaire).')
        return

    logger.info('Service de synchronisation démarré pour le nœud %s (%s).', node_code, cloud_url)
    while True:
        try:
            run_sync_cycle(logger, data_dir, node_code, cloud_url, node_token)
        except Exception:  # noqa: BLE001 - ne jamais tuer la boucle de fond
            logger.exception('Synchronisation : erreur inattendue dans le cycle, ignorée.')
        # Un peu d'aléa pour éviter que plusieurs postes ne cognent le Cloud
        # à la même seconde exacte.
        time.sleep(POLL_INTERVAL_SECONDS + random.uniform(0, 3))
