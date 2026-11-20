from core.models import Node, User
from clients.models import Client
N={n.code:n for n in Node.objects.all()}
o,_=User.objects.get_or_create(username='zz_demo_facturier_k2b',defaults=dict(role='FACTURIER',node=N['K2'],team='B'))
o.role='FACTURIER';o.node=N['K2'];o.team='B';o.is_active=True;o.must_change_password=False;o.set_password('zz_demo_facturier_k2b');o.save()
for code,ln in [('K2-0950','Cloture A'),('K2-0951','Cloture B')]:
    Client.objects.get_or_create(code=code,defaults=dict(first_name='ZZREG',last_name=ln,node=N['K2'],credit_limit=50000,commission_rate='0.25',current_debt=0,notes='ZZ e2e 2026-11-20'))
print('ok')
