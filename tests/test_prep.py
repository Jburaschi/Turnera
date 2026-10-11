import os, re, sys, subprocess, json, tempfile
MODE = sys.argv[1] if len(sys.argv) > 1 else 'web'
if MODE == 'seed':
    # corre en procesos separados con distintas variables
    code = "from app import create_app; from app.models import Company, PlatformUser; app=create_app()\nwith app.app_context(): print(Company.query.count(), PlatformUser.query.count())"
    for label, env in [('desarrollo', {}), ('producción', {'FLASK_ENV':'production','SECRET_KEY':'x'*32}), ('producción + SEED_DEMO=1', {'FLASK_ENV':'production','SECRET_KEY':'x'*32,'SEED_DEMO':'1'})]:
        db = os.path.join(tempfile.gettempdir(), f'turnex_seed_{os.getpid()}_{len(env)}.db')
        if os.path.exists(db): os.remove(db)
        out = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'PYTHONPATH': '.', 'DATABASE_URL': 'sqlite:///' + db, **env}, capture_output=True, text=True).stdout.strip().splitlines()[-1]
        companies, owners = map(int, out.split())
        esperado = 0 if label == 'producción' else 1
        print(('PASS' if companies == esperado and owners == 1 else 'FAIL') + f' {label}: {companies} negocio(s) demo, {owners} usuario de plataforma')
    sys.exit(0)

from app import create_app
from app.extensions import db, limiter
from app.models import *
from app.utils import clean_public_url
app = create_app(); limiter.enabled = False
res = []
def ok(n, c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
def tok(c, url):
    return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)

casos = {'javascript:alert(1)': None, 'JavaScript:alert(1)': None, 'data:text/html,x': None, 'java script:x': None,
         'instagram.com/pepito': 'https://instagram.com/pepito', 'https://www.facebook.com/pepito': 'https://www.facebook.com/pepito',
         'http://instagram.com/x': 'http://instagram.com/x', '': None, 'hola': None}
for raw, esperado in casos.items():
    got, err = clean_public_url(raw)
    ok(f'validación {raw!r} → {got!r}', got == esperado and (err is None) == (esperado is not None or raw == ''))

a = app.test_client(); t = tok(a, '/admin/login')
a.post('/admin/login', data={'email': 'admin@pepito.com', 'password': 'admin123', 'csrf_token': t})
t = tok(a, '/admin/pepito?section=company')
r = a.post('/admin/pepito/company', data={'target_section': 'company', 'name': 'Pepito Studio', 'instagram_url': 'javascript:alert(document.cookie)', 'facebook_url': '', 'csrf_token': t}, follow_redirects=True)
with app.app_context(): co = Company.query.filter_by(slug='pepito').first(); ig = co.instagram_url
ok('panel: javascript: en Instagram se rechaza con mensaje', 'Instagram: El link tiene que empezar con https://' in r.get_data(as_text=True) and not (ig or '').startswith('javascript'))
r = a.post('/admin/pepito/company', data={'target_section': 'company', 'name': 'Pepito Studio', 'instagram_url': 'instagram.com/pepitostudio', 'facebook_url': '', 'csrf_token': t}, follow_redirects=True)
with app.app_context(): co = Company.query.filter_by(slug='pepito').first(); ig, fb = co.instagram_url, co.facebook_url
ok(f'panel: "instagram.com/pepitostudio" se guarda como {ig!r}', ig == 'https://instagram.com/pepitostudio' and fb is None)
# dato viejo inválido cargado antes del arreglo
with app.app_context():
    co = Company.query.filter_by(slug='pepito').first(); co.facebook_url = 'javascript:alert(1)'; db.session.commit()
html = app.test_client().get('/pepito').get_data(as_text=True)
ok('página pública: un link viejo javascript: no se muestra', 'javascript:' not in html and 'https://instagram.com/pepitostudio' in html)
# plataforma
p = app.test_client(); t = tok(p, '/platform/login')
with app.app_context():
    u = PlatformUser.query.first(); u.set_password('owner12345'); db.session.commit(); email = u.email
p.post('/platform/login', data={'email': email, 'password': 'owner12345', 'csrf_token': t})
t = tok(p, '/platform/')
r = p.post('/platform/companies', data={'name': 'X', 'slug': 'x-test', 'admin_email': 'a@x.com', 'admin_password': '12345678', 'logo_url': 'javascript:alert(1)', 'active': 'on', 'csrf_token': t}, follow_redirects=True)
with app.app_context(): creada = Company.query.filter_by(slug='x-test').first()
ok('plataforma: logo javascript: se rechaza y no crea la empresa', creada is None and 'Logo:' in r.get_data(as_text=True))
r = p.post('/platform/companies', data={'name': 'X', 'slug': 'x-test', 'admin_email': 'a@x.com', 'admin_password': '12345678', 'logo_url': 'https://cdn.ejemplo.com/logo.png', 'active': 'on', 'csrf_token': t}, follow_redirects=True)
with app.app_context(): creada = Company.query.filter_by(slug='x-test').first()
ok('plataforma: logo https válido se guarda', creada is not None and creada.logo_url == 'https://cdn.ejemplo.com/logo.png')
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
