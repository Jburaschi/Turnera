"""
Manejo de la hora en Turnex (la app funciona solo en Argentina).

Hay DOS tipos de fechas guardadas en la base, ambas sin zona horaria (naive):

1. Hora del negocio -> hora local de Argentina.
   Turnos (Appointment.start_dt/end_dt), bloqueos (BlockedPeriod), horarios
   (EmployeeSchedule), holds (SlotHold.start_dt/end_dt).
   Para compararlas con "ahora" usar SIEMPRE now_ar() / today_ar().

2. Marcas del sistema -> UTC.
   created_at, expires_at, reset_token_expires, trial_expires_at, paid_at,
   canceled_at. Se comparan con datetime.utcnow() y, para mostrarlas al
   usuario, se pasan por el filtro de plantillas `|hora_ar`.

Nunca usar datetime.now() ni date.today(): dependen de la zona horaria del
servidor (en Railway/Render es UTC, 3 horas adelantada respecto de Argentina).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

TZ_NAME = 'America/Argentina/Buenos_Aires'
TZ_AR = ZoneInfo(TZ_NAME)
TZ_LABEL = 'Argentina (GMT-3)'


def now_ar() -> datetime:
    """Hora actual de Argentina, naive (comparable con los turnos guardados)."""
    return datetime.now(TZ_AR).replace(tzinfo=None)


def today_ar() -> date:
    """Fecha de hoy en Argentina."""
    return now_ar().date()


def utc_to_ar(dt: datetime | None) -> datetime | None:
    """Convierte una marca del sistema (UTC naive) a hora de Argentina (naive)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ_AR).replace(tzinfo=None)


def parse_iso_date(raw, default=None):
    """'2026-09-27' -> date. Si viene vacío o mal escrito (ej. un link editado
    a mano), devuelve `default` en lugar de romper con un error 500."""
    raw = (raw or '').strip()
    if not raw:
        return default
    try:
        return datetime.strptime(raw[:10], '%Y-%m-%d').date()
    except ValueError:
        return default
