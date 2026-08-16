"""
Blueprint de cron jobs internos.

Endpoint: POST /internal/cron/reminders?token=<CRON_SECRET>
Llamar desde un cron externo (Railway, Render cron, crontab) cada hora.

Comportamiento:
  - Busca turnos BOOKED que empiezan entre 23 y 25 horas desde ahora
  - Con email de cliente o invitado disponible
  - reminder_sent = False
  - Les manda el recordatorio y marca reminder_sent = True
  - Devuelve JSON con el resultado
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request, abort, url_for
from ..extensions import db
from ..models import Appointment
from ..services.email_service import send_reminder
from ..services import audit as audit_log

cron_bp = Blueprint('cron', __name__, url_prefix='/internal/cron')

WINDOW_MIN_HOURS = 23
WINDOW_MAX_HOURS = 25


def _get_cron_secret() -> str:
    return os.environ.get('CRON_SECRET', '')


@cron_bp.route('/reminders', methods=['POST', 'GET'])
def send_reminders():
    # Validar token — si no hay CRON_SECRET configurado en producción, bloquear
    secret = _get_cron_secret()
    token  = request.args.get('token', '')
    if not secret or token != secret:
        abort(403)

    now      = datetime.utcnow()
    win_from = now + timedelta(hours=WINDOW_MIN_HOURS)
    win_to   = now + timedelta(hours=WINDOW_MAX_HOURS)

    # Turnos en la ventana que aún no recibieron recordatorio
    appointments = (
        Appointment.query
        .filter(
            Appointment.status == 'BOOKED',
            Appointment.reminder_sent == False,
            Appointment.start_dt >= win_from,
            Appointment.start_dt <= win_to,
        )
        .all()
    )

    sent    = 0
    skipped = 0
    errors  = []

    for apt in appointments:
        # Necesita email para enviar
        has_email = (
            (apt.customer_id and apt.customer and apt.customer.email) or
            apt.guest_email
        )
        if not has_email:
            skipped += 1
            apt.reminder_sent = True   # marcar igual para no reintentar
            continue

        try:
            manage_url = url_for(
                'public.manage_appointment',
                slug=apt.company.slug,
                token=apt.manage_token,
                _external=True,
            ) if apt.manage_token else ''

            send_reminder(apt, manage_url)
            apt.reminder_sent = True
            audit_log.log_reminder_sent(apt)
            sent += 1
        except Exception as e:
            errors.append({'appointment_id': apt.id, 'error': str(e)})

    db.session.commit()

    return jsonify({
        'ok':      True,
        'run_at':  now.isoformat(),
        'window':  {'from': win_from.isoformat(), 'to': win_to.isoformat()},
        'sent':    sent,
        'skipped': skipped,
        'errors':  errors,
    })


@cron_bp.route('/health', methods=['GET'])
def health():
    """Endpoint de verificación — no requiere token."""
    return jsonify({'ok': True, 'time': datetime.utcnow().isoformat()})
