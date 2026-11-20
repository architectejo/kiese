import datetime
from core.models import Node, User, BreadPrice
from production.models import ProductionSession, ProductionSessionLine, DailyBreadStockSnapshot
k6=Node.objects.get(code='K6'); g=User.objects.get(username='zz_e307_ger6')
bp={b.unit_price:b for b in BreadPrice.objects.all()}
today=datetime.date.today(); yest=today-datetime.timedelta(days=1)
DailyBreadStockSnapshot.objects.get_or_create(node=k6,bread_price=bp[500],date=yest,team='A',defaults=dict(qty_at_close=7))
s,c=ProductionSession.objects.get_or_create(node=k6,team='B',date=today,defaults=dict(declared_by=g,flour_sacks_used=1,notes='ZZE307 dup',breads_300=4,breads_500=10,total_breads=14,total_fc_produced=6200,is_closed=True))
if c:
    ProductionSessionLine.objects.create(session=s,bread_price=bp[500],quantity=10,source='DECLARED')
    ProductionSessionLine.objects.create(session=s,bread_price=bp[500],quantity=5,source='CARRYOVER')
    ProductionSessionLine.objects.create(session=s,bread_price=bp[300],quantity=4,source='DECLARED')
print(c,s.id,s.total_fc_produced,s.total_breads)
