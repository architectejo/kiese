import json,urllib.request,urllib.error
B='http://localhost:8000'
def call(m,p,d=None,t=None):
    r=urllib.request.Request(B+p,method=m,data=json.dumps(d).encode() if d is not None else None,headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+t} if t else {})})
    try:
        x=urllib.request.urlopen(r); return x.status,json.loads(x.read() or b'null')
    except urllib.error.HTTPError as e: return e.code,e.read().decode()[:300]
def tok(u): return call('POST','/api/core/auth/login/',{'username':u,'password':u})[1]['access']
