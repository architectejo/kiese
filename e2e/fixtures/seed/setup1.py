from core.models import Node, User
from clients.models import Client
N={n.code:n for n in Node.objects.all()}
spec=[
 ('zz_demo_admin','ADMIN',None,''),('zz_demo_direction','DIRECTION',None,''),('zz_demo_comptable','COMPTABLE','K1',''),
 ('zz_demo_gerant_k1','GERANT','K1',''),('zz_demo_gerant_k2','GERANT','K2',''),
 ('zz_demo_facturier_k1','FACTURIER','K1','A'),('zz_demo_facturier_k2','FACTURIER','K2','A'),('zz_demo_livreur_k1','LIVREUR','K1','A'),
 ('zz_ventes_facturier','FACTURIER','K1','A'),
 ('zz_clients_gerant','GERANT','K4',''),('zz_clients_facturier','FACTURIER','K4','B'),('zz_clients_comptable','COMPTABLE','K4',''),
 ('zz_treso_facturier_a','FACTURIER','K4','A'),('zz_treso_livreur','LIVREUR','K4','A'),
 ('zz_direction','DIRECTION',None,''),('zz_comptable','COMPTABLE','K4',''),
 ('zz_facturier_k3','FACTURIER','K3','A'),('zz_prod_gerant_k3','GERANT','K3',''),('zz_prod_gerant_k4','GERANT','K4',''),
 ('zz_e301_fact','FACTURIER','B2','A'),('zz_e301_gerant','GERANT','B2',''),('zz_e301_dir','DIRECTION',None,''),
]
for u,role,node,team in spec:
    o,_=User.objects.get_or_create(username=u,defaults=dict(role=role,node=N.get(node) if node else None,team=team))
    o.role=role;o.node=N.get(node) if node else None;o.team=team;o.is_active=True;o.must_change_password=False
    o.set_password(u);o.save()
print(User.objects.filter(username__startswith='zz_').count())
