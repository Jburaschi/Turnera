import re
from datetime import datetime, timedelta
from app import create_app
from app.extensions import db, limiter
from app.models import *
app = create_app(); limiter.enabled = False
res = []
def ok(n, c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
def tok(c, url): return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)
def body(r): return r.get_data(as_text=True)
def co(slug='pepito'):
    return Company.query.filter_by(slug=slug).first()

p = app.test_client()
with app.app_context():
    u = PlatformUser.query.first(); u.set_password('owner12345'); db.session.commit(); email = u.email
    pep = co(); pep_id = pep.id; pep.logo_url = 'https://ejemplo.com/logo.png'; db.session.commit()
p.post('/platform/login', data={'email': email, 'password': 'owner12345', 'csrf_token': tok(p, '/platform/login')})
T = lambda: tok(p, '/platform/')

print('— Lista, uso, búsqueda y filtros')
h = body(p.get('/platform/'))
ok('muestra uso por empresa (turnos del mes, profesionales, clientes)', 'turnos este mes' in h and 'prof.' in h and 'clientes' in h)
ok('botón "Entrar" por empresa', 'Entrar</button>' in h)
ok('filtros con contadores', 'plat-chip' in h and 'Todas' in h)
h = body(p.get('/platform/?q=pepito'))
ok('buscar por link encuentra a Pepito', 'Pepito Studio' in h)
h = body(p.get('/platform/?q=zzzz-no-existe'))
ok('búsqueda sin resultados avisa', 'No hay empresas que coincidan' in h)
h = body(p.get('/platform/?q=admin@pepito.com'))
ok('buscar por email del dueño', 'Pepito Studio' in h)
with app.app_context():
    c = co(); c.plan_status = 'TRIAL'; c.trial_expires_at = datetime.utcnow() - timedelta(days=2); db.session.commit()
h = body(p.get('/platform/?f=expired'))
ok('filtro "Prueba vencida" muestra a Pepito', 'Pepito Studio' in h and 'Prueba vencida' in h)
h = body(p.get('/platform/?f=suspended'))
ok('filtro "Suspendidas" no muestra a Pepito', 'Pepito Studio' not in h.split('Empresas registradas')[1])
h = body(p.get('/platform/?f=cualquiera'))
ok('filtro desconocido no rompe', 'Empresas registradas' in h)

print('— Plan y estado como listas cerradas')
def upd(**kw):
    with app.app_context():
        c = co(); owner = sorted(c.admins, key=lambda a: a.id)[0]
        d = {'name': c.name, 'slug': c.slug, 'plan_name': c.plan_name, 'plan_status': c.plan_status,
             'admin_name': owner.name, 'admin_email': owner.email, 'active': 'on', 'admin_active': 'on',
             'brand_color': c.brand_color, 'csrf_token': T()}
    d.update(kw)
    return p.post(f'/platform/companies/{pep_id}/update', data=d, follow_redirects=True)
r = upd(plan_name='PRO ', plan_status='ACTIVE')
with app.app_context(): c = co(); ok('guarda PRO / Activo (y limpia la prueba)', c.plan_name == 'PRO' and c.plan_status == 'ACTIVE' and c.trial_expires_at is None)
with app.app_context(): ok('guardar desde plataforma NO borra el logo', co().logo_url == 'https://ejemplo.com/logo.png')
r = upd(plan_name='GOLD')
with app.app_context(): ok('plan inventado se rechaza', co().plan_name == 'PRO' and 'plan o estado inválido' in body(r))
r = upd(plan_status='PENDING')
with app.app_context(): ok('estado inventado se rechaza', co().plan_status == 'ACTIVE')
r = upd(plan_status='TRIAL')
with app.app_context(): c = co(); ok('pasar a Prueba sin días pone 30 días', c.trial_expires_at and 29 <= (c.trial_expires_at - datetime.utcnow()).days <= 30)
r = upd(plan_status='TRIAL', trial_days='10')
with app.app_context(): c = co(); ok('Prueba con 10 días', 9 <= (c.trial_expires_at - datetime.utcnow()).days <= 10)
h = body(p.get('/platform/'))
ok('el formulario usa desplegables (no texto libre) para el plan', re.search(r'<select class="form-select" name="plan_name">', h) and 'name="plan_name" value=' not in h)
r = upd(slug='admin')
with app.app_context(): ok('link reservado "admin" se rechaza', co().slug == 'pepito' and 'reservado' in body(r))
r = upd(admin_password='123')
ok('contraseña corta del dueño se rechaza', 'al menos 8' in body(r))
upd(plan_status='ACTIVE')

print('— Crear empresa')
def create(**kw):
    d = {'name': 'Nueva Empresa', 'slug': '', 'admin_email': 'nuevo@x.com', 'admin_name': 'Nuevo',
         'admin_password': 'clave1234', 'plan_name': 'BASE', 'plan_status': 'TRIAL', 'active': 'on', 'csrf_token': T()}
    d.update(kw)
    return p.post('/platform/companies', data=d, follow_redirects=True)
r = create()
with app.app_context():
    c = co('nueva-empresa')
    ok('crea con link armado desde el nombre y prueba de 30 días', c and c.plan_status == 'TRIAL' and c.trial_expires_at and (c.trial_expires_at - datetime.utcnow()).days >= 29)
r = create(name='Otra', slug='login', admin_email='otra@x.com')
with app.app_context(): ok('no crea con link reservado', co('login') is None and 'reservado' in body(r))
r = create(name='Otra', slug='otra', admin_email='admin@pepito.com')
with app.app_context(): ok('no crea con email de dueño repetido', co('otra') is None)
r = create(name='Otra', slug='otra', admin_email='otra@x.com', plan_status='PENDING')
with app.app_context(): ok('no crea con estado inventado', co('otra') is None)

print('— Entrar como la empresa')
r = p.post(f'/platform/companies/{pep_id}/enter', data={'csrf_token': T()}, follow_redirects=True)
h = body(r)
ok('entra al panel de Pepito', r.status_code == 200 and 'Pepito Studio' in h and 'impersonation-bar' in h and 'Volver a plataforma' in h)
ok('en el panel no se puede abrir la plataforma', p.get('/platform/').status_code == 302)
h = body(p.get('/admin/pepito?section=agenda'))
ok('el aviso sigue en otras secciones', 'impersonation-bar' in h)
t = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
r = p.post('/platform/volver', data={'csrf_token': t}, follow_redirects=True)
h = body(r)
ok('"Volver a plataforma" vuelve al panel de plataforma filtrado por la empresa', 'Empresas registradas' in h and 'Pepito Studio' in h and 'impersonation-bar' not in h)
with app.app_context():
    c = co(); owner = sorted(c.admins, key=lambda a: a.id)[0]; owner.active = False; db.session.commit()
r = p.post(f'/platform/companies/{pep_id}/enter', data={'csrf_token': T()}, follow_redirects=True)
ok('no entra si el dueño está inactivo', 'no tiene un dueño activo' in body(r))
with app.app_context():
    c = co(); owner = sorted(c.admins, key=lambda a: a.id)[0]; owner.active = True; db.session.commit()
a = app.test_client()
a.post('/admin/login', data={'email': 'admin@pepito.com', 'password': 'admin123', 'csrf_token': tok(a, '/admin/login')})
h = body(a.get('/admin/pepito'))
ok('un dueño normal no ve el aviso', 'impersonation-bar' not in h)
r = a.post('/platform/volver', data={'csrf_token': tok(a, '/admin/pepito?section=agenda')})
ok('un dueño normal no puede "volver" a plataforma (lo manda al login)', '/platform/login' in r.headers.get('Location', '') and a.get('/platform/').status_code == 302)
b = app.test_client()
r = b.post(f'/platform/companies/{pep_id}/enter', data={})
ok('sin sesión no se puede "Entrar"', r.status_code in (302, 400))

print('— Mi cuenta y usuarios')
h = body(p.get('/platform/cuenta'))
ok('página Mi cuenta', 'Cambiar mi contraseña' in h and 'Usuarios de plataforma' in h)
T2 = lambda: tok(p, '/platform/cuenta')
r = p.post('/platform/cuenta/password', data={'current_password': 'mala', 'new_password': 'nueva12345', 'confirm_password': 'nueva12345', 'csrf_token': T2()}, follow_redirects=True)
ok('contraseña actual incorrecta se rechaza', 'no es correcta' in body(r))
r = p.post('/platform/cuenta/password', data={'current_password': 'owner12345', 'new_password': 'nueva12345', 'confirm_password': 'otra', 'csrf_token': T2()}, follow_redirects=True)
ok('confirmación distinta se rechaza', 'no coinciden' in body(r))
r = p.post('/platform/cuenta/password', data={'current_password': 'owner12345', 'new_password': 'nueva12345', 'confirm_password': 'nueva12345', 'csrf_token': T2()}, follow_redirects=True)
ok('cambia la contraseña y sigue con la sesión abierta', 'Contraseña actualizada' in body(r) and p.get('/platform/').status_code == 200)
x = app.test_client()
r = x.post('/platform/login', data={'email': email, 'password': 'nueva12345', 'csrf_token': tok(x, '/platform/login')})
ok('entra con la contraseña nueva', r.status_code == 302 and x.get('/platform/').status_code == 200)
r = p.post('/platform/cuenta/usuarios', data={'name': 'Socio', 'email': 'Socio@Turnex.com', 'password': 'socio12345', 'csrf_token': T2()}, follow_redirects=True)
with app.app_context(): socio = PlatformUser.query.filter_by(email='socio@turnex.com').first(); sid = socio and socio.id
ok('agrega un usuario de plataforma', sid and 'socio@turnex.com' in body(r))
r = p.post('/platform/cuenta/usuarios', data={'name': 'Socio', 'email': 'socio@turnex.com', 'password': 'socio12345', 'csrf_token': T2()}, follow_redirects=True)
ok('no duplica el email', 'Ya existe' in body(r))
s = app.test_client()
s.post('/platform/login', data={'email': 'socio@turnex.com', 'password': 'socio12345', 'csrf_token': tok(s, '/platform/login')})
ok('el socio puede entrar', s.get('/platform/').status_code == 200)
p.post(f'/platform/cuenta/usuarios/{sid}/toggle', data={'csrf_token': T2()})
ok('al desactivarlo se le cierra la sesión', s.get('/platform/').status_code == 302)
with app.app_context(): me = PlatformUser.query.filter_by(email=email).first().id
r = p.post(f'/platform/cuenta/usuarios/{me}/toggle', data={'csrf_token': T2()}, follow_redirects=True)
with app.app_context(): ok('no te podés desactivar a vos mismo', PlatformUser.query.get(me).active and 'propio usuario' in body(r))

print('— Pagos')
r = p.post(f'/platform/companies/{pep_id}/payments', data={'amount': '0', 'csrf_token': T()}, follow_redirects=True)
ok('pago en cero se rechaza', 'mayor a cero' in body(r))
r = p.post(f'/platform/companies/{pep_id}/payments', data={'amount': '15000', 'method': 'Transferencia', 'status': 'PAID', 'csrf_token': T()}, follow_redirects=True)
ok('registra el pago', 'Pago registrado para Pepito Studio' in body(r))

print('— Links reservados y fechas inválidas')
from app.utils import is_reserved_slug
with app.app_context():
    ok('rutas del sistema reservadas', all(is_reserved_slug(x) for x in ('admin', 'platform', 'registrar', 'api', 'static', 'terminos', 'www')) and not is_reserved_slug('pepito'))
a = app.test_client()
a.post('/admin/login', data={'email': 'admin@pepito.com', 'password': 'admin123', 'csrf_token': tok(a, '/admin/login')})
ok('agenda con fecha inválida no da error 500', a.get('/admin/pepito?section=agenda&day=2026-13-45').status_code == 200)
ok('agenda con fecha basura no da error 500', a.get('/admin/pepito?section=agenda&day=hola').status_code == 200)
with app.app_context():
    svc = Service.query.filter_by(company_id=pep_id, active=True).first().id
c = app.test_client()
ok('disponibilidad del día con fecha inválida responde 400', c.get(f'/api/pepito/availability/day?service_id={svc}&date=2026-02-31').status_code == 400)
ok('disponibilidad del mes con mes 13 responde 400', c.get(f'/api/pepito/availability/month?service_id={svc}&year=2026&month=13').status_code == 400)
ok('disponibilidad del día normal sigue andando', c.get(f'/api/pepito/availability/day?service_id={svc}&date=2026-10-05').status_code == 200)
t = tok(a, '/admin/pepito?section=blocked')
r = a.post('/admin/pepito/blocked', data={'start_date': '2026-99-01', 'start_time': '10:00', 'end_date': '2026-10-01', 'end_time': '25:99', 'csrf_token': t}, follow_redirects=True)
ok('bloqueo con fecha inválida avisa en vez de romper', r.status_code == 200 and 'rango horario válido' in body(r))

print('— Landing')
h = body(app.test_client().get('/'))
ok('la landing ya no promete WhatsApp en recordatorios', 'Recordatorios automáticos por WhatsApp' not in h)
pro = h[h.find('>PRO<'):]
ok('"Todo lo del plan BASE" va primero en PRO', pro.find('Todo lo del plan BASE') != -1 and pro.find('Todo lo del plan BASE') < pro.find('5 profesionales'))

print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
