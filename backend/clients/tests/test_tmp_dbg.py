from clients.tests.test_clients_v8 import *
class Dbg(Journal):
    def test_dbg(self):
        ids = set(ActivityLog.objects.values_list('pk', flat=True))
        api(self.g1).patch(f'{CL}{self.c1.pk}/', {'credit_limit': '80000'}, format='json')
        api(self.g1).post(f'{CONTRIB}{self.contrib.pk}/toggle_paid/')
        for a in ActivityLog.objects.exclude(pk__in=ids):
            print('LOG>>', a.action, '|', a.description[:100])
