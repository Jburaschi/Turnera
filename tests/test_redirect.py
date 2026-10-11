import re, os
from datetime import datetime
from app import create_app
from app.extensions import limiter, db
from app.models import *
from app.blueprints.auth import safe_next_url
from app.timeutils import utc_to_ar
app=create_app(); limiter.enabled=False
res=[]
def ok(n,c): res.append(c); print(('PASS ' if c else 'FAIL ')+n)
fb='/pepito'
for bad in ['https://evil.com','//evil.com','/\\evil.com','\\\\evil.com','javascript:alert(1)','http:/evil.com','\t//evil.com',' //evil.com','evil.com','/\n/evil.com']:
    ok(f'rechaza {bad!r}', safe_next_url(bad, fb)==fb)
for good in ['/pepito/booking','/pepito/mis-turnos','/pepito/booking?x=1']:
    ok(f'acepta {good!r}', safe_next_url(good, fb)==good)
c=app.test_client()
def login(nxt):
    h=c.get('/pepito/customer/login').get_data(as_text=True); t=re.search(r'name="csrf_token" value="([^"]+)"',h).group(1)
    return c.post(f'/pepito/customer/login?next={nxt}',data={'email':'lucia@demo.com','password':'cliente123','csrf_token':t}).headers.get('Location')
ok('login con next externo va a la página del negocio', login('https://evil.com')=='/pepito')
c.get('/logout')
ok('login con next interno respeta el destino', login('/pepito/booking')=='/pepito/booking')
ok('filtro hora_ar: 15:00 UTC -> 12:00 AR', utc_to_ar(datetime(2026,9,26,15,0))==datetime(2026,9,26,12,0))
# pantallas tocadas
a=app.test_client(); h=a.get('/admin/login').get_data(as_text=True); t=re.search(r'name="csrf_token" value="([^"]+)"',h).group(1)
a.post('/admin/login',data={'email':'admin@pepito.com','password':'admin123','csrf_token':t})
with app.app_context():
    ap=Appointment.query.first(); apid=ap.id
    from app.services import audit; audit.log_created(ap,'x'); db.session.commit()
    co=Company.query.first(); co.plan_name='PREMIUM'; co.plan_status='TRIAL'; from datetime import timedelta; co.trial_expires_at=datetime.utcnow()+timedelta(days=5); db.session.commit()
ok('historial de turno', a.get(f'/admin/pepito/appointments/{apid}/log').status_code==200)
ok('panel con trial', a.get('/admin/pepito').status_code==200)
ok('booking ya no muestra el aviso de zona horaria', 'zona horaria' not in app.test_client().get('/pepito/booking').get_data(as_text=True))
# onboarding negocio sin selector
o=app.test_client(); h=o.get('/registrar').get_data(as_text=True); t=re.search(r'name="csrf_token" value="([^"]+)"',h).group(1)
o.post('/registrar',data={'full_name':'Ana','email':'ana@x.com','password':'12345678','terms':'on','csrf_token':t})
h=o.get('/registrar/negocio').get_data(as_text=True)
ok('alta guiada sin selector de zona horaria', 'name="timezone"' not in h)
r=o.post('/registrar/negocio',data={'name':'Peluquería Ana','category':'Peluquerías','csrf_token':t,'timezone':'America/Mexico_City'})
with app.app_context(): ok('negocio nuevo queda en hora Argentina', Company.query.filter_by(name='Peluquería Ana').first().timezone=='America/Argentina/Buenos_Aires')
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
c2=app.test_client(); h=c2.get('/pepito/customer/login').get_data(as_text=True); t=re.search(r'name="csrf_token" value="([^"]+)"',h).group(1)
loc=c2.post('/pepito/customer/login?next=/%0d%0aLocation:%20https://evil.com',data={'email':'lucia@demo.com','password':'cliente123','csrf_token':t}).headers.get('Location')
print(('PASS' if loc=='/pepito' else 'FAIL')+f' next con salto de línea codificado por URL -> {loc}')
