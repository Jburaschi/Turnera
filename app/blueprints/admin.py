from __future__ import annotations
import csv, io, os, secrets, uuid
from datetime import datetime, time, timedelta
from functools import wraps
from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func
from werkzeug.utils import secure_filename
from ..extensions import db
from ..models import (
    WEEKDAY_LABELS, AdminUser, Appointment, AppointmentLog, BlockedPeriod, Company, CompanyHours, Customer,
    Employee, EmployeeSchedule, GoogleCalendarConnection, Service, SubscriptionPayment, UploadedImage,
)
from ..services.availability import get_availability_for_day
from ..services.email_service import send_booking_canceled, send_booking_confirmed, send_booking_rescheduled, send_trial_warning
from ..services import audit as audit_log
from ..services.google_calendar import (
    GOOGLE_SCOPES, build_redirect_uri, company_has_google_plan,
    delete_google_event_for_appointment, ensure_google_event_for_appointment, get_google_oauth_config,
)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
ADMIN_SECTIONS = {
    'overview': 'Resumen', 'agenda': 'Agenda', 'customers': 'Clientes',
    'professionals': 'Profesionales', 'services': 'Prestaciones', 'blocked': 'Bloqueos',
    'company': 'Perfil del negocio', 'payments': 'Pagos',
    'settings': 'Reglas de reserva', 'integrations': 'Integraciones',
}
STATUS_OPTIONS = ['BOOKED', 'CANCELED', 'DONE', 'NO_SHOW']
PAGE_SIZE = 50
MONTH_LABELS = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
TRIAL_WARNING_DAYS = 7  # mostrar banner cuando faltan ≤7 días


# ── Helpers de plan ────────────────────────────────────────────────────────────

def get_plan_state(company) -> dict:
    """
    Devuelve un dict con el estado de plan de la empresa.
    Keys: blocked (bool), trial_active (bool), trial_days_left (int|None),
          trial_warning (bool), status_label (str)
    """
    now = datetime.utcnow()
    status = (company.plan_status or '').upper()

    if status == 'SUSPENDED':
        return dict(blocked=True, trial_active=False, trial_days_left=None,
                    trial_warning=False, status_label='Suspendida')

    if status == 'TRIAL':
        expires = company.trial_expires_at
        if not expires:
            # Trial sin fecha — asumimos activo (datos viejos)
            return dict(blocked=False, trial_active=True, trial_days_left=None,
                        trial_warning=False, status_label='Período de prueba')
        days_left = (expires.date() - now.date()).days
        if days_left < 0:
            return dict(blocked=True, trial_active=False, trial_days_left=0,
                        trial_warning=False, status_label='Período de prueba vencido')
        warning = days_left <= TRIAL_WARNING_DAYS
        return dict(blocked=False, trial_active=True, trial_days_left=days_left,
                    trial_warning=warning, status_label=f'Prueba — {days_left} día{"s" if days_left != 1 else ""} restante{"s" if days_left != 1 else ""}')

    # ACTIVE u otro
    return dict(blocked=False, trial_active=False, trial_days_left=None,
                trial_warning=False, status_label=company.plan_name)

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            return redirect(url_for('auth.admin_login'))
        return fn(*args, **kwargs)
    return wrapper


def owner_required(fn):
    """Como admin_required, pero además exige role == 'admin' (no 'staff').
    Usar en acciones sensibles: perfil del negocio, prestaciones, profesionales,
    bloqueos, pagos, integraciones, reglas de reserva."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            return redirect(url_for('auth.admin_login'))
        if getattr(current_user, 'role', 'admin') != 'admin':
            flash('No tenés permisos para realizar esta acción.', 'warning')
            slug = kwargs.get('slug') or (current_user.company.slug if current_user.company else None)
            return redirect(url_for('admin.dashboard', slug=slug)) if slug else abort(403)
        return fn(*args, **kwargs)
    return wrapper


@admin_bp.before_request
def check_plan_access():
    """Bloquea el panel si el plan está vencido o suspendido.
    También dispara el email de aviso cuando quedan ≤7 días de trial."""
    if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
        return
    if request.endpoint in ('admin.plan_blocked', 'admin.static'):
        return
    company = Company.query.get(current_user.company_id)
    if not company:
        return
    state = get_plan_state(company)

    # Email de aviso (solo una vez, solo en requests GET para no spamear)
    if (state['trial_warning'] and
            state['trial_days_left'] is not None and
            not company.trial_warning_sent and
            request.method == 'GET'):
        try:
            admin = current_user._get_current_object()
            send_trial_warning(admin, company, state['trial_days_left'])
            company.trial_warning_sent = True
            db.session.commit()
        except Exception:
            pass

    if state['blocked']:
        return redirect(url_for('admin.plan_blocked', slug=company.slug))

def get_owned_company_or_404(slug):
    company = Company.query.filter_by(slug=slug).first()
    if not company or current_user.company_id != company.id:
        abort(404)
    return company

def parse_time_or_none(raw):
    raw = (raw or '').strip()
    return datetime.strptime(raw, '%H:%M').time() if raw else None

def parse_datetime_or_none(raw_date, raw_time):
    if not raw_date or not raw_time:
        return None
    return datetime.strptime(f'{raw_date} {raw_time}', '%Y-%m-%d %H:%M')

def parse_employee_schedule_blocks(company):
    blocks, i = [], 0
    while True:
        wd_raw = request.form.get(f'block_{i}_weekday')
        if wd_raw is None or str(wd_raw).strip() == '':
            break
        wd   = int(wd_raw)
        st   = parse_time_or_none(request.form.get(f'block_{i}_start'))
        et   = parse_time_or_none(request.form.get(f'block_{i}_end'))
        sids = {int(x) for x in request.form.getlist(f'block_{i}_service_ids') if str(x).isdigit()}
        if st and et and st < et:
            valid = {s for s in sids if Service.query.filter_by(company_id=company.id, id=s).first()}
            blocks.append((wd, st, et, valid))
        i += 1
    return blocks

def replace_employee_schedules(employee, company, blocks):
    for sch in list(employee.schedules):
        sch.limited_services.clear()
        db.session.delete(sch)
    db.session.flush()
    for wd, st, et, sids in blocks:
        sch = EmployeeSchedule(employee_id=employee.id, weekday=wd, start_time=st, end_time=et)
        db.session.add(sch)
        db.session.flush()
        for sid in sids:
            svc = Service.query.filter_by(company_id=company.id, id=sid).first()
            if svc and svc in employee.services:
                sch.limited_services.append(svc)

def find_appointments_outside_schedule(employee, blocks):
    """Turnos futuros ya reservados que, con el horario NUEVO que se está por
    guardar, quedarían fuera de cualquier franja (el dueño cambió el horario
    y ese turno viejo ya no entra). No se tocan ni se cancelan solos —
    solo se devuelven para avisarle al dueño."""
    now = datetime.utcnow()
    future = Appointment.query.filter(
        Appointment.employee_id == employee.id,
        Appointment.status == 'BOOKED',
        Appointment.start_dt >= now,
    ).order_by(Appointment.start_dt).all()

    orphaned = []
    for ap in future:
        wd = ap.start_dt.weekday()
        ap_start_t = ap.start_dt.time()
        ap_end_t = ap.end_dt.time()
        covered = any(
            b_wd == wd and b_start <= ap_start_t and ap_end_t <= b_end
            for b_wd, b_start, b_end, _sids in blocks
        )
        if not covered:
            orphaned.append(ap)
    return orphaned

def month_range(day):
    ms = day.replace(day=1)
    return ms, ms.replace(year=ms.year+1, month=1) if ms.month == 12 else ms.replace(month=ms.month+1)

def pct_change(old, new):
    """None si no hay dato previo para comparar (evita mostrar variaciones inventadas)."""
    if old in (None, 0):
        return None
    return round(((new - old) / old) * 100)

def build_agenda_query(company, selected_day, professional_id, service_id, status, search_customer):
    q = Appointment.query.filter(
        Appointment.company_id == company.id,
        Appointment.start_dt >= datetime.combine(selected_day, time.min),
        Appointment.start_dt <= datetime.combine(selected_day, time.max),
    )
    if professional_id: q = q.filter(Appointment.employee_id == professional_id)
    if service_id:      q = q.filter(Appointment.service_id == service_id)
    if status:          q = q.filter(Appointment.status == status)
    apps = q.order_by(Appointment.start_dt.asc()).all()
    if search_customer:
        apps = [a for a in apps if search_customer in (a.customer_display_name or '').lower()]
    return apps

def build_recent_activity(company, limit=6):
    """Combina altas de turnos, cancelaciones y clientes nuevos en una sola
    línea de tiempo real, ordenada por fecha, con texto en español."""
    items = []

    logs = (AppointmentLog.query.join(Appointment, AppointmentLog.appointment_id == Appointment.id)
            .filter(Appointment.company_id == company.id,
                    AppointmentLog.action.in_(['CREATED', 'STATUS_CHANGED']))
            .order_by(AppointmentLog.created_at.desc()).limit(limit * 2).all())
    for log in logs:
        ap = log.appointment
        if not ap:
            continue
        name = ap.customer_display_name or 'Un cliente'
        if log.action == 'CREATED':
            items.append(dict(icon='calendar', ts=log.created_at,
                               title='Nuevo turno reservado',
                               sub=f'{name} · {ap.start_dt.strftime("%d/%m %H:%M")}'))
        elif log.action == 'STATUS_CHANGED' and (log.new_value or '').upper() == 'CANCELED':
            items.append(dict(icon='calendar-off', ts=log.created_at,
                               title=f'{name} canceló su turno',
                               sub=f'Turno del {ap.start_dt.strftime("%d/%m %H:%M")}'))

    new_customers = (Customer.query.filter_by(company_id=company.id)
                      .order_by(Customer.created_at.desc()).limit(limit).all())
    for c in new_customers:
        items.append(dict(icon='user-plus', ts=c.created_at,
                           title='Nuevo cliente registrado', sub=c.full_name))

    items.sort(key=lambda x: x['ts'] or datetime.min, reverse=True)
    now = datetime.now()
    for it in items[:limit]:
        it['relative'] = humanize_delta(now - it['ts']) if it['ts'] else ''
    return items[:limit]


def humanize_delta(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 60:
        return 'Recién'
    mins = secs // 60
    if mins < 60:
        return f'Hace {mins} min'
    hours = mins // 60
    if hours < 24:
        return f'Hace {hours} hora{"s" if hours != 1 else ""}'
    days = hours // 24
    if days < 7:
        return f'Hace {days} día{"s" if days != 1 else ""}'
    weeks = days // 7
    return f'Hace {weeks} semana{"s" if weeks != 1 else ""}'


@admin_bp.route('/<slug>/plan-bloqueado')
@admin_required
def plan_blocked(slug):
    company = get_owned_company_or_404(slug)
    state   = get_plan_state(company)
    return render_template('admin_plan_blocked.html', company=company, state=state)


@admin_bp.route('/<slug>')
@admin_required
def dashboard(slug):
    company    = get_owned_company_or_404(slug)
    plan_state = get_plan_state(company)
    section = request.args.get('section', 'overview')
    if section not in ADMIN_SECTIONS:
        section = 'overview'
    day                      = request.args.get('day')
    selected_day             = datetime.strptime(day, '%Y-%m-%d').date() if day else datetime.now().date()
    selected_professional_id = request.args.get('professional_id', type=int)
    selected_service_id      = request.args.get('service_id', type=int)
    selected_status          = request.args.get('status', '').strip().upper()
    search_customer          = request.args.get('q', '').strip().lower()
    appointments = build_agenda_query(company, selected_day, selected_professional_id, selected_service_id, selected_status, search_customer)

    today = datetime.now().date()

    # ── Grilla de agenda: columnas por profesional ───────────────────────
    agenda_employees = [e for e in company.employees if e.active]
    if selected_professional_id:
        agenda_employees = [e for e in agenda_employees if e.id == selected_professional_id]
    agenda_by_employee = {}
    for ap in appointments:
        if ap.employee_id:
            agenda_by_employee.setdefault(ap.employee_id, []).append(ap)

    company_hours_today = CompanyHours.query.filter_by(company_id=company.id).all()
    if company_hours_today:
        agenda_start_hour = min(h.start_time.hour for h in company_hours_today)
        agenda_end_hour   = max(h.end_time.hour + (1 if h.end_time.minute else 0) for h in company_hours_today)
    else:
        agenda_start_hour, agenda_end_hour = 8, 20
    agenda_start_hour = max(0, min(agenda_start_hour, 6))
    agenda_end_hour   = min(23, max(agenda_end_hour, agenda_start_hour + 4))
    agenda_hour_marks = list(range(agenda_start_hour, agenda_end_hour + 1))

    # ── Mini calendario (mes de selected_day) ─────────────────────────────
    import calendar as _cal
    cal = _cal.Calendar(firstweekday=0)
    mini_cal_weeks = cal.monthdayscalendar(selected_day.year, selected_day.month)
    mini_cal_month_label = MONTH_LABELS[selected_day.month - 1] + f' {selected_day.year}'
    prev_month_date = (selected_day.replace(day=1) - timedelta(days=1))
    next_month_date = (selected_day.replace(day=28) + timedelta(days=7)).replace(day=1)

    # ── Vista rápida (números reales, no filtrados por día seleccionado) ──
    agenda_today_count = Appointment.query.filter(Appointment.company_id==company.id, Appointment.start_dt>=datetime.combine(today,time.min), Appointment.start_dt<=datetime.combine(today,time.max), Appointment.status.in_(['BOOKED','DONE'])).count()
    agenda_week_count  = Appointment.query.filter(Appointment.company_id==company.id, Appointment.status.in_(['BOOKED','DONE']), Appointment.start_dt>=datetime.combine(today - timedelta(days=today.weekday()),time.min), Appointment.start_dt<datetime.combine(today - timedelta(days=today.weekday()) + timedelta(days=7),time.min)).count()
    agenda_unconfirmed_count = Appointment.query.filter(Appointment.company_id==company.id, Appointment.status=='BOOKED', Appointment.start_dt>=datetime.utcnow()).count()
    today = datetime.now().date()
    ms, nm = month_range(today)
    today_count  = Appointment.query.filter(Appointment.company_id==company.id, Appointment.start_dt>=datetime.combine(today,time.min), Appointment.start_dt<=datetime.combine(today,time.max), Appointment.status=='BOOKED').count()
    month_count  = Appointment.query.filter(Appointment.company_id==company.id, Appointment.start_dt>=datetime.combine(ms,time.min), Appointment.start_dt<datetime.combine(nm,time.min)).count()
    active_professionals = Employee.query.filter_by(company_id=company.id, active=True).count()
    active_services      = Service.query.filter_by(company_id=company.id, active=True).count()
    paid_total    = sum(float(p.amount) for p in company.payments if p.status == 'PAID')
    pending_total = sum(float(p.amount) for p in company.payments if p.status != 'PAID')

    # ── Turnos de esta semana vs. semana pasada ──────────────────────────
    week_start = today - timedelta(days=today.weekday())
    week_end   = week_start + timedelta(days=7)
    prev_week_start = week_start - timedelta(days=7)
    week_count = Appointment.query.filter(
        Appointment.company_id==company.id, Appointment.status.in_(['BOOKED','DONE']),
        Appointment.start_dt>=datetime.combine(week_start,time.min), Appointment.start_dt<datetime.combine(week_end,time.min),
    ).count()
    prev_week_count = Appointment.query.filter(
        Appointment.company_id==company.id, Appointment.status.in_(['BOOKED','DONE']),
        Appointment.start_dt>=datetime.combine(prev_week_start,time.min), Appointment.start_dt<datetime.combine(week_start,time.min),
    ).count()
    week_delta = pct_change(prev_week_count, week_count)

    # ── Clientes nuevos esta semana vs. semana pasada ────────────────────
    new_customers_week = Customer.query.filter(
        Customer.company_id==company.id,
        Customer.created_at>=datetime.combine(week_start,time.min), Customer.created_at<datetime.combine(week_end,time.min),
    ).count()
    prev_new_customers_week = Customer.query.filter(
        Customer.company_id==company.id,
        Customer.created_at>=datetime.combine(prev_week_start,time.min), Customer.created_at<datetime.combine(week_start,time.min),
    ).count()
    customers_delta = pct_change(prev_new_customers_week, new_customers_week)

    # ── Ingresos del mes vs. mes pasado (suma del precio de los servicios reservados) ──
    def _revenue_between(start_dt, end_dt):
        total = (db.session.query(func.coalesce(func.sum(Service.price), 0))
                 .join(Appointment, Appointment.service_id == Service.id)
                 .filter(Appointment.company_id==company.id, Appointment.status.in_(['BOOKED','DONE']),
                         Appointment.start_dt>=start_dt, Appointment.start_dt<end_dt).scalar())
        return float(total or 0)

    revenue_month = _revenue_between(datetime.combine(ms,time.min), datetime.combine(nm,time.min))
    prev_ms = (ms - timedelta(days=1)).replace(day=1)
    revenue_prev_month = _revenue_between(datetime.combine(prev_ms,time.min), datetime.combine(ms,time.min))
    revenue_delta = pct_change(revenue_prev_month, revenue_month)

    SERVICE_PALETTE = ['#3654f0','#7c3aed','#c98a1e','#16a34a','#ec4899','#0891b2','#dc2626']
    service_color_map = {}
    for i, svc in enumerate(sorted(company.services, key=lambda s: s.id)):
        service_color_map[svc.id] = svc.color or SERVICE_PALETTE[i % len(SERVICE_PALETTE)]

    recent_activity = build_recent_activity(company)

    # ── Pagos de turnos (lo que cobra el negocio a sus clientes) ─────────
    def _sum_paid(status, start_dt=None, end_dt=None):
        q = db.session.query(func.coalesce(func.sum(Appointment.paid_amount), 0)).filter(
            Appointment.company_id==company.id, Appointment.payment_status==status)
        if start_dt: q = q.filter(Appointment.start_dt>=start_dt)
        if end_dt:   q = q.filter(Appointment.start_dt<end_dt)
        return float(q.scalar() or 0)

    payments_paid_month    = _sum_paid('PAID', datetime.combine(ms,time.min), datetime.combine(nm,time.min))
    payments_paid_prev_month = _sum_paid('PAID', datetime.combine(prev_ms,time.min), datetime.combine(ms,time.min))
    payments_paid_delta    = pct_change(payments_paid_prev_month, payments_paid_month)
    payments_pending_total = _sum_paid('PENDING')
    payments_pending_count = Appointment.query.filter_by(company_id=company.id, payment_status='PENDING').count()
    payments_month_count   = Appointment.query.filter(Appointment.company_id==company.id, Appointment.payment_status=='PAID', Appointment.start_dt>=datetime.combine(ms,time.min), Appointment.start_dt<datetime.combine(nm,time.min)).count()
    payments_total_historic = db.session.query(func.coalesce(func.sum(Appointment.paid_amount), 0)).filter(Appointment.company_id==company.id, Appointment.payment_status=='PAID').scalar()
    payments_total_historic = float(payments_total_historic or 0)

    payments_page = request.args.get('payments_page', 1, type=int)
    PAYMENTS_PAGE_SIZE = 10
    payments_list_q = (Appointment.query.filter(Appointment.company_id==company.id, Appointment.payment_status.isnot(None))
                        .order_by(Appointment.start_dt.desc()))
    payments_total_rows = payments_list_q.count()
    payments_list = payments_list_q.offset((payments_page-1)*PAYMENTS_PAGE_SIZE).limit(PAYMENTS_PAGE_SIZE).all()
    payments_pages = max(1, (payments_total_rows+PAYMENTS_PAGE_SIZE-1)//PAYMENTS_PAGE_SIZE)
    unpaid_appointments = (Appointment.query.filter(Appointment.company_id==company.id, Appointment.payment_status.is_(None), Appointment.status.in_(['BOOKED','DONE']))
                            .order_by(Appointment.start_dt.desc()).limit(30).all())
    upcoming = Appointment.query.filter(Appointment.company_id==company.id, Appointment.start_dt>=datetime.now(), Appointment.status=='BOOKED').order_by(Appointment.start_dt.asc()).limit(8).all()
    svcs_sin_prof  = [s for s in company.services if not s.employees]
    profs_sin_hora = [e for e in company.employees if not e.schedules]

    # Checklist de configuración — cada paso tiene: id, título, descripción, ok, url de acción
    has_services    = len(company.services) > 0
    has_employees   = active_professionals > 0
    has_schedule    = len(profs_sin_hora) == 0 and has_employees
    has_profile     = bool(company.description and company.address)
    all_svcs_linked = len(svcs_sin_prof) == 0 and has_services

    setup_checklist = [
        dict(
            id='profile',
            title='Completá el perfil del negocio',
            desc='Descripción y dirección — aparecen en tu página pública.',
            ok=has_profile,
            url=url_for('admin.dashboard', slug=company.slug, section='company'),
            cta='Completar perfil',
        ),
        dict(
            id='services',
            title='Creá al menos una prestación',
            desc='Las prestaciones son lo que tus clientes van a poder reservar.',
            ok=has_services,
            url=url_for('admin.dashboard', slug=company.slug, section='services'),
            cta='Agregar prestación',
        ),
        dict(
            id='employees',
            title='Agregá un profesional',
            desc='Definí quién va a atender cada prestación.',
            ok=has_employees,
            url=url_for('admin.dashboard', slug=company.slug, section='professionals'),
            cta='Agregar profesional',
        ),
        dict(
            id='link',
            title='Asigná prestaciones al profesional',
            desc='Cada profesional necesita tener al menos una prestación asignada.',
            ok=all_svcs_linked,
            url=url_for('admin.dashboard', slug=company.slug, section='professionals'),
            cta='Revisar asignaciones',
        ),
        dict(
            id='schedule',
            title='Configurá los horarios de atención',
            desc='Sin horarios no se generan turnos disponibles.',
            ok=has_schedule,
            url=url_for('admin.dashboard', slug=company.slug, section='professionals'),
            cta='Cargar horarios',
        ),
    ]
    setup_progress  = int(sum(1 for s in setup_checklist if s['ok']) / len(setup_checklist) * 100)
    setup_complete  = setup_progress == 100

    # setup_items legacy (para no romper el template existente)
    setup_items = [(s['title'], '✓' if s['ok'] else '—', s['ok']) for s in setup_checklist]

    reminders = []
    if not company.services:        reminders.append('Creá al menos una prestación para que los clientes puedan reservar.')
    if svcs_sin_prof:               reminders.append('Asigná profesionales a las prestaciones para generar disponibilidad online.')
    if profs_sin_hora:              reminders.append('Cargá horarios de trabajo para los profesionales sin agenda.')
    if not company.active:          reminders.append('La empresa está desactivada desde plataforma y no se muestra públicamente.')
    if not reminders:               reminders.append('La configuración principal está completa. Ya podés operar la agenda.')
    services_rank  = sorted(company.services, key=lambda s: len([a for a in s.appointments if a.status=='BOOKED']), reverse=True)[:3]
    customers_page  = request.args.get('customers_page', 1, type=int)
    customers_q_str = request.args.get('q', '').strip()
    CUSTOMERS_PAGE_SIZE = 10
    customers_q     = Customer.query.filter_by(company_id=company.id)
    if customers_q_str:
        like = f'%{customers_q_str}%'
        customers_q = customers_q.filter(db.or_(
            Customer.full_name.ilike(like), Customer.email.ilike(like), Customer.phone.ilike(like),
        ))
    customers_q     = customers_q.order_by(Customer.full_name.asc())
    customers_total = customers_q.count()
    customers       = customers_q.offset((customers_page-1)*CUSTOMERS_PAGE_SIZE).limit(CUSTOMERS_PAGE_SIZE).all()
    customers_pages = max(1, (customers_total+CUSTOMERS_PAGE_SIZE-1)//CUSTOMERS_PAGE_SIZE)
    guest_count     = Appointment.query.filter_by(company_id=company.id).filter(Appointment.customer_id.is_(None)).count()

    # ── Métricas reales de la sección Clientes ───────────────────────────
    all_customers_total = Customer.query.filter_by(company_id=company.id).count()
    customers_new_month = Customer.query.filter(Customer.company_id==company.id, Customer.created_at>=datetime.combine(ms,time.min), Customer.created_at<datetime.combine(nm,time.min)).count()
    customers_new_prev_month = Customer.query.filter(Customer.company_id==company.id, Customer.created_at>=datetime.combine(prev_ms,time.min), Customer.created_at<datetime.combine(ms,time.min)).count()
    customers_new_month_delta = pct_change(customers_new_prev_month, customers_new_month)
    cutoff_30d = datetime.combine(today, time.min) - timedelta(days=30)
    customers_with_appts_30d = (db.session.query(func.count(func.distinct(Appointment.customer_id)))
                                 .filter(Appointment.company_id==company.id, Appointment.customer_id.isnot(None),
                                         Appointment.start_dt>=cutoff_30d).scalar()) or 0
    customers_without_appts_30d = max(0, all_customers_total - customers_with_appts_30d)
    with_appts_pct = round((customers_with_appts_30d / all_customers_total) * 100) if all_customers_total else 0
    without_appts_pct = 100 - with_appts_pct if all_customers_total else 0
    blocked_type_filter = request.args.get('block_type', '')
    blocked_periods_q = BlockedPeriod.query.filter_by(company_id=company.id)
    if blocked_type_filter in ('vacation','training','manual','holiday'):
        blocked_periods_q = blocked_periods_q.filter_by(block_type=blocked_type_filter)
    blocked_periods = blocked_periods_q.order_by(BlockedPeriod.start_dt.desc()).all()
    manual_slots_raw, manual_service_id, manual_employee_id = [], request.args.get('manual_service_id', type=int), request.args.get('manual_employee_id', type=int)
    if manual_service_id and manual_employee_id:
        svc = Service.query.filter_by(company_id=company.id, id=manual_service_id, active=True).first()
        emp = Employee.query.filter_by(company_id=company.id, id=manual_employee_id, active=True).first()
        if svc and emp and svc in emp.services:
            manual_slots_raw = get_availability_for_day(company, svc, selected_day, emp.id, ignore_past=True)
    seen, manual_slots = set(), []
    for slot in manual_slots_raw:
        key = slot['start'].isoformat()
        if key not in seen:
            seen.add(key); manual_slots.append(slot)
    employees_by_service = {srv.id: [{'id': e.id, 'name': e.name} for e in company.employees if e.active and srv in e.services] for srv in company.services}
    # Secciones restringidas a rol 'admin' — staff solo ve agenda, clientes y overview
    STAFF_ALLOWED = {'overview', 'agenda', 'customers'}
    if getattr(current_user, 'role', 'admin') == 'staff' and section not in STAFF_ALLOWED:
        flash('No tenés permisos para acceder a esa sección.', 'warning')
        section = 'agenda'
    return render_template('admin_dashboard.html',
        company=company, google_plan_enabled=company_has_google_plan(company),
        appointments=appointments, customers=customers, customers_page=customers_page,
        customers_pages=customers_pages, customers_total=customers_total, customers_search=customers_q_str,
        customers_all_total=all_customers_total, customers_new_month=customers_new_month,
        customers_new_month_delta=customers_new_month_delta,
        customers_with_appts_30d=customers_with_appts_30d, customers_without_appts_30d=customers_without_appts_30d,
        with_appts_pct=with_appts_pct, without_appts_pct=without_appts_pct,
        selected_day=selected_day, weekday_labels=WEEKDAY_LABELS, active_section=section,
        stats=dict(today_appointments=today_count, month_appointments=month_count,
                   professionals=active_professionals, services=active_services,
                   paid_total=paid_total, pending_total=pending_total,
                   customers=all_customers_total, guests=guest_count,
                   week_appointments=week_count, week_delta=week_delta,
                   new_customers_week=new_customers_week, customers_delta=customers_delta,
                   revenue_month=revenue_month, revenue_delta=revenue_delta),
        upcoming=upcoming, services_rank=services_rank, reminders=reminders,
        recent_activity=recent_activity, blocked_type_filter=blocked_type_filter,
        payments_paid_month=payments_paid_month, payments_paid_delta=payments_paid_delta,
        payments_pending_total=payments_pending_total, payments_pending_count=payments_pending_count,
        payments_month_count=payments_month_count, payments_total_historic=payments_total_historic,
        payments_list=payments_list, payments_page=payments_page, payments_pages=payments_pages,
        payments_total_rows=payments_total_rows, unpaid_appointments=unpaid_appointments,
        service_color_map=service_color_map,
        agenda_employees=agenda_employees, agenda_by_employee=agenda_by_employee,
        agenda_start_hour=agenda_start_hour, agenda_end_hour=agenda_end_hour, agenda_hour_marks=agenda_hour_marks,
        mini_cal_weeks=mini_cal_weeks, mini_cal_month_label=mini_cal_month_label,
        prev_month_date=prev_month_date, next_month_date=next_month_date,
        agenda_today_count=agenda_today_count, agenda_week_count=agenda_week_count,
        agenda_unconfirmed_count=agenda_unconfirmed_count,
        setup_items=setup_items, setup_progress=setup_progress,
        services_without_professionals=svcs_sin_prof,
        professionals_without_services=[e for e in company.employees if not e.services],
        professionals_without_schedules=profs_sin_hora,
        sections=ADMIN_SECTIONS, selected_professional_id=selected_professional_id,
        selected_service_id=selected_service_id, selected_status=selected_status,
        search_customer=search_customer, status_options=STATUS_OPTIONS,
        blocked_periods=blocked_periods, manual_slots=manual_slots,
        manual_service_id=manual_service_id, manual_employee_id=manual_employee_id,
        employees_by_service=employees_by_service,
        timedelta=timedelta,
        plan_state=plan_state,
        setup_checklist=setup_checklist,
        setup_complete=setup_complete,
    )

@admin_bp.route('/<slug>/agenda.csv')
@admin_required
def export_agenda_csv(slug):
    company      = get_owned_company_or_404(slug)
    day          = request.args.get('day')
    selected_day = datetime.strptime(day, '%Y-%m-%d').date() if day else datetime.now().date()
    apps         = build_agenda_query(company, selected_day, request.args.get('professional_id',type=int), request.args.get('service_id',type=int), request.args.get('status','').strip().upper(), request.args.get('q','').strip().lower())
    buf = io.StringIO()
    w   = csv.writer(buf)
    w.writerow(['fecha','hora_inicio','hora_fin','cliente','telefono','servicio','profesional','estado','notas'])
    for ap in apps:
        w.writerow([ap.start_dt.strftime('%Y-%m-%d'), ap.start_dt.strftime('%H:%M'), ap.end_dt.strftime('%H:%M'),
                    ap.customer_display_name, ap.customer_display_phone,
                    ap.service.name if ap.service else '', ap.employee.name if ap.employee else '',
                    ap.status, ap.notes or ''])
    return Response(buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="agenda_{company.slug}_{selected_day.isoformat()}.csv"'})

def _save_uploaded_image(file_storage, company_id):
    """Guarda una imagen subida (png/jpg, máx 2MB) como bytes en la base de datos
    (sobrevive a redeploys, no depende de almacenamiento en disco) y devuelve
    la URL pública para servirla, o None. Valida la firma real del archivo
    (magic bytes), no solo la extensión del nombre."""
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in ('png', 'jpg', 'jpeg'):
        return None
    file_storage.seek(0, os.SEEK_END); size = file_storage.tell(); file_storage.seek(0)
    if size > 2 * 1024 * 1024:
        flash('La imagen supera los 2MB permitidos.', 'warning')
        return None
    header = file_storage.read(12); file_storage.seek(0)
    is_png  = header.startswith(b'\x89PNG\r\n\x1a\n')
    is_jpeg = header.startswith(b'\xff\xd8\xff')
    if not (is_png or is_jpeg):
        flash('El archivo no parece ser una imagen PNG o JPG válida.', 'warning')
        return None
    mime_type = 'image/png' if is_png else 'image/jpeg'
    image = UploadedImage(company_id=company_id, mime_type=mime_type, data=file_storage.read())
    db.session.add(image)
    db.session.flush()  # para tener image.id antes del commit final del caller
    return url_for('media.serve_image', image_id=image.id)


@admin_bp.route('/<slug>/company', methods=['POST'])
@owner_required
def update_company(slug):
    company = get_owned_company_or_404(slug)
    target_section = request.form.get('target_section', 'company')

    if target_section == 'settings':
        cfg = company.config
        cfg.require_customer_login=         'require_customer_login'         in request.form
        cfg.allow_booking_by_availability=  'allow_booking_by_availability'  in request.form
        cfg.allow_booking_by_employee=      'allow_booking_by_employee'      in request.form
        cfg.allow_customer_choose_employee= 'allow_customer_choose_employee' in request.form
        cfg.required_name=  'required_name'  in request.form
        cfg.required_phone= 'required_phone' in request.form
        cfg.required_email= 'required_email' in request.form
        cfg.required_dni=   'required_dni'   in request.form
        cfg.show_address_public = 'show_address_public' in request.form
        cfg.show_phone_public   = 'show_phone_public'   in request.form
        cfg.show_email_public   = 'show_email_public'   in request.form
        try:
            company.cancelation_limit_hours = int(request.form.get('cancelation_limit_hours', 24))
        except (ValueError, TypeError):
            pass
        company.cancelation_penalty_enabled = 'cancelation_penalty_enabled' in request.form
        try:
            company.cancelation_penalty_amount = float(request.form.get('cancelation_penalty_amount', 0) or 0)
        except (ValueError, TypeError):
            pass
    else:
        company.name=request.form.get('name','').strip() or company.name
        company.category=request.form.get('category','').strip() or company.category
        logo_file = request.files.get('logo')
        logo_url = _save_uploaded_image(logo_file, company.id)
        if logo_url:
            company.logo_url = logo_url
        elif 'remove_logo' in request.form:
            company.logo_url = None
        cover_url = _save_uploaded_image(request.files.get('cover_photo'), company.id)
        if cover_url:
            company.cover_photo_url = cover_url
        elif 'remove_cover_photo' in request.form:
            company.cover_photo_url = None
        # Estos campos solo se tocan si realmente vinieron en el form que se envió
        # (el de logo y el de portada no los incluyen, y no deben borrarlos).
        if 'description' in request.form:
            company.description = request.form.get('description', '').strip() or None
        if 'address' in request.form:
            company.address = request.form.get('address', '').strip() or None
        if 'phone' in request.form:
            company.phone = request.form.get('phone', '').strip() or None
        if 'email' in request.form:
            company.email = request.form.get('email', '').strip() or None
        if 'brand_color' in request.form:
            company.brand_color = request.form.get('brand_color', company.brand_color)
        if 'instagram_url' in request.form:
            company.instagram_url = request.form.get('instagram_url', '').strip() or None
        if 'facebook_url' in request.form:
            company.facebook_url = request.form.get('facebook_url', '').strip() or None

    db.session.commit()
    flash('Configuración actualizada.', 'success')
    return redirect(url_for('admin.dashboard', slug=slug, section=target_section))

@admin_bp.route('/<slug>/services', methods=['POST'])
@owner_required
def create_service(slug):
    company=get_owned_company_or_404(slug); name=request.form.get('name','').strip(); duration=request.form.get('duration_min',type=int)
    if not name or not duration or duration<=0:
        flash('Completá nombre y duración válida.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='services'))
    photo_url = _save_uploaded_image(request.files.get('photo'), company.id)
    db.session.add(Service(company=company,name=name,short_description=request.form.get('short_description','').strip() or None,long_description=request.form.get('long_description','').strip() or None,duration_min=duration,price=request.form.get('price',type=float) or 0,active='active' in request.form,color=request.form.get('color','').strip() or None,photo_url=photo_url))
    db.session.commit(); flash('Prestación creada.','success'); return redirect(url_for('admin.dashboard',slug=slug,section='services'))

@admin_bp.route('/<slug>/services/<int:service_id>/update', methods=['POST'])
@owner_required
def update_service(slug, service_id):
    company=get_owned_company_or_404(slug); service=Service.query.filter_by(company_id=company.id,id=service_id).first_or_404()
    name=request.form.get('name','').strip(); duration=request.form.get('duration_min',type=int)
    if not name or not duration or duration<=0:
        flash('Revisá nombre y duración.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='services'))
    service.name=name; service.short_description=request.form.get('short_description','').strip() or None
    service.long_description=request.form.get('long_description','').strip() or None
    service.duration_min=duration; service.price=request.form.get('price',type=float) or 0; service.active='active' in request.form
    if request.form.get('color','').strip():
        service.color = request.form.get('color').strip()
    new_photo_url = _save_uploaded_image(request.files.get('photo'), company.id)
    if new_photo_url:
        service.photo_url = new_photo_url
    elif 'remove_photo' in request.form:
        service.photo_url = None
    db.session.commit(); flash('Prestación actualizada.','success'); return redirect(url_for('admin.dashboard',slug=slug,section='services'))

@admin_bp.route('/<slug>/services/<int:service_id>/delete', methods=['POST'])
@owner_required
def delete_service(slug, service_id):
    company=get_owned_company_or_404(slug); service=Service.query.filter_by(company_id=company.id,id=service_id).first_or_404()
    if service.appointments:
        service.active=False; db.session.commit(); flash('La prestación tenía historial. Se ocultó.','warning')
    else:
        db.session.delete(service); db.session.commit(); flash('Prestación eliminada.','success')
    return redirect(url_for('admin.dashboard',slug=slug,section='services'))

@admin_bp.route('/<slug>/employees', methods=['POST'])
@owner_required
def create_employee(slug):
    company=get_owned_company_or_404(slug); name=request.form.get('name','').strip()
    if not name:
        flash('El nombre del profesional es obligatorio.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='professionals'))
    employee=Employee(company=company, name=name,
                      color=request.form.get('color','#0d6efd'),
                      active='active' in request.form,
                      photo_url=request.form.get('photo_url','').strip() or None,
                      bio=request.form.get('bio','').strip() or None)
    sids={int(s) for s in request.form.getlist('service_ids') if s.isdigit()}
    for svc in company.services:
        if svc.id in sids: employee.services.append(svc)
    db.session.add(employee); db.session.flush()
    blocks=parse_employee_schedule_blocks(company)
    if not blocks:
        flash('Agregá al menos una franja horaria.','danger'); db.session.rollback(); return redirect(url_for('admin.dashboard',slug=slug,section='professionals'))
    replace_employee_schedules(employee,company,blocks); db.session.commit(); flash('Profesional creado.','success')
    return redirect(url_for('admin.dashboard',slug=slug,section='professionals'))

@admin_bp.route('/<slug>/employees/<int:employee_id>/update', methods=['POST'])
@owner_required
def update_employee(slug, employee_id):
    company=get_owned_company_or_404(slug); employee=Employee.query.filter_by(company_id=company.id,id=employee_id).first_or_404()
    name=request.form.get('name','').strip()
    if not name:
        flash('El profesional debe tener nombre.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='professionals'))
    employee.name=name; employee.color=request.form.get('color',employee.color)
    employee.active='active' in request.form
    employee.photo_url=request.form.get('photo_url','').strip() or None
    employee.bio=request.form.get('bio','').strip() or None
    employee.services.clear()
    sids={int(s) for s in request.form.getlist('service_ids') if s.isdigit()}
    for svc in company.services:
        if svc.id in sids: employee.services.append(svc)
    blocks=parse_employee_schedule_blocks(company)
    if not blocks:
        flash('Agregá al menos una franja horaria.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='professionals'))
    orphaned = find_appointments_outside_schedule(employee, blocks)
    replace_employee_schedules(employee,company,blocks); db.session.commit()
    if orphaned:
        detalle = '; '.join(f'{ap.customer_display_name} el {ap.start_dt.strftime("%d/%m")} a las {ap.start_dt.strftime("%H:%M")}' for ap in orphaned[:5])
        extra = f' y {len(orphaned) - 5} más' if len(orphaned) > 5 else ''
        flash(f'Horario actualizado. Ojo: {len(orphaned)} turno(s) ya reservado(s) de {employee.name} quedaron fuera del horario nuevo y no se cancelaron solos — revisalos vos: {detalle}{extra}.', 'warning')
    else:
        flash('Profesional actualizado.','success')
    return redirect(url_for('admin.dashboard',slug=slug,section='professionals'))

@admin_bp.route('/<slug>/employees/<int:employee_id>/delete', methods=['POST'])
@owner_required
def delete_employee(slug, employee_id):
    company=get_owned_company_or_404(slug); employee=Employee.query.filter_by(company_id=company.id,id=employee_id).first_or_404()
    if employee.appointments:
        employee.active=False; db.session.commit(); flash('El profesional tenía historial. Se desactivó.','warning')
    else:
        db.session.delete(employee); db.session.commit(); flash('Profesional eliminado.','success')
    return redirect(url_for('admin.dashboard',slug=slug,section='professionals'))

@admin_bp.route('/<slug>/api/slots')
@admin_required
def admin_slots_api(slug):
    """JSON endpoint: devuelve horarios disponibles para alta manual de turno."""
    company = get_owned_company_or_404(slug)
    service_id  = request.args.get('service_id', type=int)
    employee_id = request.args.get('employee_id', type=int)
    day_str     = request.args.get('day', '')
    try:
        day = datetime.fromisoformat(day_str).date() if day_str else datetime.today().date()
    except ValueError:
        day = datetime.today().date()
    if not service_id or not employee_id:
        return jsonify([])
    service  = Service.query.filter_by(company_id=company.id, id=service_id,  active=True).first()
    employee = Employee.query.filter_by(company_id=company.id, id=employee_id, active=True).first()
    if not service or not employee or service not in employee.services:
        return jsonify([])
    ignore_blocks = request.args.get('ignore_blocks') == '1'
    raw_slots = get_availability_for_day(company, service, day, employee.id, ignore_past=True, ignore_blocks=ignore_blocks)
    seen, slots = set(), []
    for s in raw_slots:
        key = s['start'].isoformat()
        if key not in seen:
            seen.add(key)
            slots.append({'value': key, 'label': s['start'].strftime('%H:%M')})
    return jsonify(slots)


@admin_bp.route('/<slug>/appointments/manual', methods=['POST'])
@admin_required
def create_manual_appointment(slug):
    company=get_owned_company_or_404(slug)
    service=Service.query.filter_by(company_id=company.id,id=request.form.get('service_id',type=int),active=True).first_or_404()
    employee=Employee.query.filter_by(company_id=company.id,id=request.form.get('employee_id',type=int),active=True).first_or_404()
    if service not in employee.services:
        flash('Ese profesional no realiza la prestación elegida.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='agenda'))
    raw=request.form.get('start_dt','').strip()
    if not raw:
        flash('Seleccioná un horario válido.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='agenda'))
    start_dt=datetime.fromisoformat(raw)
    ignore_blocks = request.form.get('ignore_blocks') == '1'
    slots=get_availability_for_day(company,service,start_dt.date(),employee.id,ignore_past=True,ignore_blocks=ignore_blocks)
    selected=next((s for s in slots if s['start']==start_dt),None)
    if not selected:
        flash('Ese horario no está disponible.','danger')
        return redirect(url_for('admin.dashboard',slug=slug,section='agenda',day=start_dt.date().isoformat(),manual_service_id=service.id,manual_employee_id=employee.id))
    customer_id=request.form.get('customer_id',type=int); guest_name=request.form.get('guest_name','').strip()
    if not customer_id and not guest_name:
        flash('Elegí un cliente existente o completá el nombre del invitado.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='agenda'))
    override_note = ' (turno forzado, ignorando un bloqueo de agenda)' if ignore_blocks else ''
    appointment=Appointment(company=company,service=service,employee=employee,start_dt=selected['start'],end_dt=selected['end'],status='BOOKED',notes=(request.form.get('notes','').strip() or None),manage_token=secrets.token_urlsafe(24))
    if customer_id:
        appointment.customer=Customer.query.filter_by(company_id=company.id,id=customer_id).first_or_404()
    else:
        appointment.guest_name=guest_name; appointment.guest_phone=request.form.get('guest_phone','').strip() or None
        appointment.guest_email=request.form.get('guest_email','').strip() or None; appointment.guest_dni=request.form.get('guest_dni','').strip() or None
    db.session.add(appointment); db.session.flush()
    audit_log.log_created(appointment, notes=f'Alta manual desde panel{override_note}')
    db.session.commit()
    ensure_google_event_for_appointment(appointment)
    send_booking_confirmed(appointment,manage_url=url_for('public.manage_appointment',slug=slug,token=appointment.manage_token,_external=True),company_url=url_for('public.company_page',slug=slug,_external=True))
    flash('Turno creado manualmente.','success')
    return redirect(url_for('admin.dashboard',slug=slug,section='agenda',day=start_dt.date().isoformat()))

@admin_bp.route('/<slug>/appointments/<int:appointment_id>/status', methods=['POST'])
@admin_required
def update_appointment_status(slug, appointment_id):
    company=get_owned_company_or_404(slug); appointment=Appointment.query.filter_by(company_id=company.id,id=appointment_id).first_or_404()
    status=request.form.get('status','').strip().upper()
    if status not in STATUS_OPTIONS:
        flash('Estado inválido.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='agenda',day=appointment.start_dt.date().isoformat()))
    old_status = appointment.status
    appointment.status = status
    if request.form.get('notes','').strip(): appointment.notes=request.form['notes'].strip()
    audit_log.log_status_changed(appointment, old_status, status,
                                 notes=request.form.get('notes','').strip())
    db.session.commit()
    if status=='CANCELED':
        delete_google_event_for_appointment(appointment)
        send_booking_canceled(appointment,company_url=url_for('public.company_page',slug=slug,_external=True))
    elif status=='BOOKED':
        ensure_google_event_for_appointment(appointment)
    flash('Estado del turno actualizado.','success')
    return redirect(url_for('admin.dashboard',slug=slug,section='agenda',day=appointment.start_dt.date().isoformat()))

@admin_bp.route('/<slug>/appointments/payment', methods=['POST'])
@owner_required
def update_appointment_payment(slug):
    company=get_owned_company_or_404(slug)
    appointment_id = request.form.get('appointment_id', type=int)
    appointment = Appointment.query.filter_by(company_id=company.id, id=appointment_id).first_or_404()
    status = request.form.get('payment_status','').strip().upper()
    if status not in ('PAID','PENDING'):
        flash('Estado de pago inválido.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='payments'))
    appointment.payment_status = status
    appointment.payment_method = request.form.get('payment_method','').strip() or None
    amount = request.form.get('paid_amount', type=float)
    appointment.paid_amount = amount if amount is not None else (appointment.service.price if appointment.service else None)
    appointment.payment_notes = request.form.get('payment_notes','').strip() or None
    db.session.commit()
    flash('Pago actualizado.','success')
    return redirect(url_for('admin.dashboard',slug=slug,section='payments'))

@admin_bp.route('/<slug>/appointments/<int:appointment_id>/reschedule', methods=['POST'])
@admin_required
def reschedule_appointment(slug, appointment_id):
    company=get_owned_company_or_404(slug); appointment=Appointment.query.filter_by(company_id=company.id,id=appointment_id).first_or_404()
    service=Service.query.filter_by(company_id=company.id,id=request.form.get('service_id',type=int),active=True).first_or_404()
    employee=Employee.query.filter_by(company_id=company.id,id=request.form.get('employee_id',type=int),active=True).first_or_404()
    if service not in employee.services:
        flash('El profesional no realiza esa prestación.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='agenda',day=appointment.start_dt.date().isoformat()))
    raw=request.form.get('start_dt','').strip()
    if not raw:
        flash('Seleccioná una nueva fecha y hora.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='agenda',day=appointment.start_dt.date().isoformat()))
    start_dt=datetime.fromisoformat(raw); original_status=appointment.status; appointment.status='CANCELED'; db.session.flush()
    slots=get_availability_for_day(company,service,start_dt.date(),employee.id,ignore_past=True)
    selected=next((s for s in slots if s['start']==start_dt),None)
    if not selected:
        appointment.status=original_status; db.session.rollback(); flash('No se pudo reprogramar — ese horario ya no está libre.','danger')
        return redirect(url_for('admin.dashboard',slug=slug,section='agenda',day=appointment.start_dt.date().isoformat()))
    old_dt = appointment.start_dt
    appointment.status='BOOKED'; appointment.service=service; appointment.employee=employee
    appointment.start_dt=selected['start']; appointment.end_dt=selected['end']
    audit_log.log_rescheduled(appointment, old_dt, selected['start'])
    db.session.commit(); ensure_google_event_for_appointment(appointment)
    send_booking_rescheduled(appointment,manage_url=url_for('public.manage_appointment',slug=slug,token=appointment.manage_token,_external=True))
    flash('Turno reprogramado.','success'); return redirect(url_for('admin.dashboard',slug=slug,section='agenda',day=start_dt.date().isoformat()))

@admin_bp.route('/<slug>/customers', methods=['POST'])
@admin_required
def create_customer(slug):
    company=get_owned_company_or_404(slug); full_name=request.form.get('full_name','').strip(); email=request.form.get('email','').strip().lower(); password=request.form.get('password','').strip()
    if not full_name or not email:
        flash('Nombre y email son obligatorios.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='customers'))
    if Customer.query.filter_by(company_id=company.id,email=email).first():
        flash('Ya existe un cliente con ese email.','warning'); return redirect(url_for('admin.dashboard',slug=slug,section='customers'))
    customer=Customer(company=company,full_name=full_name,email=email,phone=request.form.get('phone','').strip() or None,dni=request.form.get('dni','').strip() or None,tags=request.form.get('tags','').strip() or None,notes=request.form.get('notes','').strip() or None,needs_password_setup=not bool(password))
    customer.set_password(password if password else secrets.token_urlsafe(32)); db.session.add(customer); db.session.commit()
    flash('Cliente creado.' + ('' if password else ' Podrá definir su contraseña la primera vez que ingrese.'),'success')
    return redirect(url_for('admin.dashboard',slug=slug,section='customers'))

@admin_bp.route('/<slug>/customers/<int:customer_id>/update', methods=['POST'])
@admin_required
def update_customer(slug, customer_id):
    company=get_owned_company_or_404(slug); customer=Customer.query.filter_by(company_id=company.id,id=customer_id).first_or_404()
    email=request.form.get('email','').strip().lower()
    if Customer.query.filter(Customer.company_id==company.id,Customer.email==email,Customer.id!=customer.id).first():
        flash('Ya existe otro cliente con ese email.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='customers'))
    customer.full_name=request.form.get('full_name','').strip() or customer.full_name; customer.email=email or customer.email
    customer.phone=request.form.get('phone','').strip() or None; customer.dni=request.form.get('dni','').strip() or None
    customer.tags=request.form.get('tags','').strip() or None; customer.notes=request.form.get('notes','').strip() or None
    new_pw=request.form.get('password','').strip()
    if new_pw:
        if len(new_pw)<6:
            flash('La contraseña debe tener al menos 6 caracteres.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='customers'))
        customer.set_password(new_pw); customer.needs_password_setup=False
    db.session.commit(); flash('Cliente actualizado.','success'); return redirect(url_for('admin.dashboard',slug=slug,section='customers'))

@admin_bp.route('/<slug>/blocked', methods=['POST'])
@owner_required
def create_blocked_period(slug):
    company=get_owned_company_or_404(slug)
    start_dt=parse_datetime_or_none(request.form.get('start_date'),request.form.get('start_time'))
    end_dt=parse_datetime_or_none(request.form.get('end_date'),request.form.get('end_time'))
    if not start_dt or not end_dt or start_dt>=end_dt:
        flash('Ingresá un rango horario válido.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='blocked'))
    employee_id=request.form.get('employee_id',type=int)
    employee=Employee.query.filter_by(company_id=company.id,id=employee_id).first() if employee_id else None
    block_type = request.form.get('block_type', 'manual')
    if block_type not in ('vacation','training','manual','holiday'):
        block_type = 'manual'
    db.session.add(BlockedPeriod(company=company,employee=employee,title=request.form.get('title','').strip() or 'Bloqueo',block_type=block_type,start_dt=start_dt,end_dt=end_dt,notes=request.form.get('notes','').strip() or None))
    db.session.commit(); flash('Bloqueo creado.','success'); return redirect(url_for('admin.dashboard',slug=slug,section='blocked'))

@admin_bp.route('/<slug>/blocked/<int:block_id>/delete', methods=['POST'])
@owner_required
def delete_blocked_period(slug, block_id):
    company=get_owned_company_or_404(slug); block=BlockedPeriod.query.filter_by(company_id=company.id,id=block_id).first_or_404()
    db.session.delete(block); db.session.commit(); flash('Bloqueo eliminado.','success')
    return redirect(url_for('admin.dashboard',slug=slug,section='blocked'))

@admin_bp.route('/<slug>/payments', methods=['POST'])
@owner_required
def add_payment(slug):
    company=get_owned_company_or_404(slug)
    db.session.add(SubscriptionPayment(company=company,amount=request.form.get('amount',type=float) or 0,method=request.form.get('method','Transferencia').strip() or 'Transferencia',status=request.form.get('status','PAID').strip() or 'PAID',notes=request.form.get('notes','').strip() or None))
    db.session.commit(); flash('Pago registrado.','success'); return redirect(url_for('admin.dashboard',slug=slug,section='payments'))

@admin_bp.route('/<slug>/integrations/google/connect')
@owner_required
def google_connect(slug):
    company=get_owned_company_or_404(slug)
    if not company_has_google_plan(company):
        flash('La sincronización con Google Calendar requiere plan PRO/PREMIUM activo.','warning'); return redirect(url_for('admin.dashboard',slug=slug,section='integrations'))
    oauth_cfg=get_google_oauth_config()
    if not oauth_cfg:
        flash('Faltan variables GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET.','danger'); return redirect(url_for('admin.dashboard',slug=slug,section='integrations'))
    from flask import session
    from google_auth_oauthlib.flow import Flow
    redirect_uri=build_redirect_uri(request,slug)
    flow=Flow.from_client_config({'web':{'client_id':oauth_cfg['client_id'],'client_secret':oauth_cfg['client_secret'],'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token'}},scopes=GOOGLE_SCOPES)
    flow.redirect_uri=redirect_uri
    authorization_url,state=flow.authorization_url(access_type='offline',include_granted_scopes='true',prompt='consent')
    session['google_oauth_state']=state; session['google_oauth_company_id']=company.id
    return redirect(authorization_url)

@admin_bp.route('/<slug>/integrations/google/callback')
@admin_required
def google_callback(slug):
    company=get_owned_company_or_404(slug)
    from flask import session
    from google_auth_oauthlib.flow import Flow
    oauth_cfg=get_google_oauth_config(); expected_state=session.get('google_oauth_state')
    if not oauth_cfg or not expected_state:
        flash('Sesión OAuth inválida. Intentá conectar nuevamente.','warning'); return redirect(url_for('admin.dashboard',slug=slug,section='integrations'))
    redirect_uri=build_redirect_uri(request,slug)
    flow=Flow.from_client_config({'web':{'client_id':oauth_cfg['client_id'],'client_secret':oauth_cfg['client_secret'],'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token'}},scopes=GOOGLE_SCOPES,state=expected_state)
    flow.redirect_uri=redirect_uri; flow.fetch_token(authorization_response=request.url); creds=flow.credentials
    conn=GoogleCalendarConnection.query.filter_by(company_id=company.id).first()
    if not conn:
        conn=GoogleCalendarConnection(company_id=company.id); db.session.add(conn)
    conn.enabled=True; conn.admin_user_id=current_user.id; conn.calendar_id='primary'
    conn.refresh_token=creds.refresh_token or conn.refresh_token; conn.access_token=creds.token; conn.token_expiry=creds.expiry; conn.scopes=' '.join(creds.scopes or GOOGLE_SCOPES)
    db.session.commit(); session.pop('google_oauth_state',None); session.pop('google_oauth_company_id',None)
    flash('Google Calendar conectado.','success'); return redirect(url_for('admin.dashboard',slug=slug,section='integrations'))

@admin_bp.route('/<slug>/integrations/google/disconnect', methods=['POST'])
@owner_required
def google_disconnect(slug):
    company=get_owned_company_or_404(slug); conn=GoogleCalendarConnection.query.filter_by(company_id=company.id).first()
    if conn:
        conn.enabled=False; conn.refresh_token=conn.access_token=conn.token_expiry=None; db.session.commit()
    flash('Google Calendar desconectado.','success'); return redirect(url_for('admin.dashboard',slug=slug,section='integrations'))


# ── Gestión de usuarios del panel (multi-admin) ───────────────────────────────

@admin_bp.route('/<slug>/team', methods=['GET', 'POST'])
@admin_required
def team(slug):
    """Lista y crea usuarios del panel (admins y staff)."""
    company = get_owned_company_or_404(slug)
    # Solo el rol 'admin' puede gestionar el equipo
    if getattr(current_user, 'role', 'admin') != 'admin':
        flash('No tenés permisos para gestionar usuarios del panel.', 'warning')
        return redirect(url_for('admin.dashboard', slug=slug))

    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role     = request.form.get('role', 'staff')

        if not name or not email:
            flash('Nombre y email son obligatorios.', 'danger')
        elif len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres.', 'danger')
        elif AdminUser.query.filter_by(company_id=company.id, email=email).first():
            flash('Ya existe un usuario con ese email en tu empresa.', 'warning')
        else:
            new_admin = AdminUser(
                company_id=company.id,
                name=name, email=email,
                active=True, role=role,
            )
            new_admin.set_password(password)
            db.session.add(new_admin)
            db.session.commit()
            flash(f'Usuario "{name}" creado con rol {role}.', 'success')

        return redirect(url_for('admin.team', slug=slug))

    admins = AdminUser.query.filter_by(company_id=company.id).order_by(AdminUser.id).all()
    return render_template('admin_team.html', company=company, admins=admins,
                           sections=ADMIN_SECTIONS, active_section='team')


@admin_bp.route('/<slug>/team/<int:admin_id>/update', methods=['POST'])
@admin_required
def update_team_member(slug, admin_id):
    company = get_owned_company_or_404(slug)
    if getattr(current_user, 'role', 'admin') != 'admin':
        flash('Sin permisos.', 'warning')
        return redirect(url_for('admin.team', slug=slug))

    member = AdminUser.query.filter_by(company_id=company.id, id=admin_id).first_or_404()

    # No puede modificarse a sí mismo de forma destructiva
    if member.id == current_user.id and request.form.get('role') != 'admin':
        flash('No podés quitarte el rol admin a vos mismo.', 'danger')
        return redirect(url_for('admin.team', slug=slug))

    member.name   = request.form.get('name', member.name).strip() or member.name
    member.active = 'active' in request.form
    member.role   = request.form.get('role', member.role)

    new_password = request.form.get('password', '').strip()
    if new_password:
        if len(new_password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres.', 'danger')
            return redirect(url_for('admin.team', slug=slug))
        member.set_password(new_password)

    db.session.commit()
    flash('Usuario actualizado.', 'success')
    return redirect(url_for('admin.team', slug=slug))


@admin_bp.route('/<slug>/team/<int:admin_id>/delete', methods=['POST'])
@admin_required
def delete_team_member(slug, admin_id):
    company = get_owned_company_or_404(slug)
    if getattr(current_user, 'role', 'admin') != 'admin':
        flash('Sin permisos.', 'warning')
        return redirect(url_for('admin.team', slug=slug))

    member = AdminUser.query.filter_by(company_id=company.id, id=admin_id).first_or_404()
    if member.id == current_user.id:
        flash('No podés eliminarte a vos mismo.', 'danger')
        return redirect(url_for('admin.team', slug=slug))

    db.session.delete(member)
    db.session.commit()
    flash('Usuario eliminado.', 'success')
    return redirect(url_for('admin.team', slug=slug))


# ── Historial de turno (auditoría) ────────────────────────────────────────────

@admin_bp.route('/<slug>/appointments/<int:appointment_id>/log')
@admin_required
def appointment_log(slug, appointment_id):
    company     = get_owned_company_or_404(slug)
    appointment = Appointment.query.filter_by(company_id=company.id, id=appointment_id).first_or_404()
    logs        = appointment.logs.order_by('created_at').all()
    return render_template('appointment_log.html', company=company,
                           appointment=appointment, logs=logs,
                           sections=ADMIN_SECTIONS, active_section='agenda')
