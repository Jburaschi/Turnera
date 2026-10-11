import re
from datetime import date, timedelta
from app import create_app
from app.extensions import db, limiter
from app.models import *
from app.timeutils import today_ar
app = create_app(); limiter.enabled = False
res = []
def ok(n, c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
def tok(c, url): return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)
with app.app_context():
    c = Company.query.filter_by(slug='pepito').first(); c.plan_status = 'ACTIVE'; c.trial_expires_at = None; db.session.commit()
    emp = next(e for e in c.employees if e.active and e.services and e.schedules); svc = emp.services[0]
    eid, sid = emp.id, svc.id; worked = {s.weekday for s in emp.schedules}
a = app.test_client()
a.post('/admin/login', data={'email': 'admin@pepito.com', 'password': 'admin123', 'csrf_token': tok(a, '/admin/login')})
t = today_ar(); nxt = (t.replace(day=1) + timedelta(days=32)).replace(day=1)
r = a.get(f'/admin/pepito/api/slots/month?service_id={sid}&employee_id={eid}&year={nxt.year}&month={nxt.month}')
d = r.get_json()
ok('devuelve un número por cada día del mes', r.status_code == 200 and len(d) >= 28)
ok('días que trabaja tienen horarios libres', any(v > 0 for k, v in d.items() if date.fromisoformat(k).weekday() in worked))
ok('días que no trabaja quedan en 0', all(v == 0 for k, v in d.items() if date.fromisoformat(k).weekday() not in worked))
r = a.get(f'/admin/pepito/api/slots/month?service_id={sid}&employee_id={eid}&year={t.year}&month={t.month}')
d = r.get_json()
ok('días pasados quedan en 0', all(v == 0 for k, v in d.items() if date.fromisoformat(k) < t))
ok('coincide con la lista de horarios del día', (lambda k: d[k] == len(a.get(f'/admin/pepito/api/slots?service_id={sid}&employee_id={eid}&day={k}').get_json()))(max(k for k in d if date.fromisoformat(k) >= t)))
ok('mes 13 o sin datos → vacío', a.get(f'/admin/pepito/api/slots/month?service_id={sid}&employee_id={eid}&year=2026&month=13').get_json() == {} and a.get('/admin/pepito/api/slots/month').get_json() == {})
ok('sin sesión no responde datos', app.test_client().get(f'/admin/pepito/api/slots/month?service_id={sid}&employee_id={eid}&year={t.year}&month={t.month}').status_code in (302, 401))
h = a.get('/admin/pepito?section=agenda').get_data(as_text=True)
ok('el alta de turno usa el calendario nuevo', 'data-ntc' in h and 'type="date" id="nt-date"' not in h and 'admin_nt_calendar.js' in h)
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
