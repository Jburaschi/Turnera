import re
from datetime import datetime, timedelta, time
from app import create_app
from app.extensions import db, limiter
from app.models import *
from app.services import google_calendar as gc
from app.services.availability import get_availability_for_day
from app.services.holidays_ar import holiday_name
from app.timeutils import today_ar
app = create_app(); limiter.enabled = False
res = []
def ok(n, c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
def tok(c, url): return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)
def body(r): return r.get_data(as_text=True)

calls = []
class _Exec:
    def __init__(self, kind, kw): self.kind, self.kw = kind, kw
    def execute(self):
        calls.append((self.kind, self.kw)); return {'id': 'ev%d' % len(calls)}
class _Events:
    def insert(self, **kw): return _Exec('insert', kw)
    def patch(self, **kw): return _Exec('patch', kw)
    def delete(self, **kw): return _Exec('delete', kw)
class _Svc:
    def events(self): return _Events()
gc.build = lambda *a, **kw: _Svc()

with app.app_context():
    co = Company.query.filter_by(slug='pepito').first(); co.plan_name = 'PRO'; co.plan_status = 'ACTIVE'; co.trial_expires_at = None
    db.session.add(GoogleCalendarConnection(company_id=co.id, enabled=True, refresh_token='r', access_token='a')); db.session.commit()
    emps = [e for e in co.employees if e.active and e.services and e.schedules]
    e1, e2 = emps[0], emps[1]
    svc = next(s for s in e1.services if s in e2.services)
    ids = (e1.id, e2.id, svc.id, co.id)
    t = today_ar()
    def free(eid):
        for i in range(1, 30):
            d = t + timedelta(days=i)
            if holiday_name(d): continue
            sl = get_availability_for_day(co, svc, d, eid)
            if sl: return sl[0]['start'].isoformat()
    s1, s2 = free(e1.id), free(e2.id)
E1, E2, SID, CID = ids

a = app.test_client()
a.post('/admin/login', data={'email': 'admin@pepito.com', 'password': 'admin123', 'csrf_token': tok(a, '/admin/login')})

print('— Mail del profesional')
L = '/admin/pepito?section=professionals'
h = body(a.get(L + f'&pro={E1}'))
ok('la ficha tiene "Email para su calendario" y su color', 'name="calendar_email"' in h and 'Color en el calendario' in h)
def save(eid, email):
    with app.app_context():
        e = db.session.get(Employee, eid)
        d = {'name': e.name, 'active': '1', 'calendar_email': email, 'service_ids': [str(s.id) for s in e.services], 'csrf_token': tok(a, L + f'&pro={eid}')}
        for i, sc in enumerate(e.schedules):
            d[f'block_{i}_weekday'] = str(sc.weekday); d[f'block_{i}_start'] = sc.start_time.strftime('%H:%M'); d[f'block_{i}_end'] = sc.end_time.strftime('%H:%M')
    return a.post(f'/admin/pepito/employees/{eid}/update', data=d, follow_redirects=True)
r = save(E1, 'no-es-mail')
with app.app_context(): ok('mail inválido se rechaza', 'no es válido' in body(r) and db.session.get(Employee, E1).calendar_email is None)
calls.clear()
save(E1, 'Juan@Gmail.com')
with app.app_context(): ok('guarda el mail en minúsculas', db.session.get(Employee, E1).calendar_email == 'juan@gmail.com')

print('— Eventos')
calls.clear()
c = app.test_client(); t2 = tok(c, '/pepito/booking')
c.post('/pepito/book', data=dict(service_id=SID, employee_id=E1, start_dt=s1, guest_name='Ana', guest_phone='1', csrf_token=t2))
ins = [k for k in calls if k[0] == 'insert']
b = ins[-1][1]['body'] if ins else {}
with app.app_context(): name1 = db.session.get(Employee, E1).name
ok('al reservar se crea el evento', bool(ins))
ok('título: prestación · cliente · profesional', b.get('summary', '').endswith(f'· Ana · {name1}'))
ok('el profesional va como invitado', b.get('attendees') == [{'email': 'juan@gmail.com', 'displayName': name1}])
ok('sin aviso por mail (por defecto)', ins and ins[-1][1].get('sendUpdates') == 'none')
ok('tiene color de profesional', b.get('colorId') in gc.GOOGLE_EVENT_COLORS)
with app.app_context(): ap1 = Appointment.query.filter_by(guest_name='Ana').first().id
calls.clear()
c.post('/pepito/book', data=dict(service_id=SID, employee_id=E2, start_dt=s2, guest_name='Beto', guest_phone='1', csrf_token=tok(c, '/pepito/booking')))
b2 = [k for k in calls if k[0] == 'insert'][-1][1]['body']
ok('profesional sin mail: evento sin invitados', b2.get('attendees') == [])
ok('cada profesional con su color', b2.get('colorId') != b.get('colorId'))

print('— Aviso por mail')
h = body(a.get('/admin/pepito?section=integrations'))
ok('Integraciones lista profesionales con color y la opción de aviso', 'Profesionales en Google Calendar' in h and 'juan@gmail.com' in h and 'name="notify_staff"' in h)
a.post('/admin/pepito/integrations/google/settings', data={'notify_staff': '1', 'csrf_token': tok(a, '/admin/pepito?section=integrations')})
with app.app_context(): ok('se guarda la opción', GoogleCalendarConnection.query.filter_by(company_id=CID).first().notify_staff is True)
calls.clear()
with app.app_context():
    ap = db.session.get(Appointment, ap1); gc.ensure_google_event_for_appointment(ap)
ok('con aviso activado: sendUpdates=all', calls and calls[-1][1].get('sendUpdates') == 'all' and calls[-1][0] == 'patch')
a.post('/admin/pepito/integrations/google/settings', data={'csrf_token': tok(a, '/admin/pepito?section=integrations')})

print('— Cambios')
calls.clear()
save(E1, '')
pat = [k for k in calls if k[0] == 'patch']
ok('al sacar el mail se actualizan sus turnos futuros (sin invitado)', pat and all(k[1]['body']['attendees'] == [] for k in pat))
calls.clear()
save(E1, 'juan@gmail.com')
ok('al volver a cargarlo se lo suma a sus turnos futuros', any(k[1]['body']['attendees'] for k in calls if k[0] == 'patch'))
with app.app_context(): mt = Appointment.query.get(ap1).manage_token
calls.clear()
c.post(f'/pepito/a/{mt}/cancel', data={'csrf_token': tok(c, '/pepito/booking')})
ok('al cancelar se borra el evento (también del calendario del profesional)', any(k[0] == 'delete' for k in calls))
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
