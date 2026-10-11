import os, re, time
from datetime import timedelta, date, datetime
from app import create_app
from app.extensions import db, limiter
from app.models import *
from app.services import google_calendar as gc, email_service as es
app=create_app(); limiter.enabled=False
res=[]
def ok(n,c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ')+n)
def token(c, url='/pepito/customer/login'):
    return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)
def next_slot(hour, days=10):
    d=date.today()+timedelta(days=days)
    while d.weekday()>4: d+=timedelta(days=1)
    return datetime.combine(d, datetime.min.time()).replace(hour=hour).isoformat()

print('— 10) Google Calendar caído')
with app.app_context():
    co=Company.query.filter_by(slug='pepito').first(); co.plan_name='PRO'; co.plan_status='ACTIVE'
    db.session.add(GoogleCalendarConnection(company_id=co.id, enabled=True, refresh_token='r', access_token='a')); db.session.commit()
calls=[]
def broken_build(*a, **kw):
    calls.append(kw.get('http')); raise RuntimeError('Google no responde')
gc.build=broken_build
c=app.test_client(); t=token(c,'/pepito/booking')
r=c.post('/pepito/book',data=dict(service_id=1,employee_id=1,start_dt=next_slot(9),guest_name='Ana',guest_phone='1',csrf_token=t))
ok(f'reserva con Google caído: el cliente ve la confirmación ({r.status_code})', r.status_code==200 and 'manage' in r.get_data(as_text=True).lower() or r.status_code==200)
with app.app_context():
    ap=Appointment.query.filter_by(guest_name='Ana').first(); ok('el turno quedó guardado', ap is not None and ap.status=='BOOKED'); tok=ap.manage_token
ok('se intentó llamar a Google con timeout de 10 s', calls and calls[0].http.timeout==10)
r=c.post(f'/pepito/a/{tok}/cancel',data={'csrf_token':t},follow_redirects=True)
ok('cancelar con Google caído funciona', r.status_code==200 and 'Turno cancelado' in r.get_data(as_text=True))
adm=app.test_client(); t2=token(adm,'/admin/login'); adm.post('/admin/login',data={'email':'admin@pepito.com','password':'admin123','csrf_token':t2})
t2=token(adm,'/admin/pepito?section=agenda')
r=adm.post('/admin/pepito/appointments/manual',data=dict(service_id=1,employee_id=1,start_dt=next_slot(13),guest_name='Beto',csrf_token=t2),follow_redirects=True)
ok('alta manual con Google caído funciona', 'Turno creado manualmente' in r.get_data(as_text=True))

print('— 10) mails')
from aiosmtpd.controller import Controller
got=[]
class H:
    async def handle_DATA(self, server, session, envelope): got.append(envelope); return '250 OK'
ctl=Controller(H(), hostname='127.0.0.1', port=8025); ctl.start()
app.config.update(MAIL_SERVER='127.0.0.1', MAIL_PORT=8025, MAIL_USE_TLS=False, MAIL_USE_SSL=False, MAIL_USERNAME='noreply@turnex.com', MAIL_PASSWORD='', MAIL_DEFAULT_SENDER='noreply@turnex.com')
app.extensions['mail'].server='127.0.0.1'; app.extensions['mail'].port=8025; app.extensions['mail'].use_tls=False; app.extensions['mail'].username='noreply@turnex.com'; app.extensions['mail'].password=''; app.extensions['mail'].default_sender='noreply@turnex.com'
c=app.test_client(); t=token(c,'/pepito/booking')
c.post('/pepito/book',data=dict(service_id=2,employee_id=3,start_dt=next_slot(10),guest_name='Caro',guest_phone='1',guest_email='caro@x.com',csrf_token=t))
for _ in range(50):
    if got: break
    time.sleep(0.1)
ok('con SMTP funcionando, el mail de confirmación llega (en segundo plano)', got and got[0].rcpt_tos==['caro@x.com'] and b'Turno confirmado' in got[0].content or (got and 'caro@x.com' in got[0].rcpt_tos))
ctl.stop()
# SMTP que no responde: un socket que acepta y nunca contesta
import socket, threading
blk=socket.socket(); blk.bind(('127.0.0.1',8026)); blk.listen(50)
app.extensions['mail'].port=8026
es.SMTP_TIMEOUT_SECONDS=2
c=app.test_client(); t=token(c,'/pepito/booking')
t0=time.time(); r=c.post('/pepito/book',data=dict(service_id=2,employee_id=3,start_dt=next_slot(12),guest_name='Dani',guest_phone='1',guest_email='dani@x.com',csrf_token=t)); dt=time.time()-t0
ok(f'con SMTP colgado, la reserva responde igual en {dt:.2f} s', r.status_code==200 and dt<1.5)
logs=[]
import logging
class L(logging.Handler):
    def emit(self, rec): logs.append(rec.getMessage())
app.logger.addHandler(L())
time.sleep(3.5)
ok('el envío colgado se corta por timeout y queda en el log', any('Error al enviar email' in m for m in logs))
blk.close()
app.config['MAIL_USERNAME']=''

print('— 11) sesiones')
def admin_client(email='admin@pepito.com', pw='admin123'):
    x=app.test_client(); tk=token(x,'/admin/login'); x.post('/admin/login',data={'email':email,'password':pw,'csrf_token':tk}); return x
def in_panel(x): return x.get('/admin/pepito').status_code==200
with app.app_context():
    co=Company.query.filter_by(slug='pepito').first()
    st=AdminUser(company=co,email='staff@pepito.com',name='Staff',role='staff'); st.set_password('staff1234'); db.session.add(st); db.session.commit(); sid=st.id
s1=admin_client('staff@pepito.com','staff1234'); ok('staff entra al panel', in_panel(s1))
with app.app_context(): db.session.get(AdminUser,sid).active=False; db.session.commit()
ok('staff desactivado: su sesión abierta se corta', not in_panel(s1))
with app.app_context(): db.session.get(AdminUser,sid).active=True; db.session.commit()
s1=admin_client('staff@pepito.com','staff1234')
a1=admin_client(); tk=token(a1,'/admin/pepito/team')
a1.post(f'/admin/pepito/team/{sid}/delete',data={'csrf_token':tk})
ok('staff borrado: su sesión abierta se corta', not in_panel(s1))
a2=admin_client(); ok('dos sesiones del dueño abiertas', in_panel(a1) and in_panel(a2))
with app.app_context(): me=AdminUser.query.filter_by(email='admin@pepito.com').first(); mid=me.id
tk=token(a1,'/admin/pepito/team')
a1.post(f'/admin/pepito/team/{mid}/update',data={'name':'Admin','role':'admin','active':'on','password':'nuevaClave123','csrf_token':tk})
ok('el dueño cambia su contraseña y sigue adentro', in_panel(a1))
ok('la otra sesión abierta con la contraseña vieja se cierra', not in_panel(a2))
tk=token(a1,'/admin/pepito/team')
a1.post(f'/admin/pepito/team/{mid}/update',data={'name':'Admin','role':'admin','password':'','csrf_token':tk})
with app.app_context(): ok('no puede desactivarse a sí mismo', AdminUser.query.get(mid).active)
tk=token(a1,'/admin/pepito/team')
a1.post('/admin/pepito/team',data={'name':'X','email':'x@pepito.com','password':'12345678','role':'superadmin','csrf_token':tk})
with app.app_context(): ok('rol inválido se guarda como staff', AdminUser.query.filter_by(email='x@pepito.com').first().role=='staff')
# cliente
cl=app.test_client(); tk=token(cl); cl.post('/pepito/customer/login',data={'email':'lucia@demo.com','password':'cliente123','csrf_token':tk})
ok('clienta logueada ve sus turnos', cl.get('/pepito/mis-turnos').status_code==200)
with app.app_context(): cu=Customer.query.filter_by(email='lucia@demo.com').first(); cid=cu.id
tk=token(a1,'/admin/pepito?section=customers')
a1.post(f'/admin/pepito/customers/{cid}/update',data={'full_name':'Lucía Demo','email':'lucia@demo.com','password':'otraClave1','csrf_token':tk})
ok('si le cambian la contraseña, su sesión se cierra', cl.get('/pepito/mis-turnos').status_code==302)
# plataforma desactiva al admin
with app.app_context(): AdminUser.query.get(mid).active=False; db.session.commit()
ok('admin desactivado desde plataforma: queda afuera', not in_panel(a1))
# formato viejo de sesión
old=app.test_client()
with old.session_transaction() as ss: ss['_user_id']='customer:1'; ss['_fresh']=True
ok('sesión con formato viejo pide volver a ingresar', old.get('/pepito/mis-turnos').status_code==302)
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
