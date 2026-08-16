from datetime import datetime, timedelta


def can_cancel(appointment, company):
    if appointment.status in ["CANCELED", "RESCHEDULED"]:
        return False

    if appointment.start_dt <= datetime.now():
        return False

    limit_time = appointment.start_dt - timedelta(hours=company.cancelation_limit_hours)

    return datetime.now() < limit_time


def should_apply_penalty(appointment, company):
    if not company.cancelation_penalty_enabled:
        return False

    limit_time = appointment.start_dt - timedelta(hours=company.cancelation_limit_hours)

    return datetime.now() >= limit_time


def cancel_appointment_logic(appointment):
    company = appointment.company

    if appointment.status in ["CANCELED", "RESCHEDULED"]:
        return False, "El turno ya fue modificado"

    if appointment.start_dt <= datetime.now():
        return False, "No se puede cancelar un turno pasado"

    penalty = should_apply_penalty(appointment, company)

    appointment.status = "CANCELED"
    appointment.canceled_at = datetime.now()
    appointment.penalty_applied = penalty

    return True, None