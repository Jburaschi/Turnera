from __future__ import annotations
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, current_app, render_template, request, redirect, session, url_for, flash, abort
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func, or_
from ..extensions import db
from ..models import (Company, CompanyConfig, AdminUser, Appointment, Customer, Employee,
                      PlanRequest, PlatformAuditLog, PlatformUser, Service, SubscriptionPayment)
from ..services.platform_audit import changed_fields, log_platform
from ..plans import PLAN_CODES, PLAN_STATUSES, TRIAL_DAYS
from ..timeutils import parse_iso_date, today_ar
from ..utils import apply_address, clean_public_url, is_reserved_slug, read_address_form, slugify

platform_bp = Blueprint('platform', __name__, url_prefix='/platform')

# Clave de sesión que indica que un usuario de plataforma entró al panel de
# un negocio con "Entrar como". Guarda el id del usuario de plataforma.
IMPERSONATOR_KEY = 'impersonator_platform_id'
MIN_PASSWORD = 8

COMPANY_FILTERS = {
    'all': 'Todas',
    'trial': 'En prueba',
    'expiring': 'Prueba por vencer',
    'expired': 'Prueba vencida',
    'active': 'Plan activo',
    'suspended': 'Suspendidas',
    'hidden': 'Ocultas',
}


def platform_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_platform_admin', False):
            return redirect(url_for('auth.platform_login'))
        return fn(*args, **kwargs)
    return wrapper


def normalize_slug(raw: str) -> str:
    return slugify(raw)


def _slug_error(slug: str, company_id=None):
    """Devuelve un texto de error si el link no se puede usar, o None."""
    if not slug:
        return 'El link (slug) no puede quedar vacío. Usá letras, números y guiones.'
    if is_reserved_slug(slug):
        return f'El link "/{slug}" está reservado por el sistema. Elegí otro.'
    q = Company.query.filter(Company.slug == slug)
    if company_id:
        q = q.filter(Company.id != company_id)
    if q.first():
        return f'El link "/{slug}" ya lo usa otra empresa.'
    return None


def company_owner(company):
    """El dueño de la cuenta: el primer usuario con rol admin (activo si hay)."""
    admins = sorted(company.admins, key=lambda a: a.id)
    owners = [a for a in admins if a.role == 'admin']
    for a in owners:
        if a.active:
            return a
    return owners[0] if owners else (admins[0] if admins else None)


def _trial_state(company, now):
    if (company.plan_status or '').upper() != 'TRIAL':
        return None
    if not company.trial_expires_at:
        return 'trial'
    days = (company.trial_expires_at.date() - now.date()).days
    if days < 0:
        return 'expired'
    if days <= 7:
        return 'expiring'
    return 'trial'


def _matches_filter(company, flt, now):
    status = (company.plan_status or '').upper()
    if flt == 'trial':
        return status == 'TRIAL'
    if flt == 'expiring':
        return _trial_state(company, now) == 'expiring'
    if flt == 'expired':
        return _trial_state(company, now) == 'expired'
    if flt == 'active':
        return status == 'ACTIVE'
    if flt == 'suspended':
        return status == 'SUSPENDED'
    if flt == 'hidden':
        return not company.active
    return True


def _usage_by_company():
    """Uso de cada empresa: turnos del mes, profesionales activos, clientes y usuarios."""
    first = today_ar().replace(day=1)
    nxt = (first.replace(year=first.year + 1, month=1) if first.month == 12
           else first.replace(month=first.month + 1))
    month_start = datetime.combine(first, datetime.min.time())
    month_end = datetime.combine(nxt, datetime.min.time())

    def grouped(query):
        return {cid: n for cid, n in query.all()}

    return {
        'appointments_month': grouped(
            db.session.query(Appointment.company_id, func.count(Appointment.id))
            .filter(Appointment.start_dt >= month_start, Appointment.start_dt < month_end,
                    Appointment.status != 'CANCELED')
            .group_by(Appointment.company_id)),
        'professionals': grouped(
            db.session.query(Employee.company_id, func.count(Employee.id))
            .filter(Employee.active.is_(True)).group_by(Employee.company_id)),
        'customers': grouped(
            db.session.query(Customer.company_id, func.count(Customer.id)).group_by(Customer.company_id)),
        'users': grouped(
            db.session.query(AdminUser.company_id, func.count(AdminUser.id))
            .filter(AdminUser.active.is_(True)).group_by(AdminUser.company_id)),
    }


@platform_bp.route('/')
@platform_required
def dashboard():
    now = datetime.utcnow()
    companies = Company.query.order_by(Company.created_at.desc()).all()
    active_companies = [company for company in companies if company.active]
    paid_total = float(sum(payment.amount for payment in SubscriptionPayment.query.filter_by(status='PAID').all()) or 0)
    stats = {
        'companies': len(companies),
        'active_companies': len(active_companies),
        'appointments': Appointment.query.count(),
        'paid_total': paid_total,
    }
    filter_counts = {key: sum(1 for c in companies if _matches_filter(c, key, now)) for key in COMPANY_FILTERS}

    q = (request.args.get('q') or '').strip().lower()
    flt = request.args.get('f', 'all')
    if flt not in COMPANY_FILTERS:
        flt = 'all'
    shown = [c for c in companies if _matches_filter(c, flt, now)]
    if q:
        def hit(c):
            owner = company_owner(c)
            texts = [c.name, c.slug, c.email or '', c.phone or '', owner.email if owner else '']
            return any(q in (t or '').lower() for t in texts)
        shown = [c for c in shown if hit(c)]

    plan_requests = PlanRequest.query.filter_by(status='PENDING').order_by(PlanRequest.created_at.asc()).all()
    return render_template('platform_dashboard.html', companies=shown, all_count=len(companies),
                           stats=stats, now=now, plan_requests=plan_requests,
                           usage=_usage_by_company(), q=q, flt=flt, filters=COMPANY_FILTERS,
                           filter_counts=filter_counts, plan_codes=PLAN_CODES,
                           plan_statuses=PLAN_STATUSES, trial_days=TRIAL_DAYS,
                           company_owner=company_owner, trial_state=_trial_state)


@platform_bp.route('/companies', methods=['POST'])
@platform_required
def create_company():
    name = request.form.get('name', '').strip()
    slug = normalize_slug(request.form.get('slug', '') or name)
    admin_email = request.form.get('admin_email', '').strip().lower()
    admin_name = request.form.get('admin_name', '').strip() or 'Administrador'
    admin_password = request.form.get('admin_password', '').strip()

    if not name or not admin_email or not admin_password:
        flash('Nombre, email del dueño y contraseña son obligatorios.', 'danger')
        return redirect(url_for('platform.dashboard'))
    err = _slug_error(slug)
    if err:
        flash(err, 'danger')
        return redirect(url_for('platform.dashboard'))
    if len(admin_password) < MIN_PASSWORD:
        flash(f'La contraseña del dueño debe tener al menos {MIN_PASSWORD} caracteres.', 'danger')
        return redirect(url_for('platform.dashboard'))
    if AdminUser.query.filter_by(email=admin_email).first():
        flash('Ya existe un usuario de negocio con ese email.', 'danger')
        return redirect(url_for('platform.dashboard'))

    plan_name = request.form.get('plan_name', 'BASE')
    plan_status = request.form.get('plan_status', 'TRIAL')
    if plan_name not in PLAN_CODES or plan_status not in PLAN_STATUSES:
        flash('Plan o estado inválido.', 'danger')
        return redirect(url_for('platform.dashboard'))

    logo_url, logo_err = clean_public_url(request.form.get('logo_url'), allow_local_media=True)
    if logo_err:
        flash(f'Logo: {logo_err}', 'danger')
        return redirect(url_for('platform.dashboard'))

    company = Company(
        name=name,
        slug=slug,
        email=request.form.get('email', '').strip() or None,
        phone=request.form.get('phone', '').strip() or None,
        description=request.form.get('description', '').strip() or None,
        logo_url=logo_url,
        brand_color=request.form.get('brand_color', '#198754'),
        plan_name=plan_name,
        plan_status=plan_status,
        trial_expires_at=(datetime.utcnow() + timedelta(days=TRIAL_DAYS)) if plan_status == 'TRIAL' else None,
        active='active' in request.form,
        timezone='America/Argentina/Buenos_Aires',
    )
    addr_values, addr_error = read_address_form(request.form)
    apply_address(company, addr_values)
    if addr_error:
        flash(addr_error, 'warning')
    config = CompanyConfig(company=company)
    admin = AdminUser(company=company, email=admin_email, name=admin_name, active=True, role='admin')
    admin.set_password(admin_password)
    db.session.add_all([company, config, admin])
    db.session.commit()
    log_platform('Creó una empresa', f'{company.name} (/{company.slug}) · plan {plan_name} {PLAN_STATUSES[plan_status]} · dueño {admin_email}', company=company)
    flash(f'Empresa {company.name} creada. URL pública: /{company.slug}', 'success')
    return redirect(url_for('platform.dashboard'))


@platform_bp.route('/companies/<int:company_id>/update', methods=['POST'])
@platform_required
def update_company(company_id):
    company = Company.query.get_or_404(company_id)
    back = redirect(request.referrer or url_for('platform.dashboard'))
    proposed_slug = normalize_slug(request.form.get('slug', company.slug))
    if proposed_slug != company.slug:
        err = _slug_error(proposed_slug, company_id=company.id)
        if err:
            flash(f'No se pudo guardar: {err}', 'danger')
            return back

    plan_name = (request.form.get('plan_name') or company.plan_name).strip().upper()
    plan_status = (request.form.get('plan_status') or company.plan_status).strip().upper()
    if plan_name not in PLAN_CODES or plan_status not in PLAN_STATUSES:
        flash('No se pudo guardar: plan o estado inválido.', 'danger')
        return back

    logo_url, logo_err = clean_public_url(request.form.get('logo_url'), allow_local_media=True)
    if logo_err:
        flash(f'Logo: {logo_err}', 'danger')
        return back

    owner = company_owner(company)
    new_email = (request.form.get('admin_email') or '').strip().lower()
    if owner and new_email and new_email != owner.email:
        if AdminUser.query.filter(AdminUser.email == new_email, AdminUser.id != owner.id).first():
            flash('No se pudo guardar: ese email ya lo usa otro usuario de negocio.', 'danger')
            return back
    new_password = (request.form.get('admin_password') or '').strip()
    if new_password and len(new_password) < MIN_PASSWORD:
        flash(f'No se pudo guardar: la contraseña debe tener al menos {MIN_PASSWORD} caracteres.', 'danger')
        return back

    before = {'plan': (company.plan_name, company.plan_status), 'active': company.active, 'slug': company.slug}
    company.name = request.form.get('name', company.name).strip() or company.name
    company.slug = proposed_slug
    company.email = request.form.get('email', '').strip() or None
    company.phone = request.form.get('phone', '').strip() or None
    if 'address' in request.form:
        addr_values, addr_error = read_address_form(request.form)
        apply_address(company, addr_values)
        if addr_error:
            flash(addr_error, 'warning')
    company.description = request.form.get('description', '').strip() or None
    if 'logo_url' in request.form:
        company.logo_url = logo_url
    company.brand_color = request.form.get('brand_color', company.brand_color)
    company.plan_name = plan_name
    company.plan_status = plan_status
    company.active = 'active' in request.form

    # Gestión de la prueba
    if company.plan_status == 'ACTIVE':
        company.trial_expires_at   = None   # activado → limpiar prueba
        company.trial_warning_sent = False
    elif company.plan_status == 'TRIAL':
        trial_days_str = request.form.get('trial_days', '').strip()
        if trial_days_str.isdigit() and int(trial_days_str) > 0:
            company.trial_expires_at   = datetime.utcnow() + timedelta(days=min(int(trial_days_str), 365))
            company.trial_warning_sent = False  # resetear para volver a avisar
        elif not company.trial_expires_at:
            company.trial_expires_at = datetime.utcnow() + timedelta(days=TRIAL_DAYS)

    if owner:
        owner.name = request.form.get('admin_name', owner.name).strip() or owner.name
        owner.email = new_email or owner.email
        owner.active = 'admin_active' in request.form
        if new_password:
            owner.set_password(new_password)
    changes = []
    if before['plan'] != (company.plan_name, company.plan_status):
        changes.append(f"plan {before['plan'][0]} {before['plan'][1]} → {company.plan_name} {company.plan_status}")
    if before['active'] != company.active:
        changes.append('visible' if company.active else 'oculta')
    if before['slug'] != company.slug:
        changes.append(f"link /{before['slug']} → /{company.slug}")
    if new_password:
        changes.append('cambió la contraseña del dueño')
    db.session.commit()
    log_platform('Editó una empresa', '; '.join(changes) or f'Campos: {changed_fields(request.form)}', company=company)
    flash('Empresa actualizada.', 'success')
    return back


# ── Entrar como la empresa (soporte) ───────────────────────────────────────
@platform_bp.route('/companies/<int:company_id>/enter', methods=['POST'])
@platform_required
def enter_company(company_id):
    company = Company.query.get_or_404(company_id)
    owner = company_owner(company)
    if not owner or not owner.active:
        flash('La empresa no tiene un dueño activo. Activalo desde "Editar" para poder entrar.', 'danger')
        return redirect(url_for('platform.dashboard'))
    platform_user_id = current_user.id
    current_app.logger.info('Plataforma: %s entra como %s (%s)', current_user.email, owner.email, company.slug)
    logout_user()
    login_user(owner)
    session[IMPERSONATOR_KEY] = platform_user_id
    log_platform('Entró al panel del negocio', f'Como {owner.email}', company=company)
    flash(f'Estás viendo el panel de {company.name} como su dueño. Todo lo que cambies se guarda de verdad.', 'info')
    section = request.form.get('section')
    if section in ('agenda', 'customers'):
        day = parse_iso_date(request.form.get('day'))
        args = {'section': section}
        if day:
            args['day'] = day.isoformat()
        if section == 'customers' and request.form.get('q'):
            args['q'] = request.form.get('q')[:120]
        return redirect(url_for('admin.dashboard', slug=company.slug, **args))
    return redirect(url_for('admin.dashboard', slug=company.slug))


@platform_bp.route('/volver', methods=['POST'])
def leave_company():
    """Sale del panel del negocio y vuelve a la sesión de plataforma."""
    platform_user_id = session.get(IMPERSONATOR_KEY)
    if platform_user_id:
        log_platform('Salió del panel del negocio', '', company=getattr(current_user, 'company', None))
    session.pop(IMPERSONATOR_KEY, None)
    slug = current_user.company.slug if (current_user.is_authenticated and getattr(current_user, 'is_admin', False)) else None
    logout_user()
    user = db.session.get(PlatformUser, platform_user_id) if platform_user_id else None
    if not user or not user.active:
        return redirect(url_for('auth.platform_login'))
    login_user(user)
    if slug:
        return redirect(url_for('platform.dashboard', q=slug))
    return redirect(url_for('platform.dashboard'))


@platform_bp.route('/plan-requests/<int:request_id>/resolve', methods=['POST'])
@platform_required
def resolve_plan_request(request_id):
    """Marca un pedido de "Mi plan" como resuelto. El cambio en sí (plan,
    estado, desactivar la empresa) se hace editando la empresa."""
    req = PlanRequest.query.get_or_404(request_id)
    req.status = 'DONE'
    req.resolved_at = datetime.utcnow()
    db.session.commit()
    log_platform('Resolvió un pedido de plan', f"{'Cambio a ' + (req.requested_plan or '') if req.kind == 'CHANGE' else 'Baja'}", company_id=req.company_id)
    flash(f'Pedido de {req.company.name} marcado como resuelto.', 'success')
    return redirect(url_for('platform.dashboard'))


@platform_bp.route('/companies/<int:company_id>/payments', methods=['POST'])
@platform_required
def add_payment(company_id):
    company = Company.query.get_or_404(company_id)
    amount = request.form.get('amount', type=float) or 0
    if amount <= 0:
        flash('Ingresá un monto mayor a cero.', 'danger')
        return redirect(request.referrer or url_for('platform.dashboard'))
    status = request.form.get('status', 'PAID').strip().upper()
    payment = SubscriptionPayment(
        company=company,
        amount=amount,
        method=request.form.get('method', 'Transferencia').strip() or 'Transferencia',
        status=status if status in ('PAID', 'PENDING') else 'PAID',
        notes=request.form.get('notes', '').strip() or None,
        paid_at=datetime.utcnow(),
    )
    db.session.add(payment)
    db.session.commit()
    log_platform('Registró un pago', f'$ {amount:,.0f} · {payment.method} · {payment.status}'.replace(',', '.'), company=company)
    flash(f'Pago registrado para {company.name}.', 'success')
    return redirect(request.referrer or url_for('platform.dashboard'))


# ── Mi cuenta y usuarios de plataforma ─────────────────────────────────────
@platform_bp.route('/cuenta')
@platform_required
def account():
    users = PlatformUser.query.order_by(PlatformUser.created_at.asc()).all()
    return render_template('platform_account.html', users=users, min_password=MIN_PASSWORD)


@platform_bp.route('/cuenta/password', methods=['POST'])
@platform_required
def change_password():
    current = request.form.get('current_password', '')
    new = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    if not current_user.check_password(current):
        flash('La contraseña actual no es correcta.', 'danger')
    elif len(new) < MIN_PASSWORD:
        flash(f'La nueva contraseña debe tener al menos {MIN_PASSWORD} caracteres.', 'danger')
    elif new != confirm:
        flash('Las contraseñas nuevas no coinciden.', 'danger')
    else:
        user = db.session.get(PlatformUser, current_user.id)
        user.set_password(new)
        db.session.commit()
        log_platform('Cambió su contraseña')
        # La sesión depende de la contraseña: volvemos a iniciarla para no cerrarla.
        login_user(user)
        flash('Contraseña actualizada.', 'success')
    return redirect(url_for('platform.account'))


@platform_bp.route('/cuenta/usuarios', methods=['POST'])
@platform_required
def create_platform_user():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    if not name or not email or '@' not in email:
        flash('Completá nombre y un email válido.', 'danger')
    elif len(password) < MIN_PASSWORD:
        flash(f'La contraseña debe tener al menos {MIN_PASSWORD} caracteres.', 'danger')
    elif PlatformUser.query.filter_by(email=email).first():
        flash('Ya existe un usuario de plataforma con ese email.', 'danger')
    else:
        user = PlatformUser(name=name, email=email, active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        log_platform('Creó un usuario de plataforma', email)
        flash(f'Usuario {email} creado. Ya puede entrar en /platform/login.', 'success')
    return redirect(url_for('platform.account'))


@platform_bp.route('/cuenta/usuarios/<int:user_id>/toggle', methods=['POST'])
@platform_required
def toggle_platform_user(user_id):
    user = db.session.get(PlatformUser, user_id) or abort(404)
    if user.id == current_user.id:
        flash('No podés desactivar tu propio usuario.', 'danger')
    else:
        user.active = not user.active
        db.session.commit()
        log_platform('Activó un usuario de plataforma' if user.active else 'Desactivó un usuario de plataforma', user.email)
        flash(f'Usuario {user.email} {"activado" if user.active else "desactivado"}.', 'success')
    return redirect(url_for('platform.account'))


# ── Clientes de todas las empresas ─────────────────────────────────────────
PAGE = 50


def _digits_col(col):
    """El campo sin espacios, guiones, puntos, paréntesis ni '+', para buscar teléfonos y DNI."""
    for ch in (' ', '-', '.', '(', ')', '+'):
        col = func.replace(col, ch, '')
    return col


def _pages(total):
    return max(1, (total + PAGE - 1) // PAGE)


@platform_bp.route('/clientes')
@platform_required
def customers():
    q = (request.args.get('q') or '').strip()
    company_id = request.args.get('company', type=int)
    page = max(1, request.args.get('page', 1, type=int))
    query = Customer.query.join(Company, Customer.company_id == Company.id)
    if company_id:
        query = query.filter(Customer.company_id == company_id)
    if q:
        like = f'%{q.lower()}%'
        digits = ''.join(ch for ch in q if ch.isdigit())
        conds = [func.lower(Customer.full_name).like(like), func.lower(Customer.email).like(like),
                 func.lower(Company.name).like(like)]
        if digits:
            conds += [_digits_col(Customer.phone).like(f'%{digits}%'), _digits_col(Customer.dni).like(f'%{digits}%')]
        query = query.filter(or_(*conds))
    total = query.count()
    rows = query.order_by(Customer.created_at.desc()).offset((page - 1) * PAGE).limit(PAGE).all()
    ids = [c.id for c in rows]
    stats = {}
    if ids:
        for cid, n, last in (db.session.query(Appointment.customer_id, func.count(Appointment.id), func.max(Appointment.start_dt))
                             .filter(Appointment.customer_id.in_(ids)).group_by(Appointment.customer_id).all()):
            stats[cid] = (n, last)
    companies = Company.query.order_by(Company.name).all()
    return render_template('platform_customers.html', customers=rows, stats=stats, total=total, q=q,
                           company_id=company_id, companies=companies, page=page, pages=_pages(total),
                           total_all=Customer.query.count())


@platform_bp.route('/clientes/<int:customer_id>', methods=['GET', 'POST'])
@platform_required
def customer_detail(customer_id):
    customer = db.session.get(Customer, customer_id) or abort(404)
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        name = (request.form.get('full_name') or '').strip()
        new_pw = (request.form.get('password') or '').strip()
        if not name or not email or '@' not in email:
            flash('Completá nombre y un email válido.', 'danger')
        elif Customer.query.filter(Customer.company_id == customer.company_id, Customer.email == email, Customer.id != customer.id).first():
            flash('Ese negocio ya tiene otro cliente con ese email.', 'danger')
        elif new_pw and len(new_pw) < 6:
            flash('La contraseña del cliente debe tener al menos 6 caracteres.', 'danger')
        else:
            before = (customer.full_name, customer.email, customer.phone, customer.dni)
            customer.full_name = name
            customer.email = email
            customer.phone = (request.form.get('phone') or '').strip() or None
            customer.dni = (request.form.get('dni') or '').strip() or None
            customer.tags = (request.form.get('tags') or '').strip() or None
            customer.notes = (request.form.get('notes') or '').strip() or None
            if new_pw:
                customer.set_password(new_pw)
                customer.needs_password_setup = False
            db.session.commit()
            after = (customer.full_name, customer.email, customer.phone, customer.dni)
            labels = ('nombre', 'email', 'teléfono', 'DNI')
            diff = [f'{l}: {b or "—"} → {a or "—"}' for l, b, a in zip(labels, before, after) if b != a]
            if new_pw:
                diff.append('cambió la contraseña')
            log_platform('Editó un cliente', f'{customer.full_name} · ' + ('; '.join(diff) or 'sin cambios en los datos principales'), company_id=customer.company_id)
            flash('Cliente actualizado.', 'success')
            return redirect(url_for('platform.customer_detail', customer_id=customer.id))
    appts = (Appointment.query.filter_by(customer_id=customer.id)
             .order_by(Appointment.start_dt.desc()).limit(30).all())
    return render_template('platform_customer_detail.html', customer=customer, appts=appts,
                           status_labels=STATUS_LABELS)


# ── Turnos de todas las empresas ───────────────────────────────────────────
STATUS_LABELS = {'BOOKED': 'Reservado', 'DONE': 'Atendido', 'CANCELED': 'Cancelado', 'NO_SHOW': 'No vino'}
RANGES = {'hoy': (0, 0), '7': (0, 6), '30': (0, 29), 'pasados': (-30, -1)}


@platform_bp.route('/turnos')
@platform_required
def appointments():
    today = today_ar()
    rng = request.args.get('rango', '7')
    if rng in RANGES:
        d1, d2 = today + timedelta(days=RANGES[rng][0]), today + timedelta(days=RANGES[rng][1])
    else:
        rng = 'custom'
        d1 = parse_iso_date(request.args.get('desde'), today)
        d2 = parse_iso_date(request.args.get('hasta'), d1 + timedelta(days=6))
        if d2 < d1:
            d1, d2 = d2, d1
        d2 = min(d2, d1 + timedelta(days=366))
    company_id = request.args.get('company', type=int)
    status = (request.args.get('estado') or '').upper()
    q = (request.args.get('q') or '').strip()
    page = max(1, request.args.get('page', 1, type=int))
    query = (Appointment.query.join(Company, Appointment.company_id == Company.id)
             .outerjoin(Customer, Appointment.customer_id == Customer.id)
             .filter(Appointment.start_dt >= datetime.combine(d1, datetime.min.time()),
                     Appointment.start_dt < datetime.combine(d2 + timedelta(days=1), datetime.min.time())))
    if company_id:
        query = query.filter(Appointment.company_id == company_id)
    if status in STATUS_LABELS:
        query = query.filter(Appointment.status == status)
    if q:
        like = f'%{q.lower()}%'
        digits = ''.join(ch for ch in q if ch.isdigit())
        conds = [func.lower(Appointment.guest_name).like(like), func.lower(Appointment.guest_email).like(like),
                 func.lower(Customer.full_name).like(like), func.lower(Customer.email).like(like)]
        if digits:
            conds += [_digits_col(Appointment.guest_phone).like(f'%{digits}%'), _digits_col(Customer.phone).like(f'%{digits}%')]
        query = query.filter(or_(*conds))
    total = query.count()
    by_status = dict(query.with_entities(Appointment.status, func.count(Appointment.id)).group_by(Appointment.status).all())
    order = Appointment.start_dt.desc() if rng == 'pasados' else Appointment.start_dt.asc()
    rows = query.order_by(order).offset((page - 1) * PAGE).limit(PAGE).all()
    return render_template('platform_appointments.html', appts=rows, total=total, by_status=by_status,
                           rng=rng, d1=d1, d2=d2, company_id=company_id, status=status, q=q,
                           companies=Company.query.order_by(Company.name).all(), page=page,
                           pages=_pages(total), status_labels=STATUS_LABELS)


# ── Actividad (registro de acciones de plataforma) ─────────────────────────
@platform_bp.route('/actividad')
@platform_required
def activity():
    company_id = request.args.get('company', type=int)
    user_id = request.args.get('usuario', type=int)
    page = max(1, request.args.get('page', 1, type=int))
    query = PlatformAuditLog.query
    if company_id:
        query = query.filter(PlatformAuditLog.company_id == company_id)
    if user_id:
        query = query.filter(PlatformAuditLog.platform_user_id == user_id)
    total = query.count()
    rows = query.order_by(PlatformAuditLog.created_at.desc()).offset((page - 1) * PAGE).limit(PAGE).all()
    return render_template('platform_activity.html', rows=rows, total=total, page=page, pages=_pages(total),
                           company_id=company_id, user_id=user_id,
                           companies=Company.query.order_by(Company.name).all(),
                           users=PlatformUser.query.order_by(PlatformUser.name).all())
