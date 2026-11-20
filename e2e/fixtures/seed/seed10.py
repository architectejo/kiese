import os
exec(open(os.path.join(os.environ['TEMP'],'api.py')).read())
tk2=tok('zz_demo_gerant_k2'); tk4=tok('zz_prod_gerant_k4')
for i in range(4):
    s,t=call('POST','/api/production/transfers/',{'from_node':7,'lines':[{'bread_price':3,'quantity_sent':10}]},tk2)
    print('req',s, t if s!=201 else t['id'])
    if s!=201: continue
    print(' resp',call('POST',f"/api/production/transfers/{t['id']}/respond_to_request/",{'approved':True,'lines':[{'bread_price':3,'quantity_sent':10}]},tk4)[0])
    r=call('POST',f"/api/production/transfers/{t['id']}/confirm_reception/",{'lines':[{'bread_price':3,'quantity_received':8}]},tk2)
    print(' conf',r[0], str(r[1])[:200])
