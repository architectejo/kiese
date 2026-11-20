from core.models import Node, User, BreadPrice
from clients.models import Client
from production.models import BreadStock
N={n.code:n for n in Node.objects.all()}
for u,node,role,team in [('zz_demo_livreur_k2','K2','LIVREUR','A'),('zz_demo_facturier_b1','B1','FACTURIER','A'),('zz_demo_livreur_b1','B1','LIVREUR','A')]:
    o,_=User.objects.get_or_create(username=u,defaults=dict(role=role,node=N[node],team=team))
    o.role=role;o.node=N[node];o.team=team;o.is_active=True;o.must_change_password=False;o.set_password(u);o.save()
for node in ['K2','B1']:
    for i in list(range(3))+list(range(10,13)):
        c,_=Client.objects.get_or_create(code=f'{node}-09{i:02d}',defaults=dict(first_name='ZZREG',last_name=f'Cycle19 {i}',node=N[node],credit_limit=50000,commission_rate='0.25',current_debt=0,notes='ZZ e2e 2026-11-20'))
        c.refresh_category(); c.save(update_fields=['category'])
    s,_=BreadStock.objects.get_or_create(node=N[node],bread_price=BreadPrice.objects.get(unit_price=500))
    s.qty_produced=3000; s.save()
print('ok')
