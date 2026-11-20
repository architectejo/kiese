from core.models import Node, User
N={n.code:n for n in Node.objects.all()}
spec=[('zz_e307_dir','DIRECTION',None,''),('zz_e307_adm','ADMIN',None,''),
('zz_e307_ger6','GERANT','K6',''),('zz_e307_fac6','FACTURIER','K6','B'),('zz_e307_liv6','LIVREUR','K6','B'),
('zz_e307_ger5','GERANT','K5',''),('zz_e307_fac5','FACTURIER','K5','A'),
('zz_e307_ger1','GERANT','K1',''),('zz_e307_fac1','FACTURIER','K1','B'),
('zz_e307_ger3','GERANT','K3',''),('zz_e307_fac3','FACTURIER','K3','A'),
('zz_e307_flo_pos','LIVREUR','K6','A'),('zz_e307_flo_tab','LIVREUR','K6','A'),('zz_e307_flo_bur','LIVREUR','K6','A')]
for u,role,node,team in spec:
    o,_=User.objects.get_or_create(username=u,defaults=dict(role=role,node=N.get(node) if node else None,team=team))
    o.role=role;o.node=N.get(node) if node else None;o.team=team;o.is_active=True;o.must_change_password=False
    o.set_password(u);o.save()
print(User.objects.filter(username__startswith='zz_e307').count())
