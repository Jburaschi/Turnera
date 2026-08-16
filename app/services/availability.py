from __future__ import annotations
from calendar import monthrange
from datetime import date, datetime, timedelta

from ..models import Appointment, BlockedPeriod, Employee, Service, SlotHold

SLOT_STEP_MIN = 15
HOLD_MINUTES = 10


def overlaps(s1, e1, s2, e2):
    return s1 < e2 and e1 > s2


def _appointments_for_employee(employee_id, start, end):
    return Appointment.query.filter(
        Appointment.employee_id == employee_id,
        Appointment.status == 'BOOKED',
        Appointment.start_dt < end,
        Appointment.end_dt > start,
    ).all()


def _active_holds_for_employee(employee_id, start, end, exclude_session_key=None):
    q = SlotHold.query.filter(
        SlotHold.employee_id == employee_id,
        SlotHold.expires_at > datetime.utcnow(),
        SlotHold.start_dt < end,
        SlotHold.end_dt > start,
    )
    if exclude_session_key:
        q = q.filter(SlotHold.session_key != exclude_session_key)
    return q.all()


def _blocks_for_employee(company_id, employee_id, start, end):
    return BlockedPeriod.query.filter(
        BlockedPeriod.company_id == company_id,
        BlockedPeriod.start_dt < end,
        BlockedPeriod.end_dt > start,
        (BlockedPeriod.employee_id == employee_id) | (BlockedPeriod.employee_id.is_(None)),
    ).all()


def _schedule_accepts_service(employee, schedule, service):
    if not schedule.limited_services:
        return True
    return service in schedule.limited_services


def get_candidate_employees(company, service, employee_id=None):
    candidates = [e for e in company.employees if e.active and service in e.services]
    if employee_id:
        candidates = [e for e in candidates if e.id == employee_id]
    return candidates


def get_employee_slots_for_day(company, employee, service, day, ignore_past=False, exclude_session_key=None):
    """
    ignore_past=True -> muestra todos los slots sin filtrar por hora actual.
    Usar para turnos manuales y reprogramaciones desde el panel admin.
    ignore_past=False -> comportamiento publico (filtra horarios ya pasados).
    exclude_session_key -> si se pasa, los horarios reservados temporalmente (hold)
    por esa misma sesión NO se excluyen (le siguen apareciendo a quien los está
    reservando); los hold de otras sesiones sí bloquean el horario.
    """
    weekday = day.weekday()
    schedules = [s for s in employee.schedules if s.weekday == weekday]
    results = []
    now = datetime.now()

    for schedule in schedules:
        if not _schedule_accepts_service(employee, schedule, service):
            continue
        current = datetime.combine(day, schedule.start_time)
        end_boundary = datetime.combine(day, schedule.end_time)
        appointments = _appointments_for_employee(employee.id, current, end_boundary)
        blocks = _blocks_for_employee(company.id, employee.id, current, end_boundary)
        holds = _active_holds_for_employee(employee.id, current, end_boundary, exclude_session_key)

        while current + timedelta(minutes=service.duration_min) <= end_boundary:
            candidate_end = current + timedelta(minutes=service.duration_min)
            conflict  = any(overlaps(current, candidate_end, ap.start_dt, ap.end_dt) for ap in appointments)
            blocked   = any(overlaps(current, candidate_end, bl.start_dt, bl.end_dt) for bl in blocks)
            held      = any(overlaps(current, candidate_end, h.start_dt, h.end_dt) for h in holds)
            in_future = ignore_past or current >= now

            if in_future and not conflict and not blocked and not held:
                results.append({
                    'employee_id':   employee.id,
                    'employee_name': employee.name,
                    'start':         current,
                    'end':           candidate_end,
                })
            current += timedelta(minutes=SLOT_STEP_MIN)

    return results


def get_availability_for_day(company, service, day, employee_id=None, ignore_past=False, exclude_session_key=None):
    slots = []
    for employee in get_candidate_employees(company, service, employee_id):
        slots.extend(get_employee_slots_for_day(company, employee, service, day, ignore_past=ignore_past, exclude_session_key=exclude_session_key))
    slots.sort(key=lambda s: (s['start'], s['employee_name']))
    return slots


def get_month_summary(company, service, year, month, employee_id=None):
    _, days_in_month = monthrange(year, month)
    result = {}
    for day_num in range(1, days_in_month + 1):
        d = date(year, month, day_num)
        result[d.isoformat()] = len(get_availability_for_day(company, service, d, employee_id)) > 0
    return result
