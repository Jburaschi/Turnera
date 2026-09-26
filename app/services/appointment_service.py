"""
Reglas para que el CLIENTE cancele o reprograme su turno online.

Configuración del negocio (Reglas de reserva → Reglas de cancelación):
  - cancelation_limit_hours: hasta cuántas horas antes del turno se puede
    cancelar/reprogramar sin problema (0 = hasta el momento del turno).
  - cancelation_penalty_enabled / cancelation_penalty_amount.

Comportamiento pasado el límite ("cancelación tardía"):
  - Sin penalidad: el cliente NO puede cancelar online; debe contactar al negocio.
  - Con penalidad: puede cancelar, se le avisa el monto antes de confirmar y la
    penalidad queda registrada en el turno como pago PENDIENTE para el negocio.
  - Reprogramar tarde nunca se permite online (si no, reprogramar sería una
    forma de cancelar sin penalidad).

Estas reglas son solo para el cliente: desde el panel el negocio puede
cancelar o reprogramar siempre.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..timeutils import now_ar

DEFAULT_LIMIT_HOURS = 24


@dataclass
class CustomerChangePolicy:
    can_cancel: bool
    can_reschedule: bool
    is_late: bool              # ya pasó el límite de cancelación
    penalty_amount: float      # > 0 solo si cancelar ahora genera penalidad
    deadline: datetime | None  # hasta cuándo se puede cancelar/reprogramar sin problema
    limit_hours: int
    reason: str | None         # por qué no se puede (para mostrar al cliente)


def limit_hours_for(company) -> int:
    hours = company.cancelation_limit_hours
    if hours is None:
        return DEFAULT_LIMIT_HOURS
    return max(0, int(hours))


def customer_change_policy(appointment, now: datetime | None = None) -> CustomerChangePolicy:
    company = appointment.company
    now = now or now_ar()
    limit = limit_hours_for(company)
    deadline = appointment.start_dt - timedelta(hours=limit)

    if appointment.status != 'BOOKED':
        return CustomerChangePolicy(False, False, False, 0.0, deadline, limit,
                                    'Este turno ya no está activo, por lo que no se puede modificar.')
    if appointment.start_dt <= now:
        return CustomerChangePolicy(False, False, True, 0.0, deadline, limit,
                                    'El turno ya pasó, no se puede modificar.')

    if now < deadline:
        return CustomerChangePolicy(True, True, False, 0.0, deadline, limit, None)

    # Cancelación tardía
    penalty_on = bool(company.cancelation_penalty_enabled)
    amount = float(company.cancelation_penalty_amount or 0) if penalty_on else 0.0
    contact = 'Para cambiarlo, comunicate con el negocio.'
    if penalty_on:
        return CustomerChangePolicy(True, False, True, amount, deadline, limit,
                                    f'Faltan menos de {limit} horas para el turno: ya no se puede reprogramar online. {contact}')
    return CustomerChangePolicy(False, False, True, 0.0, deadline, limit,
                                f'Faltan menos de {limit} horas para el turno: ya no se puede cancelar ni reprogramar online. {contact}')


def cancel_appointment_logic(appointment, now: datetime | None = None):
    """Cancelación hecha por el cliente. Devuelve (ok, error, penalty_amount).
    No hace commit: lo hace el caller."""
    policy = customer_change_policy(appointment, now)
    if not policy.can_cancel:
        return False, policy.reason, 0.0

    appointment.status = 'CANCELED'
    appointment.canceled_at = datetime.utcnow()
    appointment.penalty_applied = policy.is_late and bool(appointment.company.cancelation_penalty_enabled)

    if appointment.penalty_applied and policy.penalty_amount > 0:
        # Queda como deuda del cliente para que el negocio la vea en Pagos.
        appointment.payment_status = 'PENDING'
        appointment.paid_amount = policy.penalty_amount
        appointment.payment_method = None
        appointment.payment_notes = 'Penalidad por cancelación tardía'

    return True, None, policy.penalty_amount if appointment.penalty_applied else 0.0
