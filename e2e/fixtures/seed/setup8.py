from core.models import Node, User
from treasury.models import CashClosure
import datetime
k1=Node.objects.get(code='K1'); g=User.objects.get(username='zz_demo_gerant_k1')
c,created=CashClosure.objects.get_or_create(node=k1,date=datetime.date(2020,2,2),defaults=dict(gerant=g,total_entries=12345,net_cash=12345,physical_cash_total=12345,is_validated=True,notes='ZZ fixture e2e 2020-02-02'))
print(created,c.id)
