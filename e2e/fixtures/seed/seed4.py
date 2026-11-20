import os
exec(open(os.path.join(os.environ['TEMP'],'api.py')).read())
def sale(u,code,prix,qte,paid,date='2026-11-05'):
    t=tok(u)
    cl=call('GET','/api/clients/clients/?search='+code,t=t)[1]['results'][0]['id']
    s,inv=call('POST','/api/sales/invoices/',{'client':cl,'payment_type':'CASH' if paid else 'CREDIT','payment_amount':str(paid),'lines':[{'bread_price':prix,'quantity':qte}],'invoice_date':date},t)
    print(code,s,inv if s!=201 else inv['id'])
    if s==201:
        print(' deliver',call('POST',f"/api/sales/invoices/{inv['id']}/deliver/",{'delivered_at':date},t)[0])
sale('zz_ventes_facturier','K1-0085',4,100,25000)
for i in range(1,5): sale('zz_clients_facturier',f'K4-096{i}',3,10,3000)
