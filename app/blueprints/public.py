import secrets
from datetime import datetime, timedelta
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user
from ..extensions import db, limiter
from ..models import Appointment, Company, CompanyHours, Employee, Service, SlotHold
from ..services.availability import get_availability_for_day, get_month_summary, HOLD_MINUTES
from ..services.appointment_service import cancel_appointment_logic
from ..services.google_calendar import ensure_google_event_for_appointment, delete_google_event_for_appointment
from ..services.email_service import send_booking_confirmed, send_booking_canceled, send_booking_rescheduled
from ..services import audit as audit_log


def _session_hold_key() -> str:
    """Identificador anónimo y estable de esta sesión de navegador, para saber
    qué holds de horario le pertenecen (no requiere login)."""
    key = session.get('hold_key')
    if not key:
        key = secrets.token_urlsafe(24)
        session['hold_key'] = key
    return key

public_bp = Blueprint('public', __name__)


def _company_accepts_bookings(company) -> bool:
    """Devuelve True si la empresa puede recibir reservas (plan activo o trial vigente)."""
    status = (company.plan_status or '').upper()
    if status == 'ACTIVE':
        return True
    if status == 'TRIAL':
        expires = company.trial_expires_at
        return expires is None or expires > datetime.utcnow()
    return False  # SUSPENDED u otro


def get_company_or_404(slug):
    company = Company.query.filter_by(slug=slug, active=True).first()
    if not company:
        abort(404)
    return company


@public_bp.route('/terminos')
def terms():
    return render_template('terms.html')


@public_bp.route('/privacidad')
def privacy():
    return render_template('privacy.html')


@public_bp.route('/preguntas-frecuentes')
def faq():
    return render_template('faq.html')


@public_bp.route('/')
def home():
    return render_template('home.html', current_year=datetime.now().year)


@public_bp.route('/directory')
def directory():
    companies = Company.query.filter_by(active=True).order_by(Company.name.asc()).all()
    return render_template('directory.html', companies=companies)


@public_bp.route('/<slug>')
def company_page(slug):
    company = get_company_or_404(slug)
    hours_summary = _build_hours_summary(company)
    return render_template('company_page.html', company=company, hours_summary=hours_summary)


WEEKDAY_SHORT = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']


def _build_hours_summary(company):
    """Agrupa CompanyHours en líneas legibles tipo 'Lun a Vie 09:00 - 20:00'."""
    rows = CompanyHours.query.filter_by(company_id=company.id).order_by(CompanyHours.weekday, CompanyHours.start_time).all()
    if not rows:
        return None
    by_day = {}
    for r in rows:
        by_day.setdefault(r.weekday, []).append(r)

    # Agrupar días consecutivos con el mismo horario (usa la primera franja de cada día)
    day_ranges = {}
    for day, entries in by_day.items():
        day_ranges[day] = f"{entries[0].start_time.strftime('%H:%M')} - {entries[-1].end_time.strftime('%H:%M')}"

    groups = []
    days_sorted = sorted(day_ranges.keys())
    i = 0
    while i < len(days_sorted):
        start_day = days_sorted[i]
        j = i
        while j + 1 < len(days_sorted) and days_sorted[j+1] == days_sorted[j] + 1 and day_ranges[days_sorted[j+1]] == day_ranges[start_day]:
            j += 1
        end_day = days_sorted[j]
        label = WEEKDAY_SHORT[start_day] if start_day == end_day else f"{WEEKDAY_SHORT[start_day]} a {WEEKDAY_SHORT[end_day]}"
        groups.append(f"{label} {day_ranges[start_day]}")
        i = j + 1
    return ' · '.join(groups)


TIMEZONE_LABELS = {
    'America/Argentina/Buenos_Aires': 'Argentina (GMT-3)',
    'America/Santiago': 'Chile (GMT-4)',
    'America/Montevideo': 'Uruguay (GMT-3)',
    'America/Sao_Paulo': 'Brasil (GMT-3)',
    'America/Mexico_City': 'México (GMT-6)',
    'America/Bogota': 'Colombia (GMT-5)',
}


@public_bp.route('/<slug>/booking')
def booking_page(slug):
    company = get_company_or_404(slug)
    if not _company_accepts_bookings(company):
        return render_template('booking_unavailable.html', company=company)
    timezone_label = TIMEZONE_LABELS.get(company.timezone, company.timezone)
    return render_template('booking.html', company=company, timezone_label=timezone_label)


@public_bp.route('/api/<slug>/services')
@limiter.limit('60 per minute')
def api_services(slug):
    company = get_company_or_404(slug)
    palette = ['#3654f0', '#7c3aed', '#c98a1e', '#16a34a', '#ec4899', '#0891b2', '#dc2626']
    active_services = sorted([s for s in company.services if s.active], key=lambda s: s.id)
    return jsonify([
        {'id': s.id, 'name': s.name, 'short_description': s.short_description,
         'long_description': s.long_description, 'duration_min': s.duration_min, 'price': float(s.price),
         'color': s.color or palette[i % len(palette)], 'photo_url': s.photo_url}
        for i, s in enumerate(active_services)
    ])


@public_bp.route('/api/<slug>/employees')
@limiter.limit('60 per minute')
def api_employees(slug):
    company    = get_company_or_404(slug)
    service_id = request.args.get('service_id', type=int)
    if not service_id:
        return jsonify([])
    return jsonify([
        {
            'id':        e.id,
            'name':      e.name,
            'color':     e.color,
            'photo_url': e.photo_url or None,
            'bio':       e.bio or None,
        }
        for e in company.employees
        if e.active and any(s.id == service_id and s.active for s in e.services)
    ])


@public_bp.route('/api/<slug>/availability/month')
@limiter.limit('30 per minute')
def api_month_availability(slug):
    company     = get_company_or_404(slug)
    service_id  = request.args.get('service_id', type=int)
    year        = request.args.get('year', type=int)
    month       = request.args.get('month', type=int)
    employee_id = request.args.get('employee_id', type=int)
    if not service_id or not year or not month:
        return jsonify({'error': 'Parametros faltantes'}), 400
    service = Service.query.filter_by(company_id=company.id, id=service_id, active=True).first_or_404()
    return jsonify(get_month_summary(company, service, year, month, employee_id))


@public_bp.route('/api/<slug>/availability/day')
@limiter.limit('60 per minute')
def api_day_availability(slug):
    company     = get_company_or_404(slug)
    service_id  = request.args.get('service_id', type=int)
    employee_id = request.args.get('employee_id', type=int)
    date_str    = request.args.get('date')
    if not service_id or not date_str:
        return jsonify({'error': 'Parametros faltantes'}), 400
    service = Service.query.filter_by(company_id=company.id, id=service_id, active=True).first_or_404()
    day     = datetime.strptime(date_str, '%Y-%m-%d').date()
    slots   = get_availability_for_day(company, service, day, employee_id, exclude_session_key=_session_hold_key())
    return jsonify([
        {'start': s['start'].isoformat(), 'end': s['end'].isoformat(),
         'label': s['start'].strftime('%H:%M'),
         'employee_id': s['employee_id'], 'employee_name': s['employee_name']}
        for s in slots
    ])


@public_bp.route('/<slug>/hold-slot', methods=['POST'])
@limiter.limit('30 per minute')
def hold_slot(slug):
    """Reserva temporalmente un horario (HOLD_MINUTES) mientras el cliente
    completa el formulario de confirmación, para que no se lo saquen."""
    company     = get_company_or_404(slug)
    service_id  = request.form.get('service_id', type=int)
    employee_id = request.form.get('employee_id', type=int)
    start_raw   = request.form.get('start_dt', '')
    service  = Service.query.filter_by(company_id=company.id, id=service_id, active=True).first()
    employee = Employee.query.filter_by(company_id=company.id, id=employee_id, active=True).first()
    if not service or not employee or not start_raw:
        return jsonify({'ok': False, 'reason': 'invalid'}), 400
    try:
        start_dt = datetime.fromisoformat(start_raw)
    except ValueError:
        return jsonify({'ok': False, 'reason': 'invalid'}), 400
    end_dt = start_dt + timedelta(minutes=service.duration_min)

    key = _session_hold_key()
    day_slots = get_availability_for_day(company, service, start_dt.date(), employee.id, exclude_session_key=key)
    if not any(s['start'] == start_dt for s in day_slots):
        return jsonify({'ok': False, 'reason': 'taken'}), 409

    SlotHold.query.filter_by(company_id=company.id, session_key=key).delete()
    expires_at = datetime.utcnow() + timedelta(minutes=HOLD_MINUTES)
    db.session.add(SlotHold(
        company_id=company.id, employee_id=employee.id,
        start_dt=start_dt, end_dt=end_dt,
        session_key=key, expires_at=expires_at,
    ))
    db.session.commit()
    return jsonify({'ok': True, 'expires_at': expires_at.isoformat() + 'Z', 'hold_minutes': HOLD_MINUTES})


@public_bp.route('/<slug>/release-hold', methods=['POST'])
@limiter.limit('30 per minute')
def release_hold(slug):
    """Libera el hold activo de esta sesión (el cliente cambió de horario o se fue)."""
    company = get_company_or_404(slug)
    key = _session_hold_key()
    SlotHold.query.filter_by(company_id=company.id, session_key=key).delete()
    db.session.commit()
    return jsonify({'ok': True})


@public_bp.route('/<slug>/book', methods=['POST'])
@limiter.limit('10 per minute', error_message='Demasiados intentos. Esperá un minuto.')
def create_appointment(slug):
    company  = get_company_or_404(slug)
    if not _company_accepts_bookings(company):
        abort(403)
    service  = Service.query.filter_by(company_id=company.id, id=request.form.get('service_id', type=int), active=True).first_or_404()
    employee = Employee.query.filter_by(company_id=company.id, id=request.form.get('employee_id', type=int), active=True).first_or_404()

    if service not in employee.services:
        flash('El profesional elegido no realiza esa prestacion.', 'danger')
        return redirect(url_for('public.booking_page', slug=slug))

    start_dt  = datetime.fromisoformat(request.form['start_dt'])
    day_slots = get_availability_for_day(company, service, start_dt.date(), employee.id, exclude_session_key=_session_hold_key())
    selected  = next((s for s in day_slots if s['start'] == start_dt), None)
    if not selected:
        flash('Ese horario ya no esta disponible.', 'danger')
        return redirect(url_for('public.booking_page', slug=slug))

    cfg = company.config
    if cfg.require_customer_login:
        if not current_user.is_authenticated or getattr(current_user, 'is_admin', False) or getattr(current_user, 'is_platform_admin', False) or current_user.company_id != company.id:
            flash('Esta empresa requiere login para reservar.', 'warning')
            return redirect(url_for('auth.customer_login', slug=slug, next=url_for('public.booking_page', slug=slug)))

    appointment = Appointment(
        company=company, service=service, employee=employee,
        start_dt=selected['start'], end_dt=selected['end'],
        status='BOOKED',
        notes=request.form.get('notes', '').strip() or None,
        manage_token=secrets.token_urlsafe(24),
    )

    is_logged_customer = (
        current_user.is_authenticated
        and not getattr(current_user, 'is_admin', False)
        and not getattr(current_user, 'is_platform_admin', False)
        and current_user.company_id == company.id
    )

    if is_logged_customer:
        appointment.customer = current_user
    else:
        if cfg.required_name and not request.form.get('guest_name', '').strip():
            flash('El nombre es obligatorio.', 'danger')
            return redirect(url_for('public.booking_page', slug=slug))
        if cfg.required_phone and not request.form.get('guest_phone', '').strip():
            flash('El telefono es obligatorio.', 'danger')
            return redirect(url_for('public.booking_page', slug=slug))
        if cfg.required_email and not request.form.get('guest_email', '').strip():
            flash('El email es obligatorio.', 'danger')
            return redirect(url_for('public.booking_page', slug=slug))
        if cfg.required_dni and not request.form.get('guest_dni', '').strip():
            flash('El DNI es obligatorio.', 'danger')
            return redirect(url_for('public.booking_page', slug=slug))
        appointment.guest_name  = request.form.get('guest_name', '').strip()
        appointment.guest_phone = request.form.get('guest_phone', '').strip()
        appointment.guest_email = request.form.get('guest_email', '').strip()
        appointment.guest_dni   = request.form.get('guest_dni', '').strip()

    db.session.add(appointment)
    db.session.flush()
    audit_log.log_created(appointment, notes='Reserva online por el cliente')
    SlotHold.query.filter_by(company_id=company.id, session_key=_session_hold_key()).delete()
    db.session.commit()
    ensure_google_event_for_appointment(appointment)

    manage_url  = url_for('public.manage_appointment', slug=slug, token=appointment.manage_token, _external=True)
    company_url = url_for('public.company_page', slug=slug, _external=True)
    send_booking_confirmed(appointment, manage_url=manage_url, company_url=company_url)

    return render_template('booking_success.html', company=company, appointment=appointment)


@public_bp.route('/<slug>/mis-turnos')
def customer_appointments(slug):
    company = get_company_or_404(slug)
    if not current_user.is_authenticated or getattr(current_user, 'is_admin', False) or getattr(current_user, 'is_platform_admin', False):
        return redirect(url_for('auth.customer_login', slug=slug, next=url_for('public.customer_appointments', slug=slug)))
    appointments = Appointment.query.filter_by(company_id=company.id, customer_id=current_user.id).order_by(Appointment.start_dt.desc()).all()
    return render_template('customer_appointments.html', company=company, appointments=appointments)


@public_bp.route('/<slug>/a/<token>')
def manage_appointment(slug, token):
    company     = get_company_or_404(slug)
    appointment = Appointment.query.filter_by(company_id=company.id, manage_token=token).first_or_404()
    return render_template('appointment_manage.html', company=company, appointment=appointment)


@public_bp.route('/<slug>/a/<token>/cancel', methods=['POST'])
def manage_appointment_cancel(slug, token):
    company     = get_company_or_404(slug)
    appointment = Appointment.query.filter_by(company_id=company.id, manage_token=token).first_or_404()
    ok, err = cancel_appointment_logic(appointment)
    if not ok:
        flash(err or 'No se pudo cancelar el turno.', 'danger')
        return redirect(url_for('public.manage_appointment', slug=slug, token=token))
    audit_log.log_status_changed(appointment, 'BOOKED', 'CANCELED', notes='Cancelado por el cliente')
    db.session.commit()
    delete_google_event_for_appointment(appointment)
    send_booking_canceled(appointment, company_url=url_for('public.company_page', slug=slug, _external=True))
    flash('Turno cancelado.', 'success')
    return redirect(url_for('public.manage_appointment', slug=slug, token=token))


@public_bp.route('/<slug>/a/<token>/reschedule', methods=['POST'])
def manage_appointment_reschedule(slug, token):
    company     = get_company_or_404(slug)
    appointment = Appointment.query.filter_by(company_id=company.id, manage_token=token).first_or_404()
    if appointment.status != 'BOOKED':
        flash('Solo se pueden reprogramar turnos activos.', 'warning')
        return redirect(url_for('public.manage_appointment', slug=slug, token=token))
    raw = request.form.get('start_dt', '').strip()
    if not raw:
        flash('Elegí una fecha y hora.', 'danger')
        return redirect(url_for('public.manage_appointment', slug=slug, token=token))
    try:
        start_dt = datetime.fromisoformat(raw)
    except Exception:
        flash('Formato de fecha invalido.', 'danger')
        return redirect(url_for('public.manage_appointment', slug=slug, token=token))
    slots    = get_availability_for_day(company, appointment.service, start_dt.date(), appointment.employee.id)
    selected = next((s for s in slots if s['start'] == start_dt), None)
    if not selected:
        flash('Ese horario ya no esta disponible.', 'danger')
        return redirect(url_for('public.manage_appointment', slug=slug, token=token))
    old_dt = appointment.start_dt
    appointment.start_dt = selected['start']
    appointment.end_dt   = selected['end']
    audit_log.log_rescheduled(appointment, old_dt, selected['start'],
                              notes='Reprogramado por el cliente')
    db.session.commit()
    ensure_google_event_for_appointment(appointment)
    manage_url = url_for('public.manage_appointment', slug=slug, token=token, _external=True)
    send_booking_rescheduled(appointment, manage_url=manage_url)
    flash('Turno reprogramado.', 'success')
    return redirect(url_for('public.manage_appointment', slug=slug, token=token))
