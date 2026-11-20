from core.models import Node, User
from clients.models import Client
N={n.code:n for n in Node.objects.all()}
o,_=User.objects.get_or_create(username='zz_demo_facturier_b1b',defaults=dict(role='FACTURIER',node=N['B1'],team='B'))
o.role='FACTURIER';o.node=N['B1'];o.team='B';o.is_active=True;o.must_change_password=False;o.set_password('zz_demo_facturier_b1b');o.save()
for code,ln in [('B1-0950','Cloture A'),('B1-0951','Cloture B')]:
    Client.objects.get_or_create(code=code,defaults=dict(first_name='ZZREG',last_name=ln,node=N['B1'],credit_limit=50000,commission_rate='0.25',current_debt=0,notes='ZZ e2e 2026-11-20'))
print('ok')
