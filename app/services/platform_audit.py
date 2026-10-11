"""Registro de acciones de los usuarios de plataforma.

- Acciones en /platform (editar empresa, pagos, clientes, usuarios…).
- Cambios hechos dentro del panel de un negocio con "Entrar" (impersonación):
  se registran solos con un after_request del blueprint admin.
"""
from __future__ import annotations

from flask import current_app, request, session
from flask_login import current_user

from ..extensions import db

IMPERSONATOR_KEY = 'impersonator_platform_id'

# Qué hizo, en palabras, según la ruta del panel del negocio
ADMIN_ACTIONS = {
    'admin.update_company': 'Editó el perfil o las reglas del negocio',
    'admin.create_employee': 'Creó un profesional',
    'admin.update_employee': 'Editó un profesional',
    'admin.delete_employee': 'Eliminó un profesional',
    'admin.toggle_employee_active': 'Activó/desactivó un profesional',
    'admin.create_service': 'Creó una prestación',
    'admin.update_service': 'Editó una prestación',
    'admin.delete_service': 'Eliminó una prestación',
    'admin.create_customer': 'Creó un cliente',
    'admin.update_customer': 'Editó un cliente',
    'admin.delete_customer': 'Eliminó un cliente',
    'admin.create_manual_appointment': 'Cargó un turno',
    'admin.update_appointment_status': 'Cambió el estado de un turno',
    'admin.reschedule_appointment': 'Reprogramó un turno',
    'admin.update_appointment_payment': 'Registró un pago de turno',
    'admin.create_blocked_period': 'Creó un bloqueo',
    'admin.delete_blocked_period': 'Eliminó un bloqueo',
    'admin.toggle_holiday': 'Abrió/cerró un feriado',
    'admin.plan_request': 'Hizo un pedido de plan',
    'admin.google_disconnect': 'Desconectó Google Calendar',
    'admin.google_settings': 'Cambió opciones de Google Calendar',
    'admin.team': 'Sumó un usuario al equipo',
    'admin.update_team_member': 'Editó un usuario del equipo',
    'admin.delete_team_member': 'Eliminó un usuario del equipo',
}
_SECRET_FIELDS = {'password', 'admin_password', 'new_password', 'current_password', 'confirm_password', 'csrf_token'}


def acting_platform_user():
    """El usuario de plataforma que está actuando (directo o con "Entrar"), o None."""
    from ..models import PlatformUser
    try:
        if current_user.is_authenticated and getattr(current_user, 'is_platform_admin', False):
            return current_user._get_current_object()
        pid = session.get(IMPERSONATOR_KEY)
        if pid:
            return db.session.get(PlatformUser, pid)
    except Exception:
        return None
    return None


def log_platform(action: str, detail: str = '', company=None, company_id=None) -> None:
    """Guarda una acción. Nunca rompe el flujo de la app."""
    from ..models import PlatformAuditLog
    try:
        user = acting_platform_user()
        entry = PlatformAuditLog(
            platform_user_id=user.id if user else None,
            platform_user_email=user.email if user else None,
            company_id=(company.id if company is not None else company_id),
            action=action[:80], detail=(detail or '')[:500] or None,
            path=(request.path[:255] if request else None),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('No se pudo registrar la acción de plataforma: %s', action)


def changed_fields(form) -> str:
    """'name, email, phone' — los campos que vinieron en el formulario (sin contraseñas)."""
    keys = [k for k in form.keys() if k not in _SECRET_FIELDS]
    pw = [k for k in form.keys() if k in _SECRET_FIELDS - {'csrf_token'} and form.get(k)]
    out = ', '.join(sorted(set(keys))[:20])
    if pw:
        out += (' · ' if out else '') + 'cambió una contraseña'
    return out


def register_impersonation_logging(admin_bp):
    """Registra cada cambio (POST) que un usuario de plataforma hace dentro del
    panel de un negocio con "Entrar"."""
    @admin_bp.after_request
    def _log_impersonated_change(response):
        try:
            if request.method == 'POST' and session.get(IMPERSONATOR_KEY) and response.status_code < 400:
                company = getattr(current_user, 'company', None)
                label = ADMIN_ACTIONS.get(request.endpoint, f'Cambio en el panel ({request.endpoint})')
                log_platform(label, f'Como {current_user.email}. Campos: {changed_fields(request.form)}', company=company)
        except Exception:
            current_app.logger.exception('No se pudo registrar el cambio hecho con "Entrar"')
        return response
