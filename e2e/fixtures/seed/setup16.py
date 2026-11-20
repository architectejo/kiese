from core.models import Node, User
from clients.models import Client
N={n.code:n for n in Node.objects.all()}
for u,node,team in [('zz_demo_facturier_k5a','K5','A'),('zz_demo_facturier_k5b','K5','B'),('zz_demo_facturier_k6a','K6','A')]:
    o,_=User.objects.get_or_create(username=u,defaults=dict(role='FACTURIER',node=N[node],team=team))
    o.role='FACTURIER';o.node=N[node];o.team=team;o.is_active=True;o.must_change_password=False;o.set_password(u);o.save()
for code,ln in [('K5-0950','Cloture A'),('K5-0951','Cloture B'),('K6-0950','Cloture A'),('K6-0951','Cloture B')]:
    Client.objects.get_or_create(code=code,defaults=dict(first_name='ZZREG',last_name=ln,node=N[code[:2]],credit_limit=50000,commission_rate='0.25',current_debt=0,notes='ZZ e2e 2026-11-20'))
print('ok')
