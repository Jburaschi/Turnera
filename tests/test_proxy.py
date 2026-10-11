import os, re, sys, logging
from urllib.parse import unquote
os.environ.update(FLASK_ENV='production', SEED_DEMO='1', SECRET_KEY='x'*32, GOOGLE_CLIENT_ID='cid', GOOGLE_CLIENT_SECRET='sec')
import logging
boot=[]
class B(logging.Handler):
    def emit(self, r): boot.append(r.getMessage())
logging.getLogger('app').addHandler(B()); logging.getLogger('app').setLevel(logging.INFO)
from app import create_app
from app.extensions import db
from app.models import *
app=create_app(); app.config['SESSION_COOKIE_SECURE']=False
res=[]
def ok(n,c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ')+n)
logs=[]
class L(logging.Handler):
    def emit(self, r): logs.append(r.getMessage())
app.logger.addHandler(L()); app.logger.setLevel(logging.INFO)
PROXY={'X-Forwarded-Proto':'https','X-Forwarded-Host':'tu-app.railway.app','X-Forwarded-For':'1.1.1.1','Referer':'https://tu-app.railway.app/'}
def get(c,u,ip='1.1.1.1',**kw): return c.get(u,headers={**PROXY,'X-Forwarded-For':ip},**kw)
def post(c,u,ip='1.1.1.1',**kw): return c.post(u,headers={**PROXY,'X-Forwarded-For':ip},**kw)
def tok(c,u,ip='1.1.1.1'): return re.search(r'name="csrf_token" value="([^"]+)"',get(c,u,ip).get_data(as_text=True)).group(1)
print('modo:', 'TRUSTED_PROXIES='+os.getenv('TRUSTED_PROXIES','(default)'))
ok('aviso en el log si falta configurar el mail', any('MAIL_USERNAME no está configurado' in m for m in boot))
with app.app_context():
    co=Company.query.filter_by(slug='pepito').first(); co.plan_name='PRO'; co.plan_status='ACTIVE'; db.session.commit()
a=app.test_client(); t=tok(a,'/admin/login'); post(a,'/admin/login',data={'email':'admin@pepito.com','password':'admin123','csrf_token':t})
r=get(a,'/admin/pepito/integrations/google/connect'); loc=unquote(r.headers.get('Location',''))
ok('Conectar Google manda a Google con redirect_uri https', 'accounts.google.com' in loc and 'redirect_uri=https://tu-app.railway.app/admin/integrations/google/callback' in loc)
from google_auth_oauthlib.flow import Flow
seen=[]
real=Flow.fetch_token
def spy(self, **kw):
    seen.append(kw['authorization_response']); return real(self, **kw)
Flow.fetch_token=spy
with a.session_transaction() as ss: state=ss.get('google_oauth_state')
logs.clear()
r=get(a,f'/admin/integrations/google/callback?code=abc&state={state}',follow_redirects=True)
ok(f'la vuelta de Google llega como https ({(seen or ["(no llegó)"])[0][:45]}...)', seen and seen[0].startswith('https://tu-app.railway.app/'))
ok('ya no aparece InsecureTransportError (falla después, al canjear el código falso con Google)', not any('InsecureTransport' in m for m in logs) and 'No se pudo conectar Google Calendar' in r.get_data(as_text=True))
import traceback
c=app.test_client(); t=tok(c,'/pepito/booking'); logs.clear()
from datetime import date, timedelta, datetime
d=date.today()+timedelta(days=10)
while d.weekday()>4: d+=timedelta(days=1)
post(c,'/pepito/book',data=dict(service_id=2,employee_id=3,start_dt=datetime.combine(d,datetime.min.time()).replace(hour=10).isoformat(),guest_name='A',guest_phone='1',guest_email='a@x.com',csrf_token=t))
body=' '.join(logs)
ok('el link "gestionar turno" del mail sale con https', 'https://tu-app.railway.app/pepito/a/' in body)
c1=app.test_client(); t1=tok(c1,'/admin/login','2.2.2.2')
codes=[post(c1,'/admin/login','2.2.2.2',data={'email':'x@x.com','password':'mal','csrf_token':t1}).status_code for _ in range(11)]
ok(f'límite de intentos: la IP que se equivoca 11 veces queda bloqueada ({codes[-1]})', codes[-1]==429)
c2=app.test_client(); t2=tok(c2,'/admin/login','3.3.3.3')
r=post(c2,'/admin/login','3.3.3.3',data={'email':'admin@pepito.com','password':'admin123','csrf_token':t2})
ok(f'otro cliente (otra IP) puede entrar igual ({r.status_code})', r.status_code==302)
# segundo negocio: misma URL de retorno
with app.app_context():
    co2=Company(slug='otro',name='Otro',plan_name='PRO',plan_status='ACTIVE'); db.session.add(co2); db.session.flush()
    db.session.add(CompanyConfig(company_id=co2.id)); ad=AdminUser(company_id=co2.id,email='a@otro.com',name='A'); ad.set_password('clave1234'); db.session.add(ad); db.session.commit()
b=app.test_client(); t=tok(b,'/admin/login','4.4.4.4'); post(b,'/admin/login','4.4.4.4',data={'email':'a@otro.com','password':'clave1234','csrf_token':t})
loc2=unquote(get(b,'/admin/otro/integrations/google/connect','4.4.4.4').headers.get('Location',''))
ok('otro negocio usa la MISMA URL de retorno (una sola para registrar en Google)', 'redirect_uri=https://tu-app.railway.app/admin/integrations/google/callback' in loc2)
with b.session_transaction() as ss: st2=ss.get('google_oauth_state')
seen.clear(); r=get(b,f'/admin/integrations/google/callback?code=abc&state={st2}','4.4.4.4',follow_redirects=True)
ok('la vuelta de Google en el otro negocio termina en SU panel', seen and '/admin/otro' in r.request.path)
r=get(b,'/admin/integrations/google/callback?error=access_denied','4.4.4.4',follow_redirects=True)
ok('si el dueño cancela en Google, ve un aviso claro', 'Sesión OAuth inválida' in r.get_data(as_text=True) or 'Cancelaste' in r.get_data(as_text=True))
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
