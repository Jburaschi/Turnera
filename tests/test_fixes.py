import re, os, sys
from datetime import datetime, timedelta, date
os.environ['CRON_SECRET']='sekret'
from app import create_app
from app.extensions import db
from app.models import *
app=create_app(); app.config['RATELIMIT_ENABLED']=False
from app.extensions import limiter; limiter.enabled=False
ok=lambda n,c: print(('PASS ' if c else 'FAIL ')+n) or (c or sys.exit(1))

def csrf_of(client, url):
    resp=client.get(url); html=resp.get_data(as_text=True)
    if resp.status_code!=200: print('DEBUG',url,resp.status_code,resp.headers.get('Location'))
    m=re.search(r'data-csrf="([^"]+)"',html) or re.search(r'name="csrf_token" value="([^"]+)"',html)
    return m.group(1)

# next weekday slot at 10:00 for María (service 1 Uñas 120min)
d=date.today()+timedelta(days=7)
while d.weekday()>4: d+=timedelta(days=1)
slot=datetime.combine(d,datetime.min.time()).replace(hour=14).isoformat()

# 1) takeover
with app.app_context():
    co=Company.query.filter_by(slug='pepito').first()
    cu=Customer(company=co,full_name='Vic',email='vic@x.com',needs_password_setup=True); cu.set_password('x'*20); db.session.add(cu); db.session.commit()
c=app.test_client(); t=csrf_of(c,'/pepito/customer/login')
r=c.post('/pepito/customer/login',data={'email':'vic@x.com','password':'atacante1','csrf_token':t})
ok('1 primer acceso no loguea', r.status_code==200 and 'te enviamos un email' in r.get_data(as_text=True))
ok('1 no quedó sesión', c.get('/pepito/mis-turnos').status_code==302)
with app.app_context():
    cu=Customer.query.filter_by(email='vic@x.com').first(); tok=cu.reset_token
    ok('1 se generó token de alta', bool(tok) and not cu.check_password('atacante1'))
t=csrf_of(c,f'/pepito/reset-password/{tok}')
r=c.post(f'/pepito/reset-password/{tok}',data={'password':'nueva123','confirm':'nueva123','csrf_token':t})
with app.app_context():
    cu=Customer.query.filter_by(email='vic@x.com').first()
    ok('1 el link crea la contraseña', cu.check_password('nueva123') and not cu.needs_password_setup)

# 2) hold-slot with csrf
b=app.test_client(); t=csrf_of(b,'/pepito/booking')
r=b.post('/pepito/hold-slot',data={'service_id':1,'employee_id':1,'start_dt':slot},headers={'X-CSRFToken':t})
ok(f'2 hold-slot con token -> {r.status_code}', r.status_code==200 and r.json['ok'])
r=b.post('/pepito/hold-slot',data={'service_id':1,'employee_id':1,'start_dt':slot})
ok('2 hold-slot sin token sigue rechazado', r.status_code==400)
b2=app.test_client(); t2=csrf_of(b2,'/pepito/booking')
r=b2.post('/pepito/hold-slot',data={'service_id':1,'employee_id':1,'start_dt':slot},headers={'X-CSRFToken':t2})
ok('2 otra sesión no puede tomar el horario retenido', r.status_code==409)
r=b.post('/pepito/release-hold',data=f'csrf_token={t}',content_type='application/x-www-form-urlencoded')
ok('2 release-hold (formato sendBeacon)', r.status_code==200)

# 3) double booking
form=dict(service_id=1,employee_id=1,start_dt=slot,guest_name='A',guest_phone='1')
r=b.post('/pepito/book',data={**form,'csrf_token':t}); ok('3 primera reserva', r.status_code==200)
r=b2.post('/pepito/book',data={**form,'csrf_token':t2}); ok('3 segunda reserva mismo horario rechazada', r.status_code==302)
with app.app_context():
    n=Appointment.query.filter_by(employee_id=1,start_dt=datetime.fromisoformat(slot),status='BOOKED').count(); ok(f'3 un solo turno en base ({n})', n==1)
    from sqlalchemy.exc import IntegrityError
    a=Appointment.query.filter_by(employee_id=1,start_dt=datetime.fromisoformat(slot)).first()
    db.session.add(Appointment(company_id=a.company_id,service_id=a.service_id,employee_id=1,start_dt=a.start_dt,end_dt=a.end_dt,status='BOOKED'))
    try: db.session.commit(); ok('3 índice único bloquea duplicado',False)
    except IntegrityError: db.session.rollback(); ok('3 índice único bloquea duplicado',True)
    db.session.add(Appointment(company_id=a.company_id,service_id=a.service_id,employee_id=1,start_dt=a.start_dt,end_dt=a.end_dt,status='CANCELED')); db.session.commit()
    ok('3 cancelados en el mismo horario sí se permiten', True)
    canceled_id=Appointment.query.filter_by(status='CANCELED',start_dt=a.start_dt).first().id
# admin reactivate canceled over booked
adm=app.test_client(); t=csrf_of(adm,'/admin/login')
adm.post('/admin/login',data={'email':'admin@pepito.com','password':'admin123','csrf_token':t})
t=csrf_of(adm,'/admin/pepito?section=agenda')
r=adm.post(f'/admin/pepito/appointments/{canceled_id}/status',data={'status':'BOOKED','csrf_token':t},follow_redirects=True)
ok('3 panel no reactiva turno encima de otro', 'No se puede reactivar' in r.get_data(as_text=True))
r=adm.post('/admin/pepito/appointments/manual',data={'service_id':1,'employee_id':1,'start_dt':slot,'guest_name':'Z','csrf_token':t},follow_redirects=True)
ok('3 alta manual en horario ocupado rechazada', 'no está disponible' in r.get_data(as_text=True))

# 4) cron
r=app.test_client().post('/internal/cron/reminders?token=sekret'); ok(f'4 cron POST -> {r.status_code}', r.status_code==200)
r=app.test_client().post('/internal/cron/reminders',headers={'X-Cron-Token':'sekret'}); ok('4 cron por cabecera', r.status_code==200)
r=app.test_client().post('/internal/cron/reminders?token=mal'); ok('4 cron token incorrecto 403', r.status_code==403)

# 5) onboarding
with app.app_context():
    co=Company.query.filter_by(slug='pepito').first()
    st=AdminUser(company=co,email='staff@pepito.com',name='Staff',role='staff'); st.set_password('staff1234'); db.session.add(st)
    co.onboarding_step=4; db.session.commit()
s=app.test_client(); t=csrf_of(s,'/admin/login')
s.post('/admin/login',data={'email':'staff@pepito.com','password':'staff1234','csrf_token':t})
r=s.post('/registrar/servicios',data={'service_name[]':['X'],'service_duration[]':['30'],'service_price[]':['1'],'row_token[]':['a'],'csrf_token':t})
ok(f'5 staff bloqueado en asistente -> {r.status_code} {r.headers.get("Location")}', r.status_code==302 and '/admin/pepito' in r.headers['Location'])
with app.app_context(): ok('5 servicios intactos', Service.query.filter_by(company_id=1,active=True).count()==3)
# owner, step 4 (not published): services with appointments get hidden, not deleted
t=csrf_of(adm,'/admin/pepito?section=agenda')
r=adm.post('/registrar/servicios',data={'service_name[]':['Nuevo'],'service_duration[]':['30'],'service_price[]':['1'],'row_token[]':['a'],'csrf_token':t})
with app.app_context():
    ok('5 servicios con turnos se ocultan, no se borran', Service.query.get(1) is not None and not Service.query.get(1).active and Appointment.query.filter_by(service_id=1).count()>0)
    co=Company.query.filter_by(slug='pepito').first(); co.onboarding_step=6; db.session.commit()
r=adm.get('/registrar/servicios'); ok('5 publicado: asistente cerrado', r.status_code==302 and '/admin/pepito' in r.headers['Location'])
r=adm.get('/registrar/listo'); ok('5 pantalla final accesible', r.status_code==200)

# smoke
for u in ['/','/pepito','/pepito/booking','/admin/pepito','/admin/pepito?section=agenda','/admin/pepito?section=customers','/admin/pepito/team']:
    ok(f'smoke {u}', adm.get(u).status_code==200)
print('TODO OK')
