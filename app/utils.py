from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit


def format_ars(amount) -> str:
    """Formato de pesos argentinos: 1500 -> '$ 1.500' · 1500.5 -> '$ 1.500,50'."""
    value = float(amount or 0)
    if value == int(value):
        txt = f'{int(value):,}'.replace(',', '.')
    else:
        txt = f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'$ {txt}'


DIAS_CORTOS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
MESES_CORTOS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


def dia_corto(dt) -> str:
    """Día de la semana abreviado en español (strftime('%a') depende del
    idioma del servidor y salía en inglés: 'Sun', 'Mon'...)."""
    return DIAS_CORTOS[dt.weekday()] if dt else ''


def mes_corto(dt) -> str:
    """Mes abreviado en español ('Ago', 'Dic'...)."""
    return MESES_CORTOS[dt.month - 1] if dt else ''


def clean_public_url(raw, allow_local_media: bool = False):
    """Valida un link que se va a mostrar en una página pública (redes, logo).
    Devuelve (url_normalizada | None, mensaje_de_error | None).
    - Vacío → (None, None): se borra el campo.
    - Sin esquema ("instagram.com/x") → se completa con https://.
    - Solo se aceptan http:// y https:// con dominio. Cualquier otra cosa
      (javascript:, data:, texto suelto) se rechaza: un href javascript: se
      ejecutaría en el navegador de quien visita la página.
    - allow_local_media: acepta además /media/<id> (logos subidos a la app)."""
    value = (raw or '').strip()
    if not value:
        return None, None
    if any(ord(ch) < 32 or ch.isspace() for ch in value):
        return None, 'El link no puede tener espacios.'
    if allow_local_media and value.startswith('/media/') and value[7:].isdigit():
        return value, None
    if '://' not in value and not value.lower().startswith(('javascript:', 'data:', 'vbscript:', 'mailto:')):
        value = 'https://' + value
    parts = urlsplit(value)
    if parts.scheme.lower() not in ('http', 'https') or not parts.netloc or '.' not in parts.netloc:
        return None, 'El link tiene que empezar con https:// (ej: https://instagram.com/tu_negocio).'
    return value, None


def safe_url(value) -> str:
    """Filtro de plantillas: devuelve el link solo si es http(s) (o /media/),
    para no mostrar como link un dato viejo inválido guardado antes de la validación."""
    url, err = clean_public_url(value, allow_local_media=True)
    return url or ''


def css_color(value, default: str = '#3654f0') -> str:
    """Filtro de plantillas: devuelve el color solo si es un hex #rrggbb
    (se usa dentro de un atributo style; cualquier otra cosa → color por defecto)."""
    import re
    value = (value or '').strip()
    return value if re.fullmatch(r'#[0-9a-fA-F]{6}', value) else default


# ── Links de negocios (slug) ────────────────────────────────────────────────
# Nombres que no puede tomar un negocio porque chocan con páginas del sistema
# o pueden confundir a los clientes. A esto se suman, en tiempo de ejecución,
# todas las rutas de primer nivel de la app (admin, platform, registrar, …).
RESERVED_SLUGS = {
    'admin', 'administrador', 'api', 'app', 'ayuda', 'blog', 'contacto', 'cuenta',
    'dashboard', 'demo', 'directory', 'directorio', 'faq', 'help', 'internal',
    'login', 'logout', 'mail', 'media', 'panel', 'planes', 'platform', 'plataforma',
    'precios', 'preguntas-frecuentes', 'privacidad', 'registrar', 'registro',
    'salir', 'signup', 'soporte', 'static', 'support', 'terminos', 'turnex', 'www',
}


def slugify(text: str) -> str:
    """'Peluquería Pepe' -> 'peluqueria-pepe' (solo a-z, 0-9 y guiones)."""
    s = unicodedata.normalize('NFD', (text or '').lower().strip())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9\s-]', '', s.replace('_', '-'))
    s = re.sub(r'\s+', '-', s)
    s = re.sub(r'-+', '-', s)
    return s[:50].strip('-')


def is_reserved_slug(slug: str) -> bool:
    slug = (slug or '').strip().lower()
    if slug in RESERVED_SLUGS:
        return True
    try:
        from flask import current_app
        for rule in current_app.url_map.iter_rules():
            first = rule.rule.split('/')[1] if rule.rule.count('/') else ''
            if first and not first.startswith('<') and first == slug:
                return True
    except RuntimeError:
        pass
    return False


# ── Dirección del negocio ───────────────────────────────────────────────────
PROVINCIAS_AR = (
    'Ciudad Autónoma de Buenos Aires', 'Buenos Aires', 'Catamarca', 'Chaco', 'Chubut',
    'Córdoba', 'Corrientes', 'Entre Ríos', 'Formosa', 'Jujuy', 'La Pampa', 'La Rioja',
    'Mendoza', 'Misiones', 'Neuquén', 'Río Negro', 'Salta', 'San Juan', 'San Luis',
    'Santa Cruz', 'Santa Fe', 'Santiago del Estero', 'Tierra del Fuego', 'Tucumán',
)
ADDRESS_FIELDS = ('address', 'address_unit', 'locality', 'partido', 'province', 'postal_code')
_ADDRESS_MAX = {'address': 255, 'address_unit': 60, 'locality': 120, 'partido': 120,
                'province': 60, 'postal_code': 12}


def format_address(obj, with_unit=True, with_postal=False) -> str:
    """Une las partes de la dirección sin repetir (ej. localidad == partido)."""
    get = (obj.get if isinstance(obj, dict) else lambda k: getattr(obj, k, None))
    parts = [get('address')]
    if with_unit:
        parts.append(get('address_unit'))
    parts += [get('locality'), get('partido'), get('province')]
    if with_postal:
        parts.append(get('postal_code'))
    out, seen = [], set()
    for p in parts:
        p = (p or '').strip()
        if p and p.lower() not in seen:
            out.append(p)
            seen.add(p.lower())
    return ', '.join(out)


def read_address_form(form):
    """Lee los campos de dirección de un formulario.
    Devuelve (valores, error). Todo es opcional, pero si se carga la calle hay
    que indicar localidad y provincia para que Google Maps lo encuentre."""
    values = {}
    for f in ADDRESS_FIELDS:
        v = (form.get(f) or '').strip()[:_ADDRESS_MAX[f]]
        values[f] = v or None
    if values['province'] and values['province'] not in PROVINCIAS_AR:
        values['province'] = None
    error = None
    if values['address'] and (not values['locality'] or not values['province']):
        error = 'Completá la localidad y la provincia para que Google Maps encuentre el negocio.'
    return values, error


def apply_address(company, values):
    for f in ADDRESS_FIELDS:
        setattr(company, f, values[f])


# ── Teléfono → links de llamada y WhatsApp ──────────────────────────────────
def phone_digits(phone) -> str:
    return re.sub(r'\D', '', phone or '')


def whatsapp_number(phone) -> str | None:
    """Número para wa.me en formato internacional argentino (549 + área + número).
    Acepta '11 5555-1234', '011 5555-1234', '+54 11 5555-1234', '+54 9 11 5555-1234'.
    Devuelve None si no parece un celular argentino válido."""
    d = phone_digits(phone)
    if d.startswith('00'):
        d = d[2:]
    if d.startswith('549'):
        rest = d[3:]
    elif d.startswith('54'):
        rest = d[2:]
    else:
        rest = d[1:] if d.startswith('0') else d
    if rest.startswith('0'):
        rest = rest[1:]
    # El "15" de los celulares viejos va después del código de área: 11 15 5555-1234
    if len(rest) == 12:
        for area_len in (2, 3, 4):
            if rest[area_len:area_len + 2] == '15':
                rest = rest[:area_len] + rest[area_len + 2:]
                break
    if len(rest) != 10:
        return None
    return '549' + rest


def tel_href(phone) -> str | None:
    """Número para un link tel:. Si es un número argentino reconocible lo pasa a
    +54 (área + número, sin el 9 de WhatsApp); si no, deja los dígitos."""
    wa = whatsapp_number(phone)
    if wa:
        return '+54' + wa[3:]
    d = phone_digits(phone)
    if len(d) < 6:
        return None
    return ('+' if (phone or '').strip().startswith('+') else '') + d
