import re
from datetime import datetime, timedelta
from app import create_app
from app.extensions import db, limiter
from app.models import *
from app.timeutils import today_ar
app = create_app(); limiter.enabled = False
res = []
def ok(n, c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
def tok(c, url): return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)
def body(r): return r.get_data(as_text=True)
p = app.test_client()
with app.app_context():
    u = PlatformUser.query.first(); u.set_password('owner12345'); db.session.commit(); email = u.email
    pep = Company.query.filter_by(slug='pepito').first(); pid = pep.id; pep.plan_status = 'ACTIVE'; pep.trial_expires_at = None
    # una segunda empresa con un cliente, para buscar entre empresas
    other = Company(name='Spa Sur', slug='spa-sur', plan_name='BASE', plan_status='ACTIVE'); db.session.add(other); db.session.flush()
    db.session.add(CompanyConfig(company=other))
    oc = Customer(company_id=other.id, full_name='Rocío Sur', email='rocio@sur.com', phone='11 4444-9999'); oc.set_password('x123456'); db.session.add(oc)
    c2x = Customer(company_id=pid, full_name='Otro Cliente', email='otro@demo.com'); c2x.set_password('x123456'); db.session.add(c2x)
    db.session.commit(); cust = Customer.query.filter_by(company_id=pid).order_by(Customer.id).first(); cust_id, cust_name = cust.id, cust.full_name
p.post('/platform/login', data={'email': email, 'password': 'owner12345', 'csrf_token': tok(p, '/platform/login')})

print('— Clientes')
h = body(p.get('/platform/clientes'))
ok('lista clientes de todas las empresas', 'Rocío Sur' in h and cust_name in h and 'Spa Sur' in h and 'Pepito Studio' in h)
ok('el menú tiene Clientes, Turnos y Actividad', all(x in h for x in ('/platform/clientes', '/platform/turnos', '/platform/actividad')))
ok('busca por teléfono sin importar espacios o guiones', 'Rocío Sur' in body(p.get('/platform/clientes?q=1144449999')) and 'Otro Cliente' not in body(p.get('/platform/clientes?q=1144449999')))
ok('busca por nombre de negocio', 'Rocío Sur' in body(p.get('/platform/clientes?q=spa sur')))
ok('filtra por negocio', 'Rocío Sur' not in body(p.get(f'/platform/clientes?company={pid}')))
h = body(p.get(f'/platform/clientes/{cust_id}'))
ok('detalle con datos, negocio y turnos', cust_name in h and 'Pepito Studio' in h and 'Turnos' in h and 'Abrir en su negocio' in h)
t = tok(p, f'/platform/clientes/{cust_id}')
r = p.post(f'/platform/clientes/{cust_id}', data={'full_name': 'Lucía Editada', 'email': 'lucia.nueva@demo.com', 'phone': '11 1111-2222', 'dni': '30111222', 'csrf_token': t}, follow_redirects=True)
with app.app_context():
    c = db.session.get(Customer, cust_id)
    ok('edita el cliente directo desde plataforma', c.full_name == 'Lucía Editada' and c.email == 'lucia.nueva@demo.com' and c.dni == '30111222' and 'Cliente actualizado' in body(r))
t = tok(p, f'/platform/clientes/{cust_id}')
with app.app_context(): other_mail = Customer.query.filter(Customer.company_id == pid, Customer.id != cust_id).first().email
r = p.post(f'/platform/clientes/{cust_id}', data={'full_name': 'X', 'email': other_mail, 'csrf_token': t}, follow_redirects=True)
ok('no deja repetir el email dentro del mismo negocio', 'otro cliente con ese email' in body(r))
r = p.post(f'/platform/clientes/{cust_id}', data={'full_name': 'Lucía Editada', 'email': 'lucia.nueva@demo.com', 'password': 'nueva123', 'csrf_token': tok(p, f'/platform/clientes/{cust_id}')})
c2 = app.test_client()
r = c2.post('/pepito/customer/login', data={'email': 'lucia.nueva@demo.com', 'password': 'nueva123', 'csrf_token': tok(c2, '/pepito/customer/login')})
ok('la contraseña nueva del cliente funciona', r.status_code == 302)
ok('cliente inexistente → 404', p.get('/platform/clientes/999999').status_code == 404)

print('— Turnos')
h = body(p.get('/platform/turnos?rango=30'))
ok('lista turnos con negocio, cliente y estado', 'Pepito Studio' in h and 'Reservado' in h and 'Ver en su agenda' in h)
ok('incluye invitados', '(invitado)' in h or 'invitado' in h)
ok('filtro por estado', 'Cancelado' not in body(p.get('/platform/turnos?rango=30&estado=BOOKED')).split('<tbody>')[1])
ok('rango a medida y fechas inválidas no rompen', p.get('/platform/turnos?rango=custom&desde=2026-99-01&hasta=hola').status_code == 200)
ok('búsqueda sin resultados', 'No hay turnos con esos filtros' in body(p.get('/platform/turnos?rango=30&q=zzzznadie')))
day = (today_ar() + timedelta(days=1)).isoformat()
r = p.post(f'/platform/companies/{pid}/enter', data={'section': 'agenda', 'day': day, 'csrf_token': tok(p, '/platform/turnos')})
ok('"Ver en su agenda" entra al negocio en ese día', r.status_code == 302 and 'section=agenda' in r.headers['Location'] and day in r.headers['Location'])

print('— Actividad')
a = p  # ahora está dentro del negocio
t = tok(a, '/admin/pepito?section=company')
with app.app_context(): cname = db.session.get(Company, pid).name
a.post('/admin/pepito/company', data={'name': cname, 'description': 'Cambio hecho desde plataforma', 'target_section': 'company', 'csrf_token': t})
with app.app_context():
    ap = Appointment.query.filter_by(company_id=pid, status='BOOKED').first(); apid = ap.id
a.post(f'/admin/pepito/appointments/{apid}/status', data={'status': 'DONE', 'csrf_token': tok(a, '/admin/pepito?section=agenda')})
with app.app_context():
    log = AppointmentLog.query.filter_by(appointment_id=apid).order_by(AppointmentLog.id.desc()).first()
    ok('el historial del turno dice que lo hizo la plataforma', log and log.actor_type == 'platform' and email in (log.actor_name or ''))
a.post('/platform/volver', data={'csrf_token': tok(a, '/admin/pepito?section=agenda')})
h = body(p.get('/platform/actividad'))
for txt in ('Editó un cliente', 'Entró al panel del negocio', 'Editó el perfil o las reglas del negocio', 'Cambió el estado de un turno', 'Salió del panel del negocio'):
    ok(f'Actividad registra: {txt}', txt in h)
ok('no guarda contraseñas en el detalle', 'nueva123' not in h and 'cambió la contraseña' in h)
ok('filtrar por negocio', 'Editó un cliente' in body(p.get(f'/platform/actividad?company={pid}')))
ok('un dueño normal no ve la actividad', app.test_client().get('/platform/actividad').status_code == 302)
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
