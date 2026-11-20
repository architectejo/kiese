from core.models import Node, User
N={n.code:n for n in Node.objects.all()}
for u,node in [('zz_demo_gerant_k5','K5'),('zz_demo_gerant_b1','B1')]:
    o,_=User.objects.get_or_create(username=u,defaults=dict(role='GERANT',node=N[node],team=''))
    o.role='GERANT';o.node=N[node];o.is_active=True;o.must_change_password=False;o.set_password(u);o.save()
print('ok')
