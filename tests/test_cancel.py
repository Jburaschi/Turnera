import os, re
from datetime import timedelta
from app import create_app
from app.extensions import db, limiter
from app.models import *
from app.timeutils import now_ar
app=create_app(); limiter.enabled=False
res=[]
def ok(n,c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ')+n)
def setcfg(limit, pen, amount):
    with app.app_context():
        co=Company.query.filter_by(slug='pepito').first(); co.cancelation_limit_hours=limit; co.cancelation_penalty_enabled=pen; co.cancelation_penalty_amount=amount; db.session.commit()
CNT=[0]
def mk(hours):
    CNT[0]+=1
    with app.app_context():
        co=Company.query.filter_by(slug='pepito').first(); e=Employee.query.filter_by(name='Juan').first(); s=Service.query.filter_by(name='Pelo').first()
        st=(now_ar()+timedelta(hours=hours, minutes=CNT[0])).replace(second=0,microsecond=0)
        a=Appointment(company=co,service=s,employee=e,start_dt=st,end_dt=st+timedelta(minutes=60),status='BOOKED',guest_name='T',guest_email='t@x.com',manage_token=os.urandom(8).hex())
        db.session.add(a); db.session.commit(); return a.manage_token, a.id
def page(tok):
    return app.test_client().get(f'/pepito/a/{tok}').get_data(as_text=True)
def post(tok, action, data=None):
    c=app.test_client(); h=c.get('/pepito/customer/login').get_data(as_text=True); t=re.search(r'name="csrf_token" value="([^"]+)"',h).group(1)
    return c.post(f'/pepito/a/{tok}/{action}',data={'csrf_token':t,**(data or {})},follow_redirects=True).get_data(as_text=True)
def ap(i):
    with app.app_context(): return db.session.get(Appointment,i).__dict__.copy()

print('— A) límite 24 h, sin penalidad')
setcfg(24, False, 0)
tok,i=mk(48); h=page(tok)
ok('turno en 48 h: muestra hasta cuándo se puede cambiar sin cargo', 'sin cargo hasta' in h and 'Reprogramar' in h and 'Cancelar turno' in h)
r=post(tok,'cancel'); a=ap(i)
ok('turno en 48 h: cancela sin penalidad', a['status']=='CANCELED' and not a['penalty_applied'] and a['payment_status'] is None)
tok,i=mk(5); h=page(tok)
ok('turno en 5 h: explica que ya no se puede y no muestra botones', 'ya no se puede cancelar ni reprogramar online' in h and 'Cancelar turno</button>' not in h and 'name="start_dt"' not in h)
ok('turno en 5 h: muestra teléfono del negocio', '5555-1234' in h)
r=post(tok,'cancel'); ok('turno en 5 h: forzar el POST de cancelar es rechazado', ap(i)['status']=='BOOKED' and 'ya no se puede' in r)
r=post(tok,'reschedule',{'start_dt':(now_ar()+timedelta(days=3)).replace(hour=10,minute=0).strftime('%Y-%m-%dT%H:%M')})
ok('turno en 5 h: forzar el POST de reprogramar es rechazado', ap(i)['status']=='BOOKED' and 'ya no se puede' in r)

print('— B) límite 24 h, penalidad $ 5.000')
setcfg(24, True, 5000)
tok,i=mk(48); h=page(tok)
ok('turno en 48 h: avisa la penalidad que aplicaría después', 'penalidad de $ 5.000' in h)
tok,i=mk(5); h=page(tok)
ok('turno en 5 h: avisa penalidad, deja cancelar y no reprogramar', 'penalidad de <strong>$ 5.000</strong>' in h and 'Cancelar turno</button>' in h and 'name="start_dt"' not in h)
ok('turno en 5 h: la confirmación del botón menciona la penalidad', 'Corresponde una penalidad de $ 5.000' in h)
r=post(tok,'reschedule',{'start_dt':'2030-01-07T10:00'}); ok('turno en 5 h: reprogramar rechazado', ap(i)['status']=='BOOKED')
r=post(tok,'cancel'); a=ap(i)
ok('turno en 5 h: cancela y registra penalidad pendiente', a['status']=='CANCELED' and a['penalty_applied'] and a['payment_status']=='PENDING' and float(a['paid_amount'])==5000 and a['payment_notes']=='Penalidad por cancelación tardía')
ok('turno en 5 h: el mensaje al cliente informa la penalidad', 'corresponde una penalidad de $ 5.000' in r)
with app.app_context():
    log=AppointmentLog.query.filter_by(appointment_id=i).order_by(AppointmentLog.id.desc()).first()
    ok(f'historial: "{log.notes}"', 'fuera de término' in log.notes and '$ 5.000' in log.notes)
adm=app.test_client(); h=adm.get('/admin/login').get_data(as_text=True); t=re.search(r'name="csrf_token" value="([^"]+)"',h).group(1)
adm.post('/admin/login',data={'email':'admin@pepito.com','password':'admin123','csrf_token':t})
h=adm.get('/admin/pepito?section=payments').get_data(as_text=True)
ok('panel > Pagos muestra la penalidad pendiente', 'Penalidad por cancelación tardía' in h)

print('— C) límite 0 y turnos pasados')
setcfg(0, False, 0)
tok,i=mk(0.5); post(tok,'cancel'); ok('límite 0: se cancela 30 min antes', ap(i)['status']=='CANCELED')
tok,i=mk(-2); h=page(tok); post(tok,'cancel'); ok('turno pasado: no se puede cancelar', ap(i)['status']=='BOOKED' and 'ya pasó' in h)

print('— D) configuración')
h=adm.get('/admin/pepito?section=settings').get_data(as_text=True)
ok('límite 0 se muestra como 0 (antes mostraba 24)', 'name="cancelation_limit_hours"\n                       value="0"' in h)
t=re.search(r'name="csrf_token" value="([^"]+)"',h).group(1)
adm.post('/admin/pepito/company',data={'target_section':'settings','cancelation_limit_hours':'-5','cancelation_penalty_amount':'-100','csrf_token':t})
with app.app_context():
    co=Company.query.filter_by(slug='pepito').first(); ok('valores negativos se corrigen a 0', co.cancelation_limit_hours==0 and co.cancelation_penalty_amount==0)

print('— E) email')
from app.services.email_service import _render, BOOKING_CANCELED_BODY
with app.app_context(), app.test_request_context():
    body=_render(BOOKING_CANCELED_BODY,name='Ana',company='Pepito',service='Pelo',professional='Juan',start_dt='x',company_url='u',penalty='$ 5.000')
    body2=_render(BOOKING_CANCELED_BODY,name='Ana',company='Pepito',service='Pelo',professional='Juan',start_dt='x',company_url='u',penalty=None)
ok('email de cancelación menciona la penalidad solo cuando corresponde', 'penalidad de $ 5.000' in body and 'penalidad' not in body2)
from app.utils import format_ars
ok('formato de pesos', format_ars(5000)=='$ 5.000' and format_ars(1234.5)=='$ 1.234,50' and format_ars(None)=='$ 0')
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
