import os
exec(open(os.path.join(os.environ['TEMP'],'api.py')).read())
def sale(u,code,prix,qte,paid,date):
    t=tok(u)
    cl=call('GET','/api/clients/clients/?search='+code,t=t)[1]['results'][0]['id']
    s,inv=call('POST','/api/sales/invoices/',{'client':cl,'payment_type':'CASH','payment_amount':str(paid),'lines':[{'bread_price':prix,'quantity':qte}],'invoice_date':date},t)
    print(code,s)
    if s==201: print(' deliver',call('POST',f"/api/sales/invoices/{inv['id']}/deliver/",{'delivered_at':date},t)[0])
for i in (1,2): sale('zz_clients_facturier',f'K4-096{i}',3,100,50000,'2026-11-06')
t=tok('zz_direction')
print(call('POST','/api/commissions/periods/generate/',{'node':7,'month':11,'year':2026},t)[0])
