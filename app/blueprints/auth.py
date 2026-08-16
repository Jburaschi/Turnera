from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user
from ..extensions import db, limiter
from ..models import Company, AdminUser, Customer, PlatformUser
import secrets
from datetime import datetime, timedelta
from ..services.email_service import send_password_reset

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/admin')
def admin_root():
    return redirect(url_for('auth.admin_login'))


@auth_bp.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute', error_message='Demasiados intentos. Esperá un minuto.')
def admin_login():
    if request.method == 'POST':
        slug = request.form.get('slug', '').strip().lower()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        company = Company.query.filter_by(slug=slug, active=True).first()
        admin = None
        if company:
            admin = AdminUser.query.filter_by(company_id=company.id, email=email, active=True).first()
        if not admin or not admin.check_password(password):
            flash('Credenciales invalidas.', 'danger')
            return render_template('admin_login.html')
        login_user(admin)
        return redirect(url_for('admin.dashboard', slug=company.slug))
    return render_template('admin_login.html')


@auth_bp.route('/platform/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute', error_message='Demasiados intentos. Esperá un minuto.')
def platform_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = PlatformUser.query.filter_by(email=email, active=True).first()
        if not user or not user.check_password(password):
            flash('Credenciales invalidas.', 'danger')
            return render_template('platform_login.html')
        login_user(user)
        return redirect(url_for('platform.dashboard'))
    return render_template('platform_login.html')


@auth_bp.route('/logout')
def logout():
    was_platform = current_user.is_authenticated and getattr(current_user, 'is_platform_admin', False)
    logout_user()
    if was_platform:
        return redirect(url_for('auth.platform_login'))
    return redirect(url_for('auth.admin_login'))


@auth_bp.route('/<slug>/customer/login', methods=['GET', 'POST'])
@limiter.limit('15 per minute', error_message='Demasiados intentos. Esperá un minuto.')
def customer_login(slug):
    company = Company.query.filter_by(slug=slug, active=True).first_or_404()
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        customer = Customer.query.filter_by(company_id=company.id, email=email).first()
        if not customer:
            flash('Credenciales invalidas.', 'danger')
            return render_template('customer_login.html', company=company)
        if getattr(customer, 'needs_password_setup', False):
            if len(password.strip()) < 6:
                flash('Es tu primer acceso. Elegí una contraseña de al menos 6 caracteres.', 'warning')
                return render_template('customer_login.html', company=company, preset_email=email)
            customer.set_password(password)
            customer.needs_password_setup = False
            db.session.commit()
            login_user(customer)
            next_url = request.args.get('next') or url_for('public.company_page', slug=slug)
            return redirect(next_url)
        if not customer.check_password(password):
            flash('Credenciales invalidas.', 'danger')
            return render_template('customer_login.html', company=company)
        login_user(customer)
        next_url = request.args.get('next') or url_for('public.company_page', slug=slug)
        return redirect(next_url)
    return render_template('customer_login.html', company=company)


@auth_bp.route('/<slug>/customer/register', methods=['GET', 'POST'])
@limiter.limit('5 per minute', error_message='Demasiados intentos. Esperá un minuto.')
def customer_register(slug):
    company = Company.query.filter_by(slug=slug, active=True).first_or_404()
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        if not full_name or not email:
            flash('Nombre y email son obligatorios.', 'danger')
            return render_template('customer_register.html', company=company)
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template('customer_register.html', company=company)
        if Customer.query.filter_by(company_id=company.id, email=email).first():
            flash('Ya existe una cuenta con ese email.', 'warning')
            return render_template('customer_register.html', company=company)
        customer = Customer(
            company=company,
            full_name=full_name,
            email=email,
            phone=request.form.get('phone', '').strip(),
            dni=request.form.get('dni', '').strip(),
        )
        customer.set_password(password)
        db.session.add(customer)
        db.session.commit()
        login_user(customer)
        return redirect(url_for('public.company_page', slug=slug))
    return render_template('customer_register.html', company=company)


# ── Recuperación de contraseña — Admin ────────────────────────────────────────

@auth_bp.route('/admin/forgot-password', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
def admin_forgot_password():
    if request.method == 'POST':
        slug  = request.form.get('slug', '').strip().lower()
        email = request.form.get('email', '').strip().lower()
        company = Company.query.filter_by(slug=slug, active=True).first()
        admin = None
        if company:
            admin = AdminUser.query.filter_by(
                company_id=company.id, email=email, active=True
            ).first()
        # Siempre mostrar el mismo mensaje para no filtrar info
        if admin:
            token = secrets.token_urlsafe(32)
            admin.reset_token = token
            admin.reset_token_expires = datetime.utcnow() + timedelta(hours=2)
            db.session.commit()
            reset_url = url_for(
                'auth.admin_reset_password', token=token, _external=True
            )
            send_password_reset(admin, reset_url)
        flash(
            'Si los datos son correctos, vas a recibir un email con el link para restablecer tu contraseña.',
            'info'
        )
        return redirect(url_for('auth.admin_forgot_password'))
    return render_template('admin_forgot_password.html')


@auth_bp.route('/admin/reset-password/<token>', methods=['GET', 'POST'])
def admin_reset_password(token):
    admin = AdminUser.query.filter_by(reset_token=token).first()
    if not admin or not admin.reset_token_expires or admin.reset_token_expires < datetime.utcnow():
        flash('El link es inválido o expiró. Solicitá uno nuevo.', 'danger')
        return redirect(url_for('auth.admin_forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')
        if len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres.', 'danger')
            return render_template('admin_reset_password.html', token=token)
        if password != confirm:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('admin_reset_password.html', token=token)
        admin.set_password(password)
        admin.reset_token = None
        admin.reset_token_expires = None
        db.session.commit()
        flash('Contraseña actualizada. Ya podés ingresar.', 'success')
        return redirect(url_for('auth.admin_login'))

    return render_template('admin_reset_password.html', token=token)


# ── Recuperación de contraseña — Cliente ─────────────────────────────────────

@auth_bp.route('/<slug>/forgot-password', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
def customer_forgot_password(slug):
    company = Company.query.filter_by(slug=slug, active=True).first_or_404()
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        customer = Customer.query.filter_by(
            company_id=company.id, email=email
        ).first()
        if customer:
            token = secrets.token_urlsafe(32)
            customer.reset_token = token
            customer.reset_token_expires = datetime.utcnow() + timedelta(hours=2)
            db.session.commit()
            reset_url = url_for(
                'auth.customer_reset_password',
                slug=slug, token=token, _external=True
            )
            send_password_reset(customer, reset_url)
        flash(
            'Si existe una cuenta con ese email, vas a recibir el link para restablecer tu contraseña.',
            'info'
        )
        return redirect(url_for('auth.customer_forgot_password', slug=slug))
    return render_template('customer_forgot_password.html', company=company)


@auth_bp.route('/<slug>/reset-password/<token>', methods=['GET', 'POST'])
def customer_reset_password(slug, token):
    company  = Company.query.filter_by(slug=slug, active=True).first_or_404()
    customer = Customer.query.filter_by(
        company_id=company.id, reset_token=token
    ).first()
    if not customer or not customer.reset_token_expires or customer.reset_token_expires < datetime.utcnow():
        flash('El link es inválido o expiró. Solicitá uno nuevo.', 'danger')
        return redirect(url_for('auth.customer_forgot_password', slug=slug))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm', '')
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template(
                'customer_reset_password.html', company=company, token=token
            )
        if password != confirm:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template(
                'customer_reset_password.html', company=company, token=token
            )
        customer.set_password(password)
        customer.reset_token = None
        customer.reset_token_expires = None
        customer.needs_password_setup = False
        db.session.commit()
        flash('Contraseña actualizada. Ya podés ingresar.', 'success')
        return redirect(url_for('auth.customer_login', slug=slug))

    return render_template(
        'customer_reset_password.html', company=company, token=token
    )
