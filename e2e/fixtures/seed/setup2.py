from core.models import Node
from clients.models import Client
N={n.code:n for n in Node.objects.all()}
def mk(code,fn,ln,debt=0,node=None):
    node=node or code.split('-')[0]
    c,_=Client.objects.get_or_create(code=code,defaults=dict(first_name=fn,last_name=ln,node=N[node],credit_limit=50000,commission_rate='0.25',current_debt=debt,notes='ZZ e2e 2026-11-19'))
    c.current_debt=debt; c.save(); return c
mk('K1-0078','CrossNodeE2E','DEMO')
mk('K1-0079','DEMO','PlafondE2E',50000)
mk('K1-0080','ZZTEST','Ventes 3')
mk('K1-0081','ZZTEST','Ventes 4',50000)
mk('K1-0082','ZZTEST','Ventes 5')
mk('K1-0083','DEMO','RemboursementE2E',20000)
mk('K1-0084','ZZTEST','Ventes 7')
mk('K1-0085','ZZTEST','Ventes 8',-55000)
mk('K1-0086','ZZTEST','Ventes 9')
for i in range(3):
    mk(f'K4-09{i:02d}',f'ZZREG','CycleExact %d'%i)
    mk(f'K4-09{10+i}',f'ZZREG','CycleSous %d'%i)
mk('K4-0950','ZZREG','Cloture A'); mk('K4-0951','ZZREG','Cloture B')
for i in range(1,5): mk(f'K4-096{i}','ZZTEST','Clients %d'%i)
print(Client.objects.filter(notes__startswith='ZZ e2e').count())
