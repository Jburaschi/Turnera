"""
Blueprint de onboarding self-service — wizard de alta en 8 pasos:
  1. /registrar              → crear cuenta
  2. /registrar/negocio      → información del negocio
  3. /registrar/equipo       → quién atiende (solo / equipo)
  4. /registrar/servicios    → servicios que ofrece
  5. /registrar/horarios     → horarios de atención
  6. /registrar/vista-previa → previsualizar
  7. /registrar/publicar     → checklist final + publicar
  8. /registrar/listo        → confirmación

Todo lo cargado acá impacta directo en el motor de turnos real: se crea un
Employee reservable, con sus Service asociados y su EmployeeSchedule — no es
un asistente decorativo, el negocio queda con disponibilidad real al publicar.
"""
from __future__ import annotations
import os
import re
import unicodedata
import uuid
from datetime import datetime, time, timedelta
from flask import Blueprint, current_app, redirect, render_template, request, url_for
from flask_login import login_user, current_user
from werkzeug.utils import secure_filename
from ..extensions import db, limiter
from ..models import AdminUser, Company, CompanyConfig, Service, CompanyHours, Employee, EmployeeSchedule, UploadedImage
from ..services.email_service import send_welcome_admin

TRIAL_DAYS = 14
LOGO_EXTS  = {'png', 'jpg', 'jpeg'}
LOGO_MAX_BYTES = 2 * 1024 * 1024

CATEGORIES = [
    'Barberías', 'Peluquerías', 'Spa y estética', 'Uñas y pestañas',
    'Consultorios médicos', 'Centros de salud', 'Gimnasios y entrenadores',
    'Tatuajes y piercing', 'Veterinarias', 'Otros servicios',
]

WEEKDAYS = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

TIMEZONES = [
    ('America/Argentina/Buenos_Aires', '(GMT-03:00) Buenos Aires'),
    ('America/Santiago', '(GMT-04:00) Santiago'),
    ('America/Montevideo', '(GMT-03:00) Montevideo'),
    ('America/Sao_Paulo', '(GMT-03:00) São Paulo'),
    ('America/Mexico_City', '(GMT-06:00) Ciudad de México'),
    ('America/Bogota', '(GMT-05:00) Bogotá'),
]

onboarding_bp = Blueprint('onboarding', __name__)


# ── helpers ────────────────────────────────────────────────────────────
def _slugify(text: str) -> str:
    s = unicodedata.normalize('NFD', text.lower().strip())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'[\s]+', '-', s)
    s = re.sub(r'-+', '-', s)
    return s[:50].strip('-')


def _unique_slug(base: str, company_id=None) -> str:
    base = base or 'negocio'
    slug = base
    i = 2
    while True:
        q = Company.query.filter_by(slug=slug)
        if company_id:
            q = q.filter(Company.id != company_id)
        if not q.first():
            return slug
        slug = f'{base}-{i}'
        i += 1


def _current_company():
    if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
        return None
    return current_user.company


def _next_step_url(company):
    step = company.onboarding_step
    urls = {
        1: 'onboarding.business', 2: 'onboarding.staffing', 3: 'onboarding.services',
        4: 'onboarding.hours', 5: 'onboarding.publish',
    }
    return url_for(urls.get(step, 'onboarding.done'))


def _sync_employee_services(company):
    """Modelo simple de onboarding: los empleados creados acá atienden todos
    los servicios activos del negocio (se puede afinar después desde el panel)."""
    services = Service.query.filter_by(company_id=company.id, active=True).all()
    for employee in company.employees:
        employee.services = services


def _sync_employee_schedules(company, rows):
    """Aplica los mismos horarios semanales a todos los empleados del negocio."""
    for employee in company.employees:
        EmployeeSchedule.query.filter_by(employee_id=employee.id).delete()
        for weekday, start_t, end_t in rows:
            db.session.add(EmployeeSchedule(employee_id=employee.id, weekday=weekday, start_time=start_t, end_time=end_t))


def _save_logo(file_storage, company_id) -> str | None:
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in LOGO_EXTS:
        return None
    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > LOGO_MAX_BYTES:
        return None
    header = file_storage.read(12); file_storage.seek(0)
    is_png  = header.startswith(b'\x89PNG\r\n\x1a\n')
    is_jpeg = header.startswith(b'\xff\xd8\xff')
    if not (is_png or is_jpeg):
        return None
    mime_type = 'image/png' if is_png else 'image/jpeg'
    image = UploadedImage(company_id=company_id, mime_type=mime_type, data=file_storage.read())
    db.session.add(image)
    db.session.flush()
    return url_for('media.serve_image', image_id=image.id)


# ── Paso 1: crear cuenta ──────────────────────────────────────────────
@onboarding_bp.route('/registrar', methods=['GET', 'POST'])
@limiter.limit('8 per minute', error_message='Demasiados intentos. Esperá un minuto.')
def register():
    company = _current_company()
    if company:
        return redirect(_next_step_url(company))

    errors: dict = {}
    form: dict = {}

    if request.method == 'POST':
        form = request.form.to_dict()
        full_name = form.get('full_name', '').strip()
        email     = form.get('email', '').strip().lower()
        password  = form.get('password', '')
        accepted  = form.get('terms') == 'on'

        if not full_name:
            errors['full_name'] = 'Ingresá tu nombre completo.'
        if not email or '@' not in email:
            errors['email'] = 'Email inválido.'
        elif AdminUser.query.filter_by(email=email).first():
            errors['email'] = 'Ya existe una cuenta con ese email.'
        if len(password) < 8:
            errors['password'] = 'La contraseña debe tener al menos 8 caracteres.'
        if not accepted:
            errors['terms'] = 'Tenés que aceptar los términos para continuar.'

        if not errors:
            slug = _unique_slug('mi-negocio')
            company = Company(
                slug=slug, name='Mi negocio', email=email,
                plan_name='BASE', plan_status='TRIAL',
                trial_expires_at=datetime.utcnow() + timedelta(days=TRIAL_DAYS),
                active=True, brand_color='#3654f0', onboarding_step=1,
            )
            db.session.add(company)
            db.session.flush()

            db.session.add(CompanyConfig(
                company_id=company.id,
                require_customer_login=False,
                allow_booking_by_availability=True,
                allow_booking_by_employee=True,
                allow_customer_choose_employee=True,
                required_name=True,
                required_phone=True,
            ))

            admin = AdminUser(company_id=company.id, name=full_name, email=email, active=True)
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()

            login_user(admin)
            return redirect(url_for('onboarding.business'))

    return render_template('onboarding_register.html', errors=errors, form=form)


# ── Paso 2: información del negocio ────────────────────────────────────
@onboarding_bp.route('/registrar/negocio', methods=['GET', 'POST'])
def business():
    company = _current_company()
    if not company:
        return redirect(url_for('onboarding.register'))

    errors: dict = {}
    form = {
        'name': '' if company.name == 'Mi negocio' else company.name,
        'category': company.category or '',
        'phone': company.phone or '',
        'address': company.address or '',
        'timezone': company.timezone,
    }

    if request.method == 'POST':
        form = request.form.to_dict()
        name     = form.get('name', '').strip()
        category = form.get('category', '').strip()
        phone    = form.get('phone', '').strip()
        address  = form.get('address', '').strip()
        timezone = form.get('timezone', 'America/Argentina/Buenos_Aires').strip()

        if not name:
            errors['name'] = 'El nombre del negocio es obligatorio.'
        if not category:
            errors['category'] = 'Elegí una categoría.'

        if not errors:
            logo_url = _save_logo(request.files.get('logo'), company.id)
            if company.onboarding_step <= 2:
                base = _slugify(name)
                company.slug = _unique_slug(base, company_id=company.id)
            company.name = name
            company.category = category
            company.phone = phone or None
            company.address = address or None
            company.timezone = timezone
            if logo_url:
                company.logo_url = logo_url
            if company.onboarding_step < 2:
                company.onboarding_step = 2
            db.session.commit()
            return redirect(url_for('onboarding.staffing'))

    return render_template(
        'onboarding_business.html', errors=errors, form=form,
        categories=CATEGORIES, timezones=TIMEZONES, company=company, active_step=2,
    )


# ── Paso 3: ¿quién atiende? ─────────────────────────────────────────────
@onboarding_bp.route('/registrar/equipo', methods=['GET', 'POST'])
def staffing():
    company = _current_company()
    if not company:
        return redirect(url_for('onboarding.register'))
    if company.onboarding_step < 2:
        return redirect(url_for('onboarding.business'))

    errors: dict = {}

    if request.method == 'POST':
        mode = request.form.get('staffing_mode')
        if mode not in ('solo', 'team'):
            errors['staffing_mode'] = 'Elegí una opción para continuar.'

        if not errors:
            company.staffing_mode = mode
            if not company.employees:
                admin = AdminUser.query.filter_by(company_id=company.id).first()
                owner_name = admin.name if (mode == 'solo' and admin) else f'{company.name} · Equipo'
                db.session.add(Employee(company_id=company.id, name=owner_name, active=True, color='#3654f0'))
            if company.onboarding_step < 3:
                company.onboarding_step = 3
            db.session.commit()
            return redirect(url_for('onboarding.services'))

    return render_template('onboarding_staffing.html', errors=errors, company=company, active_step=3)


# ── Paso 4: servicios ───────────────────────────────────────────────────
@onboarding_bp.route('/registrar/servicios', methods=['GET', 'POST'])
def services():
    company = _current_company()
    if not company:
        return redirect(url_for('onboarding.register'))
    if company.onboarding_step < 3:
        return redirect(url_for('onboarding.staffing'))

    errors: dict = {}

    if request.method == 'POST':
        names     = request.form.getlist('service_name[]')
        durations = request.form.getlist('service_duration[]')
        prices    = request.form.getlist('service_price[]')

        rows = []
        for n, d, p in zip(names, durations, prices):
            n = n.strip()
            if not n:
                continue
            try:
                d_val = int(float(d))
                p_val = float(p) if p else 0.0
            except (TypeError, ValueError):
                errors['services'] = 'Revisá la duración y el precio de los servicios.'
                break
            if d_val < 5 or d_val > 480:
                errors['services'] = 'La duración debe estar entre 5 y 480 minutos.'
                break
            if p_val < 0:
                errors['services'] = 'El precio no puede ser negativo.'
                break
            rows.append((n, d_val, p_val))

        if not rows and not errors:
            errors['services'] = 'Agregá al menos un servicio.'

        if not errors:
            Service.query.filter_by(company_id=company.id).delete()
            db.session.flush()
            for n, d_val, p_val in rows:
                db.session.add(Service(
                    company_id=company.id, name=n,
                    duration_min=d_val, price=p_val, active=True,
                ))
            db.session.flush()
            _sync_employee_services(company)
            if company.onboarding_step < 4:
                company.onboarding_step = 4
            db.session.commit()
            return redirect(url_for('onboarding.hours'))

    services_list = Service.query.filter_by(company_id=company.id).order_by(Service.id).all()
    return render_template('onboarding_services.html', errors=errors, services=services_list, company=company, active_step=4)


# ── Paso 5: horarios ─────────────────────────────────────────────────────
@onboarding_bp.route('/registrar/horarios', methods=['GET', 'POST'])
def hours():
    company = _current_company()
    if not company:
        return redirect(url_for('onboarding.register'))
    if company.onboarding_step < 4:
        return redirect(url_for('onboarding.services'))

    errors: dict = {}

    if request.method == 'POST':
        rows = []
        for day_idx in range(7):
            if request.form.get(f'day_open_{day_idx}') != 'on':
                continue
            starts = request.form.getlist(f'start_{day_idx}[]')
            ends   = request.form.getlist(f'end_{day_idx}[]')
            for s, e in zip(starts, ends):
                if not s or not e:
                    continue
                try:
                    sh, sm = (int(x) for x in s.split(':'))
                    eh, em = (int(x) for x in e.split(':'))
                    rows.append((day_idx, time(sh, sm), time(eh, em)))
                except (ValueError, IndexError):
                    errors['hours'] = 'Revisá los horarios ingresados.'

        if not rows and not errors:
            errors['hours'] = 'Activá al menos un día de atención.'

        if not errors:
            CompanyHours.query.filter_by(company_id=company.id).delete()
            for day_idx, start_t, end_t in rows:
                db.session.add(CompanyHours(company_id=company.id, weekday=day_idx, start_time=start_t, end_time=end_t))
            db.session.flush()
            _sync_employee_schedules(company, rows)
            if company.onboarding_step < 5:
                company.onboarding_step = 5
            db.session.commit()
            return redirect(url_for('onboarding.publish'))

    existing: dict = {}
    for h in CompanyHours.query.filter_by(company_id=company.id).all():
        existing.setdefault(h.weekday, []).append(h)

    return render_template('onboarding_hours.html', errors=errors, weekdays=WEEKDAYS, existing=existing, company=company, active_step=5)


# ── Paso 6: checklist + publicar ─────────────────────────────────────────
@onboarding_bp.route('/registrar/publicar', methods=['GET', 'POST'])
def publish():
    company = _current_company()
    if not company:
        return redirect(url_for('onboarding.register'))
    if company.onboarding_step < 5:
        return redirect(url_for('onboarding.hours'))

    if request.method == 'POST':
        company.onboarding_step = 6
        db.session.commit()
        admin = AdminUser.query.filter_by(company_id=company.id).first()
        try:
            if admin:
                send_welcome_admin(admin, company)
        except Exception:
            pass
        return redirect(url_for('onboarding.done'))

    services_count  = Service.query.filter_by(company_id=company.id, active=True).count()
    employees_count = len(company.employees)
    hours_count     = CompanyHours.query.filter_by(company_id=company.id).count()

    return render_template(
        'onboarding_publish.html', company=company, active_step=6,
        services_count=services_count, employees_count=employees_count, hours_count=hours_count,
    )


# ── Paso 7: listo ────────────────────────────────────────────────────────
@onboarding_bp.route('/registrar/listo')
def done():
    company = _current_company()
    if not company:
        return redirect(url_for('onboarding.register'))
    admin = AdminUser.query.filter_by(company_id=company.id).first()
    first_name = (admin.name.split()[0] if admin and admin.name else '')
    return render_template('onboarding_done.html', company=company, first_name=first_name)
