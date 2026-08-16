"""
Helpers para registrar cambios en turnos (AppointmentLog).
Usar en admin, public y cron blueprints.
"""
from __future__ import annotations
from datetime import datetime
from flask_login import current_user
from ..extensions import db
from ..models import AppointmentLog


def _actor_info() -> tuple[str, int | None, str]:
    """Devuelve (actor_type, actor_id, actor_name) del usuario actual."""
    try:
        if not current_user.is_authenticated:
            return 'system', None, 'Sistema'
        if getattr(current_user, 'is_platform_admin', False):
            return 'platform', current_user.id, current_user.name
        if getattr(current_user, 'is_admin', False):
            role = getattr(current_user, 'role', 'admin')
            return role, current_user.id, current_user.name
        return 'customer', current_user.id, getattr(current_user, 'full_name', current_user.email)
    except Exception:
        return 'system', None, 'Sistema'


def log_created(appointment, notes: str = '') -> None:
    actor_type, actor_id, actor_name = _actor_info()
    _write(appointment, 'CREATED', None, 'BOOKED',
           actor_type, actor_id, actor_name, notes)


def log_status_changed(appointment, old_status: str, new_status: str, notes: str = '') -> None:
    actor_type, actor_id, actor_name = _actor_info()
    _write(appointment, 'STATUS_CHANGED', old_status, new_status,
           actor_type, actor_id, actor_name, notes)


def log_rescheduled(appointment, old_dt: datetime, new_dt: datetime, notes: str = '') -> None:
    actor_type, actor_id, actor_name = _actor_info()
    _write(appointment, 'RESCHEDULED',
           old_dt.strftime('%Y-%m-%d %H:%M'),
           new_dt.strftime('%Y-%m-%d %H:%M'),
           actor_type, actor_id, actor_name, notes)


def log_reminder_sent(appointment) -> None:
    _write(appointment, 'REMINDER_SENT', None, None, 'system', None, 'Sistema')


def _write(appointment, action, old_value, new_value,
           actor_type, actor_id, actor_name, notes='') -> None:
    try:
        entry = AppointmentLog(
            appointment_id=appointment.id,
            action=action,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            actor_type=actor_type,
            actor_id=actor_id,
            actor_name=actor_name,
            notes=notes or None,
        )
        db.session.add(entry)
        # No hacemos commit aquí — el caller lo maneja
    except Exception:
        pass  # La auditoría nunca debe romper el flujo principal
