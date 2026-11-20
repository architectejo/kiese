from core.models import Node
from clients.models import Client
b2=Node.objects.get(code='B2')
print('cotisation B2', b2.monthly_social_contribution)
for s in ['POS','TAB','BUR']:
    for nm,debt in [('Retrait',0),('Epargne',-10000),('Plafond',50000),('Credit',0)]:
        Client.objects.get_or_create(node=b2,first_name='ZZE301',last_name=f'{nm}{s}',defaults=dict(credit_limit=50000,commission_rate='0.25',current_debt=debt,notes='ZZ e2e 2026-11-20'))
print(Client.objects.filter(first_name='ZZE301').count())
