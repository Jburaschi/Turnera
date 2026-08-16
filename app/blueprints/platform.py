from __future__ import annotations
from datetime import datetime
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user
from ..extensions import db
from ..models import Company, CompanyConfig, AdminUser, Appointment, SubscriptionPayment

platform_bp = Blueprint('platform', __name__, url_prefix='/platform')


def platform_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_platform_admin', False):
            return redirect(url_for('auth.platform_login'))
        return fn(*args, **kwargs)
    return wrapper


def normalize_slug(raw: str) -> str:
    return '-'.join(part for part in raw.strip().lower().replace('_', '-').split() if part)


@platform_bp.route('/')
@platform_required
def dashboard():
    companies = Company.query.order_by(Company.created_at.desc()).all()
    active_companies = [company for company in companies if company.active]
    paid_total = float(sum(payment.amount for payment in SubscriptionPayment.query.filter_by(status='PAID').all()) or 0)
    stats = {
        'companies': len(companies),
        'active_companies': len(active_companies),
        'appointments': Appointment.query.count(),
        'paid_total': paid_total,
    }
    return render_template('platform_dashboard.html', companies=companies, stats=stats,
                           now=datetime.utcnow())


@platform_bp.route('/companies', methods=['POST'])
@platform_required
def create_company():
    name = request.form.get('name', '').strip()
    slug = normalize_slug(request.form.get('slug', ''))
    admin_email = request.form.get('admin_email', '').strip().lower()
    admin_name = request.form.get('admin_name', '').strip() or 'Administrador'
    admin_password = request.form.get('admin_password', '').strip()

    if not name or not slug or not admin_email or not admin_password:
        flash('Nombre, slug, email admin y contraseña son obligatorios.', 'danger')
        return redirect(url_for('platform.dashboard'))
    if Company.query.filter_by(slug=slug).first():
        flash('Ese slug ya está en uso.', 'danger')
        return redirect(url_for('platform.dashboard'))

    company = Company(
        name=name,
        slug=slug,
        email=request.form.get('email', '').strip() or None,
        phone=request.form.get('phone', '').strip() or None,
        address=request.form.get('address', '').strip() or None,
        description=request.form.get('description', '').strip() or None,
        logo_url=request.form.get('logo_url', '').strip() or None,
        brand_color=request.form.get('brand_color', '#198754'),
        plan_name=request.form.get('plan_name', 'BASE'),
        plan_status=request.form.get('plan_status', 'ACTIVE'),
        active='active' in request.form,
        timezone='America/Argentina/Buenos_Aires',
    )
    config = CompanyConfig(company=company)
    admin = AdminUser(company=company, email=admin_email, name=admin_name, active=True)
    admin.set_password(admin_password)
    db.session.add_all([company, config, admin])
    db.session.commit()
    flash(f'Empresa {company.name} creada. URL pública: /{company.slug}', 'success')
    return redirect(url_for('platform.dashboard'))


@platform_bp.route('/companies/<int:company_id>/update', methods=['POST'])
@platform_required
def update_company(company_id):
    company = Company.query.get_or_404(company_id)
    proposed_slug = normalize_slug(request.form.get('slug', company.slug))
    existing = Company.query.filter(Company.slug == proposed_slug, Company.id != company.id).first()
    if existing:
        flash('No se pudo guardar: el slug ya pertenece a otra empresa.', 'danger')
        return redirect(url_for('platform.dashboard'))

    company.name = request.form.get('name', company.name).strip() or company.name
    company.slug = proposed_slug
    company.email = request.form.get('email', '').strip() or None
    company.phone = request.form.get('phone', '').strip() or None
    company.address = request.form.get('address', '').strip() or None
    company.description = request.form.get('description', '').strip() or None
    company.logo_url = request.form.get('logo_url', '').strip() or None
    company.brand_color = request.form.get('brand_color', company.brand_color)
    company.plan_name   = request.form.get('plan_name',   company.plan_name).strip()   or company.plan_name
    company.plan_status = request.form.get('plan_status', company.plan_status).strip() or company.plan_status
    company.active = 'active' in request.form

    # Gestión de trial
    if company.plan_status == 'ACTIVE':
        company.trial_expires_at   = None   # activado → limpiar trial
        company.trial_warning_sent = False
    elif company.plan_status == 'TRIAL':
        from datetime import datetime, timedelta
        trial_days_str = request.form.get('trial_days', '').strip()
        if trial_days_str.isdigit() and int(trial_days_str) > 0:
            company.trial_expires_at   = datetime.utcnow() + timedelta(days=int(trial_days_str))
            company.trial_warning_sent = False  # resetear para volver a avisar

    admin = company.admins[0] if company.admins else None
    if admin:
        admin.name = request.form.get('admin_name', admin.name).strip() or admin.name
        admin.email = request.form.get('admin_email', admin.email).strip().lower() or admin.email
        admin.active = 'admin_active' in request.form
        new_password = request.form.get('admin_password', '').strip()
        if new_password:
            admin.set_password(new_password)
    db.session.commit()
    flash('Empresa actualizada.', 'success')
    return redirect(url_for('platform.dashboard'))


@platform_bp.route('/companies/<int:company_id>/payments', methods=['POST'])
@platform_required
def add_payment(company_id):
    company = Company.query.get_or_404(company_id)
    payment = SubscriptionPayment(
        company=company,
        amount=request.form.get('amount', type=float) or 0,
        method=request.form.get('method', 'Transferencia').strip() or 'Transferencia',
        status=request.form.get('status', 'PAID').strip() or 'PAID',
        notes=request.form.get('notes', '').strip() or None,
        paid_at=datetime.utcnow(),
    )
    db.session.add(payment)
    db.session.commit()
    flash('Pago registrado para la empresa.', 'success')
    return redirect(url_for('platform.dashboard'))
