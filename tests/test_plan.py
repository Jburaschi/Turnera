import re, logging
from datetime import datetime, timedelta
from app import create_app
from app.extensions import db, limiter
from app.models import *
app = create_app(); limiter.enabled = False
mails = []
class H(logging.Handler):
    def emit(self, r):
        m = r.getMessage()
        if '[EMAIL' in m: mails.append(m)
app.logger.addHandler(H()); app.logger.setLevel(logging.INFO)
res = []
def ok(n, c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
def tok(c, url): return re.search(r'name="csrf_token" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)

# ── 30 días y plan de la landing
for q, esperado in (('?plan=PRO', 'PRO'), ('?plan=premium', 'PREMIUM'), ('?plan=GRATIS', 'BASE'), ('', 'BASE')):
    c = app.test_client(); url = '/registrar' + q
    html = c.get(url).get_data(as_text=True); t = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    email = f'r{len(q)}{esperado}@x.com'.lower()
    c.post(url, data={'full_name': 'Ana', 'email': email, 'password': '12345678', 'terms': 'on', 'csrf_token': t, 'plan': re.search(r'name="plan" value="([^"]*)"', html).group(1)})
    with app.app_context():
        co = AdminUser.query.filter_by(email=email).first().company
        dias = (co.trial_expires_at - datetime.utcnow()).days
    ok(f'registro {url or "/registrar"} → plan {co.plan_name}, TRIAL de {dias + 1} días', co.plan_name == esperado and co.plan_status == 'TRIAL' and dias in (29, 30))
ok('el formulario dice "30 días gratis del plan PRO"', '30 días gratis del plan PRO' in app.test_client().get('/registrar?plan=PRO').get_data(as_text=True))

# ── Mi plan
a = app.test_client(); t = tok(a, '/admin/login')
a.post('/admin/login', data={'email': 'admin@pepito.com', 'password': 'admin123', 'csrf_token': t})
h = a.get('/admin/pepito?section=plan').get_data(as_text=True)
ok('sección "Mi plan" muestra plan actual y los dos formularios', 'Plan actual' in h and 'Pedir cambio de plan' in h and 'Pedir la baja' in h)
ok('"Ver mi plan" lleva a la sección plan', 'section=plan">Ver mi plan' in a.get('/admin/pepito').get_data(as_text=True))
t = tok(a, '/admin/pepito?section=plan')
with app.app_context(): actual = Company.query.filter_by(slug='pepito').first().plan_name
r = a.post('/admin/pepito/plan/request', data={'kind': 'CHANGE', 'requested_plan': actual, 'csrf_token': t}, follow_redirects=True)
ok(f'pedir el mismo plan ({actual}) → aviso', f'Ya estás en el plan {actual}' in r.get_data(as_text=True))
r = a.post('/admin/pepito/plan/request', data={'kind': 'CHANGE', 'requested_plan': 'ORO', 'csrf_token': t}, follow_redirects=True)
ok('plan inexistente → error', 'Elegí un plan válido' in r.get_data(as_text=True))
mails.clear()
r = a.post('/admin/pepito/plan/request', data={'kind': 'CHANGE', 'requested_plan': 'PREMIUM', 'message': 'Queremos soporte', 'csrf_token': t}, follow_redirects=True)
with app.app_context(): reqs = PlanRequest.query.filter_by(kind='CHANGE').all()
ok('pedido de cambio registrado', len(reqs) == 1 and reqs[0].requested_plan == 'PREMIUM' and reqs[0].current_plan == actual and reqs[0].message == 'Queremos soporte')
ok('mail a plataforma con los datos del pedido', mails and 'owner@turnex.com' in mails[-1] and 'Cambio de plan' in mails[-1] and 'PREMIUM' in mails[-1] and 'Queremos soporte' in mails[-1])
ok('la sección muestra el pedido pendiente y no deja repetirlo', 'Ya pediste pasar al plan PREMIUM' in r.get_data(as_text=True))
r = a.post('/admin/pepito/plan/request', data={'kind': 'CHANGE', 'requested_plan': 'BASE', 'csrf_token': t}, follow_redirects=True)
with app.app_context(): n = PlanRequest.query.filter_by(kind='CHANGE').count()
ok('segundo pedido de cambio mientras hay uno pendiente → no se duplica', n == 1 and 'Ya tenés un pedido igual pendiente' in r.get_data(as_text=True))
r = a.post('/admin/pepito/plan/request', data={'kind': 'CANCEL', 'csrf_token': t}, follow_redirects=True)
with app.app_context(): n = PlanRequest.query.filter_by(kind='CANCEL').count()
ok('baja sin tildar la confirmación → no se registra', n == 0 and 'confirmá que querés dar de baja' in r.get_data(as_text=True))
mails.clear()
r = a.post('/admin/pepito/plan/request', data={'kind': 'CANCEL', 'confirm': 'on', 'message': 'Cierro el local', 'csrf_token': t}, follow_redirects=True)
with app.app_context():
    n = PlanRequest.query.filter_by(kind='CANCEL').count(); co = Company.query.filter_by(slug='pepito').first()
ok('baja confirmada → pedido registrado y la cuenta sigue activa', n == 1 and co.active and 'Recibimos tu pedido de baja' in r.get_data(as_text=True))
ok('mail de baja a plataforma', mails and 'Baja de la cuenta' in mails[-1] and 'Cierro el local' in mails[-1])

# ── staff
with app.app_context():
    co = Company.query.filter_by(slug='pepito').first()
    st = AdminUser(company=co, email='st@pepito.com', name='St', role='staff'); st.set_password('staff1234'); db.session.add(st); db.session.commit()
s = app.test_client(); t2 = tok(s, '/admin/login'); s.post('/admin/login', data={'email': 'st@pepito.com', 'password': 'staff1234', 'csrf_token': t2})
r = s.get('/admin/pepito?section=plan', follow_redirects=True).get_data(as_text=True)
ok('staff no ve "Mi plan"', 'Pedir la baja' not in r)
t2 = tok(s, '/admin/pepito?section=agenda')
s.post('/admin/pepito/plan/request', data={'kind': 'CANCEL', 'confirm': 'on', 'csrf_token': t2})
with app.app_context(): n = PlanRequest.query.filter_by(kind='CANCEL').count()
ok('staff no puede pedir la baja', n == 1)

# ── plataforma
p = app.test_client(); t3 = tok(p, '/platform/login')
with app.app_context():
    u = PlatformUser.query.first(); u.set_password('owner12345'); db.session.commit(); email = u.email
p.post('/platform/login', data={'email': email, 'password': 'owner12345', 'csrf_token': t3})
h = p.get('/platform/').get_data(as_text=True)
ok('plataforma lista los 2 pedidos pendientes', 'Pedidos de plan y bajas' in h and '2 pendientes' in h and 'Cierro el local' in h)
with app.app_context(): rid = PlanRequest.query.filter_by(kind='CHANGE').first().id
t3 = tok(p, '/platform/')
p.post(f'/platform/plan-requests/{rid}/resolve', data={'csrf_token': t3})
with app.app_context(): st_ = db.session.get(PlanRequest, rid).status
h = p.get('/platform/').get_data(as_text=True)
ok('marcar como resuelto', st_ == 'DONE' and '1 pendiente' in h)
t = tok(a, '/admin/pepito?section=plan')
ok('con el pedido resuelto, se puede volver a pedir cambio', 'Pedir cambio de plan' in a.get('/admin/pepito?section=plan').get_data(as_text=True))

# ── prueba vencida: "Mi plan" sigue accesible
with app.app_context():
    co = Company.query.filter_by(slug='pepito').first(); co.plan_status = 'TRIAL'; co.trial_expires_at = datetime.utcnow() - timedelta(days=2); db.session.commit()
r = a.get('/admin/pepito?section=agenda')
ok('prueba vencida: la agenda redirige al bloqueo', r.status_code == 302 and 'plan-bloqueado' in r.headers['Location'])
bl = a.get('/admin/pepito/plan-bloqueado').get_data(as_text=True)
ok('la pantalla de bloqueo ofrece "Elegir un plan"', 'Elegir un plan' in bl and 'section=plan' in bl)
r = a.get('/admin/pepito?section=plan')
ok('prueba vencida: "Mi plan" abre', r.status_code == 200 and 'La prueba venció el' in r.get_data(as_text=True))
t = tok(a, '/admin/pepito?section=plan')
a.post('/admin/pepito/plan/request', data={'kind': 'CHANGE', 'requested_plan': 'PREMIUM', 'csrf_token': t})
with app.app_context(): n = PlanRequest.query.filter_by(kind='CHANGE', status='PENDING', requested_plan='PREMIUM').count()
ok('prueba vencida: puede pedir cambiar de plan', n == 1)
print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
