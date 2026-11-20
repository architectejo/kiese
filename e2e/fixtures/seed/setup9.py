import datetime
from core.models import Node, User, BreadPrice
from production.models import ProductionSession, BreadStock, BreadDisposal
N={n.code:n for n in Node.objects.all()}
g=User.objects.get(username='zz_demo_gerant_k2')
bp={b.unit_price:b for b in BreadPrice.objects.all()}
s,_=BreadStock.objects.get_or_create(node=N['K4'],bread_price=bp[500]); s.qty_produced=400; s.save()
sess=[]
for d in range(1,17):
    o,c=ProductionSession.objects.get_or_create(node=N['K2'],team='A',date=datetime.date(2026,11,d),defaults=dict(declared_by=g,flour_sacks_used=1,is_closed=True,notes='ZZ e2e seed KPI'))
    sess.append(o)
base=sess[0]
for t,q in [('DECLASSED',8),('FREE_DIST',12),('UNSOLD',3),('REMAINING',5)]:
    BreadDisposal.objects.get_or_create(node=N['K2'],session=base,bread_price=bp[500],disposal_type=t,defaults=dict(quantity=q,notes='ZZ e2e seed'))
print(ProductionSession.objects.filter(node=N['K2']).count(), BreadDisposal.objects.filter(node=N['K2']).count())
