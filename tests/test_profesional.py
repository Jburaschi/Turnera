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
with app.app_context():
    c = Company.query.filter_by(slug='pepito').first(); c.plan_name = 'PREMIUM'; c.plan_status = 'ACTIVE'; c.trial_expires_at = None; db.session.commit()
    svcs = [s.id for s in c.services]
a = app.test_client()
a.post('/admin/login', data={'email': 'admin@pepito.com', 'password': 'admin123', 'csrf_token': tok(a, '/admin/login')})
L = '/admin/pepito?section=professionals'

print('— Listado')
h = body(a.get(L))
ok('"Nuevo profesional" lleva a la vista dedicada', 'section=professionals&amp;pro=new' in h)
ok('ya no hay formularios dentro del listado', 'id="new-employee-form"' not in h and 'update' not in h.split('admin-table')[1][:20000] and 'block_0_weekday' not in h)
ok('cada profesional tiene "Editar" que abre su vista', re.search(r'pro=\d+" title="Editar"', h))
ok('se sacó el texto falso de arrastrar y soltar', 'arrastrar y soltar' not in h)

print('— Nuevo')
h = body(a.get(L + '&pro=new'))
ok('vista con migas, datos, prestaciones y horarios', 'Nuevo profesional' in h and 'Datos del profesional' in h and 'Prestaciones que realiza' in h and 'Horarios de atención' in h)
ok('acciones abajo: Cancelar y Crear profesional', 'class="pf-actions"' in h and '>Crear profesional<' in h and 'form="pro-form"' in h)
ok('mantiene el menú lateral', 'admin-sidebar' in h)
t = tok(a, L + '&pro=new')
data = {'name': 'Lucas', 'active': '1', 'bio': 'Barbero', 'service_ids': [str(svcs[0]), str(svcs[1])],
        'block_0_weekday': '0', 'block_0_start': '09:00', 'block_0_end': '13:00', 'block_0_service_ids': [str(svcs[0]), str(svcs[1])],
        'block_1_weekday': '0', 'block_1_start': '15:00', 'block_1_end': '19:00', 'block_1_service_ids': [str(svcs[0])],
        'csrf_token': t}
r = a.post('/admin/pepito/employees', data=data)
with app.app_context():
    e = Employee.query.filter_by(name='Lucas').first()
    sch = sorted(e.schedules, key=lambda s: s.start_time) if e else []
    ok('crea con dos franjas el mismo día', e and e.active and len(sch) == 2 and e.bio == 'Barbero')
    ok('franja con todas sus prestaciones queda sin límite', sch and sch[0].limited_services == [])
    ok('franja con una prestación queda limitada a esa', sch and [s.id for s in sch[1].limited_services] == [svcs[0]])
    lid = e.id
ok('vuelve al listado', r.status_code == 302 and 'pro=' not in r.headers['Location'])
t = tok(a, L + '&pro=new')
r = a.post('/admin/pepito/employees', data={'name': 'Sin horario', 'active': '1', 'block_0_weekday': '0', 'block_0_start': '18:00', 'block_0_end': '10:00', 'csrf_token': t})
ok('franja inválida vuelve al formulario de alta con aviso', 'pro=new' in r.headers['Location'] and 'franja horaria válida' in body(a.get(r.headers['Location'])))
t = tok(a, L + '&pro=new')
a.post('/admin/pepito/employees', data={'name': 'Inactivo', 'active': '0', 'block_0_weekday': '1', 'block_0_start': '10:00', 'block_0_end': '12:00', 'csrf_token': t})
with app.app_context(): ok('estado "Inactivo" se respeta', Employee.query.filter_by(name='Inactivo').first().active is False)

print('— Editar')
h = body(a.get(L + f'&pro={lid}'))
ok('vista de edición con datos cargados', 'Editar profesional' in h and 'value="Lucas"' in h and '>Barbero</textarea>' in h and '>Guardar cambios<' in h and 'Eliminar' in h)
ok('muestra las dos franjas', h.count('data-slot>') == 2 or h.count('class="pf-slot"') == 2)
t = tok(a, L + f'&pro={lid}')
r = a.post(f'/admin/pepito/employees/{lid}/update', data={'name': 'Lucas M', 'active': '0', 'service_ids': [str(svcs[0])],
        'block_0_weekday': '2', 'block_0_start': '10:00', 'block_0_end': '18:00', 'block_0_service_ids': [str(svcs[0])], 'csrf_token': t})
with app.app_context():
    e = db.session.get(Employee, lid)
    ok('guarda nombre, estado, prestaciones y horario', e.name == 'Lucas M' and e.active is False and [s.id for s in e.services] == [svcs[0]] and len(e.schedules) == 1 and e.schedules[0].weekday == 2)
t = tok(a, L + f'&pro={lid}')
r = a.post(f'/admin/pepito/employees/{lid}/update', data={'name': '', 'csrf_token': t})
ok('sin nombre vuelve a la edición', f'pro={lid}' in r.headers['Location'])
ok('profesional de otra empresa → 404', a.get(L + '&pro=999999').status_code == 404)

print('— Límite del plan')
with app.app_context():
    c = Company.query.filter_by(slug='pepito').first(); c.plan_name = 'BASE'; db.session.commit()
r = a.get(L + '&pro=new')
ok('BASE con el cupo lleno: "Nuevo" vuelve al listado con aviso', r.status_code == 302 and 'pro=' not in r.headers['Location'])
t = tok(a, L + f'&pro={lid}')
r = a.post(f'/admin/pepito/employees/{lid}/update', data={'name': 'Lucas M', 'active': '1', 'service_ids': [str(svcs[0])], 'block_0_weekday': '2', 'block_0_start': '10:00', 'block_0_end': '18:00', 'csrf_token': t})
with app.app_context(): ok('no deja activar desde la edición por encima del límite', db.session.get(Employee, lid).active is False)

print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
