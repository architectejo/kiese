from core.models import Node, BreadPrice
from production.models import BreadStock
for code in ['K5']:
    n=Node.objects.get(code=code)
    for bp in BreadPrice.objects.filter(is_active=True):
        s,c=BreadStock.objects.get_or_create(node=n,bread_price=bp)
        if s.qty_produced<20: s.qty_produced=20; s.save()
print(BreadStock.objects.filter(node__code__in=['B1','K2']).count())
