"""Feriados nacionales de Argentina, automáticos para todos los negocios.

Salen de la librería `holidays` (no usa internet). Los "días no laborables"
optativos como Jueves Santo NO se cuentan como feriado: el negocio decide.
Cada negocio puede abrir un feriado puntual desde Bloqueos; eso se guarda
en HolidayOptOut y ese día vuelve a ofrecer turnos.

Los feriados trasladables y los "con fines turísticos" se definen año a año:
cuando el gobierno los anuncia, alcanza con actualizar la versión de
`holidays` en requirements.txt.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache

# Días no laborables (optativos): no cierran la agenda automáticamente
_NOT_HOLIDAYS = ('jueves santo',)


@lru_cache(maxsize=16)
def national_holidays(year: int) -> dict:
    """{date: 'Día de la Independencia', ...} para ese año."""
    try:
        import holidays as _h
        raw = _h.country_holidays('AR', years=year, language='es')
    except Exception:            # sin la librería la app sigue funcionando, sin feriados
        return {}
    out = {}
    for d, name in raw.items():
        parts = [p.strip() for p in str(name).split(';')]
        parts = [p for p in parts if p and p.lower() not in _NOT_HOLIDAYS]
        if parts:
            out[d] = ' / '.join(parts)
    return out


def holiday_name(day: date) -> str | None:
    return national_holidays(day.year).get(day)


def is_closed_for_holiday(company, day: date) -> bool:
    """True si ese día es feriado nacional y el negocio no lo abrió."""
    if not holiday_name(day):
        return False
    from ..models import HolidayOptOut
    return not HolidayOptOut.query.filter_by(company_id=company.id, day=day).first()


def upcoming_holidays(company, start: date, months: int = 12):
    """Feriados desde `start` durante los próximos meses, con su estado para el negocio."""
    from ..models import Appointment, HolidayOptOut
    end_year = start.year + (1 if start.month + months > 12 else 0)
    days = {}
    for y in range(start.year, end_year + 1):
        days.update(national_holidays(y))
    limit = date(start.year + (start.month - 1 + months) // 12, (start.month - 1 + months) % 12 + 1, 1)
    opened = {o.day for o in HolidayOptOut.query.filter_by(company_id=company.id).all()}
    rows = []
    for d in sorted(k for k in days if start <= k < limit):
        booked = Appointment.query.filter(
            Appointment.company_id == company.id, Appointment.status == 'BOOKED',
            Appointment.start_dt >= datetime.combine(d, time.min),
            Appointment.start_dt < datetime.combine(d + timedelta(days=1), time.min),
        ).count()
        rows.append({'day': d, 'name': days[d], 'open': d in opened, 'booked': booked})
    return rows
