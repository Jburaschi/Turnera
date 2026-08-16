"""
Servicio de notificaciones por email.
Usa Flask-Mail. Si MAIL_USERNAME no esta configurado, imprime en consola (util en dev).
"""
from __future__ import annotations
from flask import current_app, render_template_string
from flask_mail import Message
from ..extensions import mail


# ── Templates de email ────────────────────────────────────────────────────────

BOOKING_CONFIRMED_BODY = """
Hola {{ name }},

Tu turno quedó confirmado:

  Empresa:      {{ company }}
  Servicio:     {{ service }}
  Profesional:  {{ professional }}
  Fecha y hora: {{ start_dt }}

Para cancelar o reprogramar tu turno, ingresá acá:
  {{ manage_url }}

¡Hasta pronto!
El equipo de {{ company }}
"""

BOOKING_CANCELED_BODY = """
Hola {{ name }},

Tu turno fue cancelado:

  Empresa:      {{ company }}
  Servicio:     {{ service }}
  Profesional:  {{ professional }}
  Fecha y hora: {{ start_dt }}

Si querés reservar un nuevo turno, podés hacerlo acá:
  {{ company_url }}

¡Hasta pronto!
El equipo de {{ company }}
"""

BOOKING_RESCHEDULED_BODY = """
Hola {{ name }},

Tu turno fue reprogramado:

  Empresa:      {{ company }}
  Servicio:     {{ service }}
  Profesional:  {{ professional }}
  Nueva fecha:  {{ start_dt }}

Para gestionar tu turno:
  {{ manage_url }}

¡Hasta pronto!
El equipo de {{ company }}
"""


def _mail_configured() -> bool:
    return bool(current_app.config.get('MAIL_USERNAME'))


def _render(template: str, **ctx) -> str:
    return render_template_string(template, **ctx)


def _send(subject: str, recipients: list[str], body: str) -> None:
    if not recipients or not any(r for r in recipients if r):
        return
    if not _mail_configured():
        current_app.logger.info(
            '[EMAIL - dev mode] Para: %s | Asunto: %s\n%s',
            recipients, subject, body,
        )
        return
    try:
        msg = Message(subject=subject, recipients=recipients, body=body)
        mail.send(msg)
    except Exception as exc:
        current_app.logger.error('Error al enviar email: %s', exc)


# ── API pública ───────────────────────────────────────────────────────────────

def send_booking_confirmed(appointment, manage_url: str, company_url: str) -> None:
    recipient = _get_email(appointment)
    if not recipient:
        return
    body = _render(
        BOOKING_CONFIRMED_BODY,
        name=appointment.customer_display_name,
        company=appointment.company.name,
        service=appointment.service.name,
        professional=appointment.employee.name,
        start_dt=appointment.start_dt.strftime('%d/%m/%Y %H:%M'),
        manage_url=manage_url,
    )
    _send(f'Turno confirmado — {appointment.company.name}', [recipient], body)


def send_booking_canceled(appointment, company_url: str) -> None:
    recipient = _get_email(appointment)
    if not recipient:
        return
    body = _render(
        BOOKING_CANCELED_BODY,
        name=appointment.customer_display_name,
        company=appointment.company.name,
        service=appointment.service.name,
        professional=appointment.employee.name,
        start_dt=appointment.start_dt.strftime('%d/%m/%Y %H:%M'),
        company_url=company_url,
    )
    _send(f'Turno cancelado — {appointment.company.name}', [recipient], body)


def send_booking_rescheduled(appointment, manage_url: str) -> None:
    recipient = _get_email(appointment)
    if not recipient:
        return
    body = _render(
        BOOKING_RESCHEDULED_BODY,
        name=appointment.customer_display_name,
        company=appointment.company.name,
        service=appointment.service.name,
        professional=appointment.employee.name,
        start_dt=appointment.start_dt.strftime('%d/%m/%Y %H:%M'),
        manage_url=manage_url,
    )
    _send(f'Turno reprogramado — {appointment.company.name}', [recipient], body)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_email(appointment) -> str | None:
    if appointment.customer and appointment.customer.email:
        return appointment.customer.email
    return appointment.guest_email or None


WELCOME_ADMIN_BODY = """\
¡Hola {{ name }}!

Tu negocio "{{ company }}" ya está activo en Turnex.

Accedé a tu panel de administración acá:
  {{ dashboard_url }}

  Usuario: {{ email }}
  Contraseña: la que elegiste al registrarte

Desde el panel vas a poder:
  - Agregar tus servicios y aranceles
  - Dar de alta a tus profesionales y sus horarios
  - Ver y gestionar los turnos de cada día
  - Compartir tu página pública con tus clientes:
    {{ company_url }}

Si tenés alguna duda, respondé este email.

¡Éxitos!
El equipo de Turnex
"""

def send_welcome_admin(admin, company) -> None:
    from flask import url_for
    try:
        dashboard_url = url_for('admin.dashboard', slug=company.slug, _external=True)
        company_url   = url_for('public.company_page', slug=company.slug, _external=True)
    except RuntimeError:
        dashboard_url = f'/admin/{company.slug}'
        company_url   = f'/{company.slug}'

    body = _render(
        WELCOME_ADMIN_BODY,
        name=admin.name,
        company=company.name,
        email=admin.email,
        dashboard_url=dashboard_url,
        company_url=company_url,
    )
    _send(f'¡Bienvenido a Turnex! Tu negocio {company.name} ya está activo', [admin.email], body)


PASSWORD_RESET_BODY = """\
Hola {{ name }},

Recibimos una solicitud para restablecer la contraseña de tu cuenta en Turnex.

Hacé clic en el siguiente link para elegir una nueva contraseña:
  {{ reset_url }}

Este link es válido por 2 horas. Si no solicitaste el cambio, ignorá este mensaje.

El equipo de Turnex
"""

def send_password_reset(user, reset_url: str) -> None:
    name = getattr(user, 'name', None) or getattr(user, 'full_name', 'Usuario')
    body = _render(PASSWORD_RESET_BODY, name=name, reset_url=reset_url)
    _send('Restablecé tu contraseña — Turnex', [user.email], body)


TRIAL_WARNING_BODY = """\
Hola {{ name }},

Tu período de prueba de Turnex para "{{ company }}" vence en {{ days }} día{{ 's' if days != 1 else '' }}.

Para no perder el acceso al panel ni la posibilidad de recibir turnos online,
activá tu plan antes del {{ expires }}.

¿Querés seguir usando Turnex? Respondé este email y te ayudamos.

El equipo de Turnex
"""

def send_trial_warning(admin, company, days_left: int) -> None:
    expires_str = company.trial_expires_at.strftime('%d/%m/%Y') if company.trial_expires_at else '—'
    body = _render(
        TRIAL_WARNING_BODY,
        name=admin.name,
        company=company.name,
        days=days_left,
        expires=expires_str,
    )
    _send(
        f'Tu prueba de Turnex vence en {days_left} día{"s" if days_left != 1 else ""} — {company.name}',
        [admin.email],
        body,
    )


REMINDER_BODY = """\
Hola {{ name }},

Te recordamos que mañana tenés un turno en {{ company }}:

  Servicio:     {{ service }}
  Profesional:  {{ employee }}
  Fecha:        {{ date }}
  Hora:         {{ time }}
  Dirección:    {{ address }}

¿Necesitás cancelar o reprogramar? Entrá acá:
  {{ manage_url }}

¡Te esperamos!
{{ company }}
"""

def send_reminder(appointment, manage_url: str) -> None:
    """Manda el recordatorio 24h antes al cliente (guest o registrado)."""
    recipient = None
    if appointment.customer_id and appointment.customer:
        name      = appointment.customer.full_name
        recipient = appointment.customer.email
    elif appointment.guest_email:
        name      = appointment.guest_name or 'Cliente'
        recipient = appointment.guest_email
    if not recipient:
        return

    company = appointment.company
    body = _render(
        REMINDER_BODY,
        name=name,
        company=company.name,
        service=appointment.service.name  if appointment.service  else '—',
        employee=appointment.employee.name if appointment.employee else '—',
        date=appointment.start_dt.strftime('%d/%m/%Y'),
        time=appointment.start_dt.strftime('%H:%M'),
        address=company.address or 'A confirmar con el negocio',
        manage_url=manage_url,
    )
    _send(
        f'Recordatorio de turno — {appointment.start_dt.strftime("%d/%m")} a las {appointment.start_dt.strftime("%H:%M")} en {company.name}',
        [recipient],
        body,
    )
