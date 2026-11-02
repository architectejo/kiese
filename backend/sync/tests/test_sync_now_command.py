"""
Tests de `python manage.py sync_now` (usage manuel en ligne de commande) —
BUG-067 / BUG-072 (docs/qa/REGISTRE_BUGS.md).

Avant cette correction, un `503` transitoire de `/api/sync/push/` ou
`/api/sync/pull/` était traité exactement comme un `400`/`401`/`403` :
`CommandError` immédiate, et une relance manuelle régénérait un nouveau
`batch_id` (le lot original n'était jamais rejoué tel quel). Ces tests
reproduisent ce défaut (ils échouaient avant la correction) et vérifient le
comportement attendu désormais : même `batch_id` rejoué avec un nombre borné
de tentatives et un backoff, abandon propre si le Cloud reste indisponible,
et aucune régression sur les autres codes d'erreur (toujours fatals
immédiatement, sans retentative).
"""
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


def _response(status_code, json_data=None, text=''):
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    resp.json = Mock(return_value=json_data or {})
    return resp


class Sync503RetrySameBatchIdTests(TestCase):
    """BUG-067/BUG-072 : un 503 doit être rejoué avec le MÊME batch_id,
    jamais traité comme une erreur fatale identique à un 400/401/403."""

    def _call(self, **extra_options):
        out = StringIO()
        call_command(
            'sync_now',
            node_code='K1', cloud_url='https://cloud.example.test', node_token='tok-123',
            stdout=out, **extra_options,
        )
        return out.getvalue()

    @patch('sync.management.commands.sync_now.time.sleep')
    @patch('requests.get')
    @patch('requests.post')
    def test_a_transient_503_is_retried_with_the_exact_same_batch_id_then_succeeds(
        self, mock_post, mock_get, mock_sleep,
    ):
        mock_post.side_effect = [
            _response(503, text='Service de synchronisation temporairement indisponible'),
            _response(200, json_data={'batch_id': 'whatever', 'results': {}}),
        ]
        mock_get.return_value = _response(200, json_data={'clients': []})

        output = self._call(max_retries=3, retry_backoff=0.01)

        self.assertEqual(mock_post.call_count, 2)
        first_payload = mock_post.call_args_list[0].kwargs['json']
        second_payload = mock_post.call_args_list[1].kwargs['json']
        # Coeur du ticket : le batch_id n'est JAMAIS régénéré entre les deux
        # tentatives (contrairement au comportement avant correction, qui
        # reconstruisait un lot neuf à chaque appel de la commande).
        self.assertEqual(first_payload['batch_id'], second_payload['batch_id'])
        self.assertIn('Synchronisation terminée', output)
        mock_sleep.assert_called_once()

    @patch('sync.management.commands.sync_now.time.sleep')
    @patch('requests.get')
    @patch('requests.post')
    def test_persistent_503_gives_up_cleanly_after_bounded_retries_with_a_clear_message(
        self, mock_post, mock_get, mock_sleep,
    ):
        mock_post.return_value = _response(503, text='toujours indisponible')

        with self.assertRaises(CommandError) as ctx:
            self._call(max_retries=2, retry_backoff=0.01)

        # max_retries=2 => 1 essai initial + 2 retentatives = 3 appels, puis abandon.
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        message = str(ctx.exception)
        self.assertIn('503', message)
        self.assertIn('indisponible', message)
        # Le pull n'est jamais tenté : le push n'a jamais été confirmé.
        mock_get.assert_not_called()

    @patch('sync.management.commands.sync_now.time.sleep')
    @patch('requests.get')
    @patch('requests.post')
    def test_a_definitive_400_is_still_fatal_immediately_without_any_retry(
        self, mock_post, mock_get, mock_sleep,
    ):
        """Non-régression : les erreurs définitives (400/401/403/500...)
        restent traitées comme avant — aucune retentative, échec immédiat."""
        mock_post.return_value = _response(400, text='Lot malformé')

        with self.assertRaises(CommandError) as ctx:
            self._call(max_retries=5, retry_backoff=0.01)

        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()
        self.assertIn('400', str(ctx.exception))
        mock_get.assert_not_called()

    @patch('sync.management.commands.sync_now.time.sleep')
    @patch('requests.get')
    @patch('requests.post')
    def test_a_transient_503_on_pull_after_a_successful_push_is_also_retried_and_reported_clearly(
        self, mock_post, mock_get, mock_sleep,
    ):
        mock_post.return_value = _response(200, json_data={'batch_id': 'b1', 'results': {}})
        mock_get.return_value = _response(503, text='indisponible au pull')

        with self.assertRaises(CommandError) as ctx:
            self._call(max_retries=1, retry_backoff=0.01)

        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(mock_get.call_count, 2)  # 1 essai + 1 retentative
        self.assertIn('503', str(ctx.exception))
        self.assertIn('push', str(ctx.exception).lower())
