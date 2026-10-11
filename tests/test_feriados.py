import re
from datetime import date, datetime, time, timedelta
from app import create_app
from app.extensions import db, limiter
from app.models import *
from app.services.holidays_ar import national_holidays, holiday_name
from app.services.availability import get_availability_for_day
from app.timeutils import today_ar
app = create_app(); limiter.enabled = False
res = []
def ok(n, c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
def tok(c, url): return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)
def body(r): return r.get_data(as_text=True)

print('— Feriados')
h26 = national_holidays(2026)
ok('9 de julio es feriado', holiday_name(date(2026, 7, 9)) == 'Día de la Independencia')
ok('Jueves Santo no cierra (es no laborable)', all('Jueves Santo' not in n for n in h26.values()))
ok('2 de abril sigue (Malvinas) aunque coincida con Jueves Santo', 'Malvinas' in (holiday_name(date(2026, 4, 2)) or ''))
ok('un día común no es feriado', holiday_name(date(2026, 10, 13)) is None)

# próximo feriado futuro que caiga en un día que trabaja algún profesional
with app.app_context():
    c = Company.query.filter_by(slug='pepito').first(); c.plan_status = 'ACTIVE'; c.trial_expires_at = None; db.session.commit()
    emp = next(e for e in c.employees if e.active and e.services and e.schedules); svc = emp.services[0]
    worked = {s.weekday for s in emp.schedules}
    t = today_ar()
    hol = next(d for y in (t.year, t.year + 1) for d in sorted(national_holidays(y)) if d > t and d.weekday() in worked)
    normal = next(t + timedelta(days=i) for i in range(1, 30) if (t + timedelta(days=i)).weekday() in worked and not holiday_name(t + timedelta(days=i)))
    ok(f'el feriado {hol} no ofrece turnos', get_availability_for_day(c, svc, hol, emp.id) == [])
    ok('un día común sí ofrece turnos', len(get_availability_for_day(c, svc, normal, emp.id)) > 0)
    ok('el panel puede forzar un turno en feriado', len(get_availability_for_day(c, svc, hol, emp.id, ignore_past=True, ignore_blocks=True)) > 0)
    cid, eid, sid = c.id, emp.id, svc.id
pub = app.test_client()
r = pub.get(f'/api/pepito/availability/day?service_id={sid}&employee_id={eid}&date={hol.isoformat()}')
ok('reserva pública: feriado sin horarios', r.get_json() == [])
r = pub.get(f'/api/pepito/availability/month?service_id={sid}&employee_id={eid}&year={hol.year}&month={hol.month}')
ok('calendario público: el feriado figura sin lugar', r.get_json().get(hol.isoformat()) in (False, 0))

print('— Bloqueos')
a = app.test_client()
a.post('/admin/login', data={'email': 'admin@pepito.com', 'password': 'admin123', 'csrf_token': tok(a, '/admin/login')})
h = body(a.get('/admin/pepito?section=blocked'))
ok('aparece la tarjeta de feriados con el próximo', 'Feriados nacionales' in h and hol.strftime('%d/%m') in h and 'Cerrado' in h)
ok('en la pestaña "Vacaciones" no aparece', 'Feriados nacionales' not in body(a.get('/admin/pepito?section=blocked&block_type=vacation')))
t2 = tok(a, '/admin/pepito?section=blocked')
r = a.post(f'/admin/pepito/holidays/{hol.isoformat()}/open', data={'csrf_token': t2}, follow_redirects=True)
ok('"Eliminar" abre el día y avisa', 'vas a atender' in body(r))
with app.app_context():
    ok('el día abierto ya ofrece turnos', len(get_availability_for_day(db.session.get(Company, cid), db.session.get(Service, sid), hol, eid)) > 0)
r = pub.get(f'/api/pepito/availability/day?service_id={sid}&employee_id={eid}&date={hol.isoformat()}')
ok('y la reserva pública también', len(r.get_json()) > 0)
h = body(a.get('/admin/pepito?section=blocked'))
ok('figura como Abierto con "Volver a cerrar"', 'Volver a cerrar' in h)
a.post(f'/admin/pepito/holidays/{hol.isoformat()}/open', data={'csrf_token': tok(a, '/admin/pepito?section=blocked')})
with app.app_context(): ok('abrir dos veces no duplica', HolidayOptOut.query.filter_by(company_id=cid, day=hol).count() == 1)
a.post(f'/admin/pepito/holidays/{hol.isoformat()}/close', data={'csrf_token': tok(a, '/admin/pepito?section=blocked')})
with app.app_context():
    ok('"Volver a cerrar" lo cierra de nuevo', get_availability_for_day(db.session.get(Company, cid), db.session.get(Service, sid), hol, eid) == [])
r = a.post(f'/admin/pepito/holidays/{normal.isoformat()}/open', data={'csrf_token': tok(a, '/admin/pepito?section=blocked')}, follow_redirects=True)
with app.app_context(): ok('no se puede "abrir" un día que no es feriado', 'no es un feriado' in body(r) and HolidayOptOut.query.filter_by(day=normal).count() == 0)
r = a.post(f'/admin/pepito/holidays/hola/open', data={'csrf_token': tok(a, '/admin/pepito?section=blocked')})
ok('fecha basura no rompe', r.status_code == 302)
with app.app_context():
    e = db.session.get(Employee, eid); s = db.session.get(Service, sid)
    st = datetime.combine(hol, time(23, 0))
    if not Appointment.query.filter(Appointment.employee_id == eid, Appointment.status == 'BOOKED', Appointment.start_dt >= datetime.combine(hol, time.min), Appointment.start_dt < datetime.combine(hol + timedelta(days=1), time.min)).count():
        db.session.add(Appointment(company_id=cid, employee_id=eid, service_id=sid, start_dt=st, end_dt=st + timedelta(minutes=30), status='BOOKED', guest_name='Ya reservado')); db.session.commit()
h = body(a.get('/admin/pepito?section=blocked'))
ok('avisa si ya había turnos reservados ese feriado', 'turno reservado ese día' in h or 'turnos reservados ese día' in h)
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
