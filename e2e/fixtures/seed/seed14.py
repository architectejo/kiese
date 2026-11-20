import os
exec(open(os.path.join(os.environ['TEMP'],'api.py')).read())
t=tok('zz_clients_facturier')
cl=call('GET','/api/clients/clients/?search=K4-0964',t=t)[1]['results'][0]['id']
print(call('POST','/api/sales/invoices/',{'client':cl,'payment_type':'CREDIT','payment_amount':'0','lines':[{'bread_price':3,'quantity':2}],'invoice_date':'2026-11-10'},t)[0])
