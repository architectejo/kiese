"""Lanceur de tests qui stabilise l'horloge entre 00:00 et 12:00 (heure locale).

Depuis la décision du client Q-018 (journée comptable de midi à midi), un test qui
fabrique ses données avec `date.today()` voit « aujourd'hui » devenir la veille
tant qu'il est avant l'heure de clôture. Avec KIESE_TEST_CLOCK_SHIFT=1, si
l'heure locale est avant 13:00, `timezone.now()` est décalé à 13:00 du même jour
(l'horloge continue d'avancer). Aucun effet sur l'application : tests seulement.
"""
import os
import time
from datetime import datetime, timedelta
from unittest import mock

from django.test.runner import DiscoverRunner
from django.utils import timezone


class ClockShiftRunner(DiscoverRunner):
    def run_tests(self, *args, **kwargs):
        if os.environ.get('KIESE_TEST_CLOCK_SHIFT') != '1':
            return super().run_tests(*args, **kwargs)
        real_now = timezone.now
        local = timezone.localtime(real_now())
        if local.hour >= 13:
            return super().run_tests(*args, **kwargs)
        target = local.replace(hour=13, minute=0, second=0, microsecond=0)
        delta = target - local
        # Les modules de migration référencent `django.utils.timezone.now` (default=...)
        # au chargement : on les importe AVANT de remplacer la fonction, sinon
        # `makemigrations --check` voit un « changement » (autre objet fonction).
        from django.db.migrations.loader import MigrationLoader
        MigrationLoader(None, ignore_no_migrations=True)
        real_time = time.time
        offset = delta.total_seconds()
        # `time.time` suit aussi le décalage : le poste desktop compare `Node.last_sync`
        # (écrit via timezone.now) à `time.time()` ; sans cela il verrait un instant futur.
        with mock.patch.object(timezone, 'now', lambda: real_now() + delta), \
                mock.patch.object(time, 'time', lambda: real_time() + offset):
            return super().run_tests(*args, **kwargs)
