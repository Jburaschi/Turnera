import re, os, sqlite3, sys
from app import create_app
from app.extensions import db, limiter
from app.models import *
from app.utils import format_address, read_address_form
app = create_app(); limiter.enabled = False
res = []
def ok(n, c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
def tok(c, url): return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)
def body(r): return r.get_data(as_text=True)
def co(slug='pepito'): return Company.query.filter_by(slug=slug).first()

print('— Armado de la dirección')
d = {'address': 'Av. San Martín 1234', 'address_unit': '2º B', 'locality': 'Santos Lugares', 'partido': 'Tres de Febrero', 'province': 'Buenos Aires', 'postal_code': '1674'}
ok('para mostrar', format_address(d) == 'Av. San Martín 1234, 2º B, Santos Lugares, Tres de Febrero, Buenos Aires')
ok('para Maps: sin piso/depto y con CP', format_address(d, with_unit=False, with_postal=True) == 'Av. San Martín 1234, Santos Lugares, Tres de Febrero, Buenos Aires, 1674')
ok('no repite si localidad y partido son iguales', format_address({'address': 'Calle 1', 'locality': 'Pilar', 'partido': 'pilar', 'province': 'Buenos Aires'}) == 'Calle 1, Pilar, Buenos Aires')
v, e = read_address_form({'address': 'Calle 1'})
ok('calle sin localidad ni provincia → aviso', e and 'localidad' in e)
v, e = read_address_form({'address': '', 'locality': ''})
ok('sin dirección es válido', e is None and v['address'] is None)
v, e = read_address_form({'address': 'Calle 1', 'locality': 'X', 'province': 'Narnia'})
ok('provincia inventada se descarta', v['province'] is None and e)

print('— Perfil del negocio')
a = app.test_client()
a.post('/admin/login', data={'email': 'admin@pepito.com', 'password': 'admin123', 'csrf_token': tok(a, '/admin/login')})
h = body(a.get('/admin/pepito?section=company'))
ok('el perfil muestra los campos nuevos', all(f'name="{f}"' in h for f in ('address', 'address_unit', 'locality', 'partido', 'province', 'postal_code')) and 'Tierra del Fuego' in h)
with app.app_context(): c = co(); base = {'name': c.name, 'description': c.description or '', 'phone': c.phone or '', 'email': c.email or ''}
r = a.post('/admin/pepito/company', data={**base, **d, 'csrf_token': tok(a, '/admin/pepito?section=company')}, follow_redirects=True)
with app.app_context():
    c = co(); ok('guarda todas las partes', (c.address, c.address_unit, c.locality, c.partido, c.province, c.postal_code) == tuple(d.values()))
h = body(app.test_client().get('/pepito'))
ok('página pública muestra la dirección completa', 'Av. San Martín 1234, 2º B' in h and 'Santos Lugares, Tres de Febrero, Buenos Aires, Argentina' in h)
ok('"Cómo llegar" busca calle, localidad, partido, provincia y CP (sin depto)', 'query=Av.%20San%20Mart%C3%ADn%201234%2C%20Santos%20Lugares%2C%20Tres%20de%20Febrero%2C%20Buenos%20Aires%2C%201674%2C%20Argentina' in h)
r = a.post('/admin/pepito/company', data={**base, 'address': 'Otra 55', 'locality': '', 'province': '', 'csrf_token': tok(a, '/admin/pepito?section=company')}, follow_redirects=True)
ok('calle sin localidad: guarda y avisa', 'Completá la localidad y la provincia' in body(r))
r = a.post('/admin/pepito/company', data={'csrf_token': tok(a, '/admin/pepito?section=company')}, follow_redirects=True)
with app.app_context(): ok('el form del logo no borra la dirección', co().address == 'Otra 55')

print('— Alta guiada')
n = app.test_client()
t = tok(n, '/registrar')
n.post('/registrar', data={'full_name': 'Ana', 'email': 'ana@x.com', 'password': 'clave1234', 'accept_terms': 'on', 'terms': 'on', 'csrf_token': t}, follow_redirects=True)
h = body(n.get('/registrar/negocio'))
ok('el paso del negocio tiene los campos nuevos', 'name="locality"' in h and 'name="province"' in h)
t = tok(n, '/registrar/negocio')
r = n.post('/registrar/negocio', data={'name': 'Barbería Ana', 'category': re.search(r'<option value="([^"]+)"\s*>', h).group(1), 'address': 'Belgrano 10', 'csrf_token': t}, follow_redirects=True)
ok('calle sin localidad no avanza y muestra el aviso', 'Completá la localidad y la provincia' in body(r) and 'value="Belgrano 10"' in body(r))
t = tok(n, '/registrar/negocio')
cat = re.search(r'<option value="([^"]+)"\s*>', h).group(1)
r = n.post('/registrar/negocio', data={'name': 'Barbería Ana', 'category': cat, 'address': 'Belgrano 10', 'locality': 'Morón', 'province': 'Buenos Aires', 'csrf_token': t})
with app.app_context():
    c = Company.query.filter_by(name='Barbería Ana').first()
    ok('con localidad y provincia avanza y guarda', r.status_code == 302 and c and c.locality == 'Morón' and c.province == 'Buenos Aires')
t = tok(n, '/registrar/negocio')
r = n.post('/registrar/negocio', data={'name': 'Barbería Ana', 'category': cat, 'csrf_token': t})
ok('sin dirección también avanza (es opcional)', r.status_code == 302)

print('— Plataforma')
p = app.test_client()
with app.app_context():
    u = PlatformUser.query.first(); u.set_password('owner12345'); db.session.commit(); email = u.email
p.post('/platform/login', data={'email': email, 'password': 'owner12345', 'csrf_token': tok(p, '/platform/login')})
h = body(p.get('/platform/'))
ok('alta y edición con los campos nuevos', h.count('name="locality"') >= 2)
r = p.post('/platform/companies', data={'name': 'Spa Sur', 'admin_email': 'sur@x.com', 'admin_password': 'clave1234', 'plan_name': 'BASE', 'plan_status': 'TRIAL', 'active': 'on', 'address': 'Mitre 5', 'locality': 'Quilmes', 'province': 'Buenos Aires', 'csrf_token': tok(p, '/platform/')}, follow_redirects=True)
with app.app_context(): c = co('spa-sur'); ok('crea con dirección completa', c and c.locality == 'Quilmes')

print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
