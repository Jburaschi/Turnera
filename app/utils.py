from __future__ import annotations

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
