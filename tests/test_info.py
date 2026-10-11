import re
from app import create_app
from app.extensions import db, limiter
from app.models import *
from app.utils import whatsapp_number, tel_href
app = create_app(); limiter.enabled = False
res = []
def ok(n, c): res.append(bool(c)); print(('PASS ' if c else 'FAIL ') + n)
def page():
    h = app.test_client().get('/pepito').get_data(as_text=True)
    i = h.find('class="cp-info'); j = h.find('id="servicios"')
    return h[i:j] if i != -1 else ''
def setc(**kw):
    with app.app_context():
        c = Company.query.filter_by(slug='pepito').first()
        for k, v in kw.items():
            if k.startswith('cfg_'): setattr(c.config, k[4:], v)
            else: setattr(c, k, v)
        db.session.commit()

print('— Números')
ok('WhatsApp con 15 y 0', whatsapp_number('011 15 5555-1234') == '5491155551234')
ok('WhatsApp de Rosario', whatsapp_number('(0341) 15 555-1234') == '5493415551234')
ok('número corto no es WhatsApp', whatsapp_number('111111') is None)
ok('tel con +54', tel_href('11 5555-1234') == '+541155551234')

from datetime import time
with app.app_context():
    cid = Company.query.filter_by(slug='pepito').first().id
    for d in range(5): db.session.add(CompanyHours(company_id=cid, weekday=d, start_time=time(10), end_time=time(20)))
    db.session.add(CompanyHours(company_id=cid, weekday=5, start_time=time(10), end_time=time(14)))
    db.session.commit()
print('— Widget completo')
setc(address='Vedia 687', address_unit=None, locality='Núñez', partido=None, province='Ciudad Autónoma de Buenos Aires', postal_code=None, phone='11 5555-1234', email='hola@x.com', cfg_show_address_public=True, cfg_show_phone_public=True, cfg_show_email_public=True)
h = page()
ok('tres bloques', 'cp-info--3' in h and h.count('class="cp-info-block"') == 3)
ok('calle arriba y "Núñez, CABA, Argentina" abajo', '<strong class="cp-info-main">Vedia 687</strong>' in h and 'Núñez, CABA, Argentina' in h)
ok('Cómo llegar abre Google Maps con la dirección y Argentina', 'google.com/maps/search/?api=1&query=Vedia%20687%2C%20N%C3%BA%C3%B1ez%2C%20Ciudad%20Aut%C3%B3noma%20de%20Buenos%20Aires%2C%20Argentina' in h and 'target="_blank"' in h)
ok('horarios en filas: Lun a Vie y Sábados', h.count('class="cp-hours-row"') == 2 and '<dt>Lun a Vie</dt>' in h and '10:00 - 20:00' in h and '<dt>Sábados</dt>' in h and '10:00 - 14:00' in h)
ok('sin botón de llamar', 'tel:' not in h and 'Llamar' not in h and 'Atención por WhatsApp.' in h)
ok('WhatsApp con número internacional y mensaje', 'href="https://wa.me/5491155551234?text=Hola%20Pepito%20Studio' in h)
ok('el email ya no va en la tarjeta', 'hola@x.com' not in h)

setc(address='vedia 687', locality=None, province=None)
h = page()
ok('cuenta vieja sin localidad: "Vedia 687" y "Argentina"', '<strong class="cp-info-main">Vedia 687</strong>' in h and '<span class="cp-info-sub">Argentina</span>' in h and 'query=vedia%20687%2C%20Argentina' in h)
setc(address='Vedia 687', locality='Núñez', province='Ciudad Autónoma de Buenos Aires')
print('— Casos')
setc(phone='111111')
h = page()
ok('número corto: igual muestra WhatsApp y no "Llamar"', 'href="https://wa.me/111111?text=' in h and 'Llamar' not in h)
setc(phone='11 5555-1234', cfg_show_address_public=False)
h = page()
ok('dirección oculta: dos bloques', 'cp-info--2' in h and 'Cómo llegar' not in h)
setc(cfg_show_phone_public=False, cfg_show_email_public=False, instagram_url=None, facebook_url=None)
h = page()
ok('sin contacto ni dirección: solo horarios', 'cp-info--1' in h and 'Contacto' not in h)
setc(cfg_show_address_public=True, address=None)
h = page()
ok('dirección vacía no muestra el bloque', 'Dirección' not in h)
with app.app_context():
    CompanyHours.query.filter_by(company_id=Company.query.filter_by(slug='pepito').first().id).delete(); db.session.commit()
h = app.test_client().get('/pepito').get_data(as_text=True)
ok('sin nada para mostrar no hay tarjeta vacía', 'class="cp-info' not in h and app.test_client().get('/pepito').status_code == 200)

print('RESULTADO', 'TODO OK' if all(res) else f'{res.count(False)} FALLAS')
