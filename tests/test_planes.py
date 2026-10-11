import re, os
from datetime import datetime, timedelta, time
from app import create_app
from app.extensions import db, limiter
from app.models import *
from app.services.google_calendar import company_has_google_plan
from app.timeutils import now_ar
app = create_app(); limiter.enabled = False
res = []
def ok(n, c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
def tok(c, url): return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)
def set_plan(plan, status='TRIAL', days=20):
    with app.app_context():
        co = Company.query.filter_by(slug='pepito').first()
        co.plan_name, co.plan_status = plan, status
        co.trial_expires_at = datetime.utcnow() + timedelta(days=days) if status == 'TRIAL' else None
        db.session.commit()
def co_():
    return Company.query.filter_by(slug='pepito').first()
a = app.test_client(); t = tok(a, '/admin/login')
a.post('/admin/login', data={'email': 'admin@pepito.com', 'password': 'admin123', 'csrf_token': t})
T = lambda: tok(a, '/admin/pepito?section=agenda')
def body(r): return r.get_data(as_text=True)
def new_emp(name, active=True):
    d = {'name': name, 'block_0_weekday': '0', 'block_0_start': '09:00', 'block_0_end': '12:00', 'csrf_token': T()}
    if active: d['active'] = 'on'
    return a.post('/admin/pepito/employees', data=d, follow_redirects=True)
def n_active():
    with app.app_context(): return Employee.query.filter_by(company_id=co_().id, active=True).count()

print('— BASE (prueba vigente)')
set_plan('BASE')
with app.app_context(): ok('Google Calendar no incluido', not company_has_google_plan(co_()))
r = new_emp('Nuevo')
ok(f'profesionales: con 3 activos no deja crear otro ({n_active()} activos)', n_active() == 3 and 'Tu plan BASE incluye 1 profesional' in body(r))
with app.app_context(): juan = Employee.query.filter_by(name='Juan').first().id
a.post(f'/admin/pepito/employees/{juan}/toggle-active', data={'csrf_token': T()})
ok('desactivar un profesional sigue permitido en BASE', n_active() == 2)
r = a.post(f'/admin/pepito/employees/{juan}/toggle-active', data={'csrf_token': T()}, follow_redirects=True)
ok('no deja reactivar por encima del límite', n_active() == 2 and 'Tu plan BASE incluye 1 profesional' in body(r))
h = body(a.get('/admin/pepito?section=professionals'))
ok('en Profesionales aparece el aviso de límite en lugar de "Nuevo profesional"', 'Tu plan BASE incluye 1 profesional' in h and 'data-bs-target="#new-employee-form"' not in h)
r = a.post('/admin/pepito/team', data={'name': 'X', 'email': 'x@p.com', 'password': '12345678', 'role': 'staff', 'csrf_token': tok(a, '/admin/pepito/team')}, follow_redirects=True)
with app.app_context(): ok('usuarios: BASE no deja invitar (solo el dueño)', AdminUser.query.filter_by(email='x@p.com').first() is None and 'incluye 1 usuario' in body(r))
h = body(a.get('/admin/pepito?section=payments'))
ok('Pagos muestra la tarjeta "Ver planes" y no la tabla', 'Registro de pagos de turnos' in h and 'Ver planes' in h and 'Registrar pago' not in h)
with app.app_context(): apid = Appointment.query.filter_by(company_id=co_().id).first().id
r = a.post('/admin/pepito/appointments/payment', data={'appointment_id': apid, 'payment_status': 'PAID', 'csrf_token': T()}, follow_redirects=True)
with app.app_context(): ok('registrar un pago por URL → bloqueado', db.session.get(Appointment, apid).payment_status is None and 'desde el plan PRO' in body(r))
ok('menú: Pagos con etiqueta PRO', 'plan-lock">PRO' in body(a.get('/admin/pepito')))
r = a.get('/admin/pepito/agenda.csv', follow_redirects=True)
ok('exportar CSV → bloqueado', 'Exportar la agenda a Excel está incluido desde el plan PRO' in body(r))
ok('agenda: "Exportar a Excel" con candado', 'Exportar a Excel' in body(a.get('/admin/pepito?section=agenda')) and 'href="/admin/pepito/agenda.csv' not in body(a.get('/admin/pepito?section=agenda')))
r = a.get(f'/admin/pepito/appointments/{apid}/log', follow_redirects=True)
ok('historial del turno → bloqueado (PREMIUM)', 'desde el plan PREMIUM' in body(r))
a.post('/admin/pepito/company', data={'target_section': 'settings', 'cancelation_limit_hours': '24', 'cancelation_penalty_enabled': 'on', 'cancelation_penalty_amount': '5000', 'csrf_token': T()})
with app.app_context(): c = co_(); ok('penalidad: BASE no la puede activar', not c.cancelation_penalty_enabled)
a.post('/admin/pepito/company', data={'target_section': 'company', 'name': 'Pepito Studio', 'brand_color': '#ff0000', 'instagram_url': 'instagram.com/pepito', 'csrf_token': T()})
with app.app_context(): c = co_(); ok('perfil: color y redes no se guardan en BASE', c.brand_color != '#ff0000' and not c.instagram_url)
h = body(a.get('/admin/pepito?section=company'))
ok('perfil: color y redes deshabilitados con candado', 'plan-field-locked' in h and 'desde el plan PRO' in h)

print('— PRO (prueba vigente)')
set_plan('PRO')
with app.app_context(): ok('Google Calendar incluido durante la prueba', company_has_google_plan(co_()))
r = a.post(f'/admin/pepito/employees/{juan}/toggle-active', data={'csrf_token': T()}, follow_redirects=True)
new_emp('Cuatro'); new_emp('Cinco'); r = new_emp('Seis')
ok(f'profesionales: hasta 5 ({n_active()} activos) y el sexto bloqueado', n_active() == 5 and 'Tu plan PRO incluye 5 profesionales' in body(r))
for i in range(3):
    r = a.post('/admin/pepito/team', data={'name': f'U{i}', 'email': f'u{i}@p.com', 'password': '12345678', 'role': 'staff', 'csrf_token': tok(a, '/admin/pepito/team')}, follow_redirects=True)
with app.app_context(): n = AdminUser.query.filter_by(company_id=co_().id, active=True).count()
ok(f'usuarios: dueño + 2 ({n}) y el tercero bloqueado', n == 3 and 'incluye 3 usuarios' in body(r))
r = a.get('/admin/pepito/agenda.csv')
ok('exportar CSV funciona', r.status_code == 200 and 'text/csv' in r.headers['Content-Type'])
ok('agenda: botón "Exportar a Excel" activo', 'href="/admin/pepito/agenda.csv' in body(a.get('/admin/pepito?section=agenda')))
ok('historial sigue bloqueado en PRO', 'desde el plan PREMIUM' in body(a.get(f'/admin/pepito/appointments/{apid}/log', follow_redirects=True)))
a.post('/admin/pepito/company', data={'target_section': 'company', 'name': 'Pepito Studio', 'brand_color': '#aa2255', 'instagram_url': 'instagram.com/pepito', 'csrf_token': T()})
with app.app_context(): c = co_(); ok('perfil: color y redes se guardan', c.brand_color == '#aa2255' and c.instagram_url == 'https://instagram.com/pepito')
h = body(app.test_client().get('/pepito'))
ok('página pública usa el color y muestra Instagram', '--brand: #aa2255' in h and 'https://instagram.com/pepito' in h)
ok('la reserva usa el color', '--brand: #aa2255' in body(app.test_client().get('/pepito/booking')))
a.post('/admin/pepito/company', data={'target_section': 'settings', 'cancelation_limit_hours': '24', 'cancelation_penalty_enabled': 'on', 'cancelation_penalty_amount': '5000', 'csrf_token': T()})
with app.app_context(): c = co_(); ok('penalidad se puede activar', c.cancelation_penalty_enabled and c.cancelation_penalty_amount == 5000)
r = a.post('/admin/pepito/appointments/payment', data={'appointment_id': apid, 'payment_status': 'PAID', 'csrf_token': T()})
with app.app_context(): ok('registrar pago funciona', db.session.get(Appointment, apid).payment_status == 'PAID')

print('— Baja de PRO a BASE (sin borrar nada)')
set_plan('BASE')
with app.app_context():
    c = co_(); ok('se conserva la configuración de penalidad pero no se aplica', c.cancelation_penalty_enabled)
    from app.services.appointment_service import penalty_enabled
    ok('penalty_enabled() = False en BASE', not penalty_enabled(c))
    ok(f'los 5 profesionales siguen activos ({Employee.query.filter_by(company_id=c.id, active=True).count()})', Employee.query.filter_by(company_id=c.id, active=True).count() == 5)
h = body(app.test_client().get('/pepito'))
ok('página pública vuelve al color de Turnex y sin redes', '--brand: #3654f0' in h and 'https://instagram.com/pepito' not in h)
# turno tardío: sin penalidad en BASE → no se puede cancelar online
with app.app_context():
    c = co_(); e = Employee.query.filter_by(company_id=c.id, name='María').first(); s = Service.query.filter_by(company_id=c.id, name='Pelo').first()
    st = (now_ar() + timedelta(hours=5, minutes=7)).replace(second=0, microsecond=0)
    ap = Appointment(company=c, service=s, employee=e, start_dt=st, end_dt=st + timedelta(hours=1), status='BOOKED', guest_name='T', manage_token='tkbase'); db.session.add(ap); db.session.commit()
h = body(app.test_client().get('/pepito/a/tkbase'))
ok('cliente: turno tardío en BASE no ofrece cancelar con penalidad', 'ya no se puede cancelar ni reprogramar online' in h and 'penalidad' not in h)

print('— PREMIUM')
set_plan('PREMIUM', 'ACTIVE')
new_emp('Siete'); new_emp('Ocho')
ok(f'profesionales ilimitados ({n_active()} activos)', n_active() == 7)
ok('historial del turno abre', a.get(f'/admin/pepito/appointments/{apid}/log').status_code == 200)
ok('detalle del turno con "Ver historial del turno"', 'id="ag2d-log"' in body(a.get('/admin/pepito?section=agenda')))

print('— Prueba vencida')
set_plan('PRO', 'TRIAL', days=-1)
with app.app_context(): ok('PRO con prueba vencida: Google Calendar se corta', not company_has_google_plan(co_()))

print('— Alta guiada y landing')
for plan, nombres, debe in (('BASE', ['A', 'B'], False), ('PRO', ['A', 'B', 'C'], True)):
    c = app.test_client(); html = body(c.get(f'/registrar?plan={plan}')); t = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    c.post(f'/registrar?plan={plan}', data={'full_name': 'Ana', 'email': f'on{plan.lower()}@x.com', 'password': '12345678', 'terms': 'on', 'csrf_token': t, 'plan': plan})
    c.post('/registrar/negocio', data={'name': f'Neg {plan}', 'category': 'Peluquerías', 'csrf_token': t})
    r = c.post('/registrar/equipo', data={'staffing_mode': 'team', 'team_professional_name[]': nombres, 'csrf_token': t})
    avanzo = r.status_code == 302
    ok(f'alta guiada {plan} con {len(nombres)} profesionales → {"avanza" if avanzo else "avisa el límite"}', avanzo == debe and (debe or 'incluye hasta 1 profesional' in body(r)))
h = body(app.test_client().get('/'))
ok('landing: listas de planes desde la definición única', 'Hasta 5 profesionales' not in h and '5 profesionales' in h and 'Historial de cambios de cada turno' in h and 'Funcionalidades a medida' not in h)
ok('landing: PREMIUM lleva al registro con plan PREMIUM', '/registrar?plan=PREMIUM' in h and '/platform/login' not in h.split('hl-plans-grid')[1][:4000])
set_plan('PRO')
h = body(a.get('/admin/pepito?section=plan'))
ok('Mi plan: tabla comparativa', 'Comparar planes' in h and 'plan-compare' in h)
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
