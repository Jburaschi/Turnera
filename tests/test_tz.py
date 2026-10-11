import os, re, sys
os.environ['CRON_SECRET']='sekret'
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo
from app import create_app
from app.extensions import db, limiter
from app.models import *
app=create_app(); limiter.enabled=False
AR=ZoneInfo('America/Argentina/Buenos_Aires')
now_ar=datetime.now(AR).replace(tzinfo=None, second=0, microsecond=0)
res=[]
def ok(n,c): res.append(c); print(('PASS ' if c else 'FAIL ')+n)
print(f'servidor datetime.now()={datetime.now():%H:%M} · hora Argentina={now_ar:%H:%M}')
with app.app_context():
    maria=Employee.query.filter_by(name='María').first(); pelo=Service.query.filter_by(name='Pelo').first()
    db.session.add(EmployeeSchedule(employee_id=maria.id, weekday=now_ar.weekday(), start_time=time(0,0), end_time=time(23,45))); db.session.commit()
    co=Company.query.first(); co.cancelation_limit_hours=0
    def mk(start, **kw):
        a=Appointment(company=co, service=pelo, employee=maria, start_dt=start, end_dt=start+timedelta(minutes=60), status='BOOKED', guest_name='T', guest_email='t@x.com', manage_token=os.urandom(8).hex(), **kw)
        db.session.add(a); db.session.commit(); return a.manage_token, a.id
    tok_soon,_  = mk(now_ar+timedelta(hours=1, minutes=30))
    _,rem_ok    = mk(now_ar+timedelta(hours=24))
    _,rem_wrong = mk(now_ar+timedelta(hours=27, minutes=30))
    pelo_id, maria_id = pelo.id, maria.id
c=app.test_client()
slots=c.get(f'/api/pepito/availability/day?service_id={pelo_id}&employee_id={maria_id}&date={now_ar.date()}').json
first=datetime.fromisoformat(slots[0]['start']) if slots else None
ok(f'turnos de hoy arrancan en la hora actual de Argentina (primer turno {first:%H:%M})' if first else 'hay turnos hoy', bool(first) and now_ar <= first < now_ar+timedelta(minutes=30))
h=c.get(f'/pepito/a/{tok_soon}').get_data(as_text=True); t=re.search(r'name="csrf_token" value="([^"]+)"',h).group(1)
r=c.post(f'/pepito/a/{tok_soon}/cancel',data={'csrf_token':t},follow_redirects=True).get_data(as_text=True)
ok('turno dentro de 1h30 se puede cancelar (no lo toma como pasado)', 'Turno cancelado' in r)
c.post('/internal/cron/reminders?token=sekret')
with app.app_context():
    ok('recordatorio sale para el turno de dentro de 24 h', Appointment.query.get(rem_ok).reminder_sent)
    ok('recordatorio NO sale para el turno de dentro de 27 h 30', not Appointment.query.get(rem_wrong).reminder_sent)
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
