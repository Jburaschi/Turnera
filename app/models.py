from __future__ import annotations
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import UniqueConstraint
from .extensions import db


employee_services = db.Table(
    'employee_services',
    db.Column('employee_id', db.Integer, db.ForeignKey('employee.id', ondelete='CASCADE'), primary_key=True),
    db.Column('service_id', db.Integer, db.ForeignKey('service.id', ondelete='CASCADE'), primary_key=True),
)

employee_schedule_services = db.Table(
    'employee_schedule_service',
    db.Column('schedule_id', db.Integer, db.ForeignKey('employee_schedule.id', ondelete='CASCADE'), primary_key=True),
    db.Column('service_id', db.Integer, db.ForeignKey('service.id', ondelete='CASCADE'), primary_key=True),
)


class PasswordMixin:
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class PlatformUser(UserMixin, PasswordMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def is_admin(self):
        return False

    @property
    def is_platform_admin(self):
        return True

    def get_id(self):
        return f'platform:{self.id}'


class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    logo_url = db.Column(db.String(500), nullable=True)
    cover_photo_url = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)
    address = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    timezone = db.Column(db.String(80), default='America/Argentina/Buenos_Aires', nullable=False)
    category = db.Column(db.String(80), nullable=True)
    instagram_url = db.Column(db.String(255), nullable=True)
    facebook_url  = db.Column(db.String(255), nullable=True)
    onboarding_step = db.Column(db.Integer, default=1, nullable=False)
    staffing_mode = db.Column(db.String(20), nullable=True)  # 'solo' | 'team'

    # 🔥 NUEVO
    cancelation_limit_hours = db.Column(db.Integer, default=24)
    cancelation_penalty_enabled = db.Column(db.Boolean, default=False)
    cancelation_penalty_amount = db.Column(db.Float, default=0)

    plan_name = db.Column(db.String(50), default='BASE', nullable=False)
    plan_status = db.Column(db.String(30), default='ACTIVE', nullable=False)
    trial_expires_at    = db.Column(db.DateTime, nullable=True)
    trial_warning_sent  = db.Column(db.Boolean, default=False, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    brand_color = db.Column(db.String(20), default='#198754', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    config = db.relationship('CompanyConfig', uselist=False, back_populates='company', cascade='all, delete-orphan')
    payments = db.relationship('SubscriptionPayment', back_populates='company', cascade='all, delete-orphan')
    admins = db.relationship('AdminUser', back_populates='company', cascade='all, delete-orphan')
    employees = db.relationship('Employee', back_populates='company', cascade='all, delete-orphan')
    services = db.relationship('Service', back_populates='company', cascade='all, delete-orphan')
    appointments = db.relationship('Appointment', back_populates='company', cascade='all, delete-orphan')
    customers = db.relationship('Customer', back_populates='company', cascade='all, delete-orphan')
    blocked_periods = db.relationship('BlockedPeriod', back_populates='company', cascade='all, delete-orphan')
    google_calendar = db.relationship('GoogleCalendarConnection', uselist=False, back_populates='company', cascade='all, delete-orphan')
    hours = db.relationship('CompanyHours', back_populates='company', cascade='all, delete-orphan', order_by='CompanyHours.weekday')


class CompanyConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), unique=True, nullable=False)
    require_customer_login = db.Column(db.Boolean, default=False, nullable=False)
    allow_booking_by_availability = db.Column(db.Boolean, default=True, nullable=False)
    allow_booking_by_employee = db.Column(db.Boolean, default=True, nullable=False)
    allow_customer_choose_employee = db.Column(db.Boolean, default=True, nullable=False)
    required_name = db.Column(db.Boolean, default=True, nullable=False)
    required_phone = db.Column(db.Boolean, default=True, nullable=False)
    required_email = db.Column(db.Boolean, default=False, nullable=False)
    required_dni = db.Column(db.Boolean, default=False, nullable=False)

    company = db.relationship('Company', back_populates='config')


class SubscriptionPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    paid_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(30), default='PAID', nullable=False)
    method = db.Column(db.String(50), default='Transferencia', nullable=False)
    notes = db.Column(db.String(255), nullable=True)

    company = db.relationship('Company', back_populates='payments')


class AdminUser(UserMixin, PasswordMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id          = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    email               = db.Column(db.String(120), nullable=False)
    name                = db.Column(db.String(120), nullable=False)
    active              = db.Column(db.Boolean, default=True, nullable=False)
    role                = db.Column(db.String(20), default='admin', nullable=False)
    # role: 'admin' (dueño, todo acceso) | 'staff' (agenda + clientes, sin config de empresa)
    reset_token         = db.Column(db.String(100), nullable=True, index=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)

    __table_args__ = (UniqueConstraint('company_id', 'email', name='uq_admin_company_email'),)

    company = db.relationship('Company', back_populates='admins')

    @property
    def is_admin(self):
        return True

    @property
    def is_platform_admin(self):
        return False

    def get_id(self):
        return f'admin:{self.id}'


class Customer(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    dni = db.Column(db.String(40), nullable=True)
    birth_date = db.Column(db.Date, nullable=True)
    tags = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    needs_password_setup = db.Column(db.Boolean, default=False, nullable=False)
    reset_token = db.Column(db.String(100), nullable=True, index=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint('company_id', 'email', name='uq_customer_company_email'),)

    company = db.relationship('Company', back_populates='customers')
    appointments = db.relationship('Appointment', back_populates='customer')

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return False

    @property
    def is_platform_admin(self):
        return False

    def get_id(self):
        return f'customer:{self.id}'


class Employee(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    name       = db.Column(db.String(120), nullable=False)
    active     = db.Column(db.Boolean, default=True, nullable=False)
    color      = db.Column(db.String(20), default='#0d6efd', nullable=False)
    photo_url  = db.Column(db.String(500), nullable=True)
    bio        = db.Column(db.String(300), nullable=True)

    company = db.relationship('Company', back_populates='employees')
    services = db.relationship('Service', secondary=employee_services, back_populates='employees')
    schedules = db.relationship('EmployeeSchedule', back_populates='employee', cascade='all, delete-orphan')
    appointments = db.relationship('Appointment', back_populates='employee')
    blocked_periods = db.relationship('BlockedPeriod', back_populates='employee', cascade='all, delete-orphan')


class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    short_description = db.Column(db.String(255), nullable=True)
    long_description = db.Column(db.Text, nullable=True)
    duration_min = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    color = db.Column(db.String(20), nullable=True)
    photo_url = db.Column(db.String(500), nullable=True)

    company = db.relationship('Company', back_populates='services')
    employees = db.relationship('Employee', secondary=employee_services, back_populates='services')
    appointments = db.relationship('Appointment', back_populates='service')


class EmployeeSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    weekday = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    employee = db.relationship('Employee', back_populates='schedules')
    limited_services = db.relationship(
        'Service',
        secondary=employee_schedule_services,
        lazy='select',
    )


class CompanyHours(db.Model):
    """Horarios de atención del negocio (a nivel empresa, no por empleado).
    Puede haber más de una franja por día (ej: mañana y tarde)."""
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    weekday = db.Column(db.Integer, nullable=False)  # 0=Lunes ... 6=Domingo
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    company = db.relationship('Company', back_populates='hours')


class UploadedImage(db.Model):
    """Logos y fotos de servicios/profesionales, guardados como bytes en la propia
    base de datos (en vez de en disco) para que sobrevivan a redeploys sin
    depender de almacenamiento externo. Se sirven vía /media/<id>."""
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False, index=True)
    mime_type = db.Column(db.String(50), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class SlotHold(db.Model):
    """Reserva temporal de un horario mientras el cliente completa sus datos.
    Evita que dos personas confirmen el mismo turno al mismo tiempo."""
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    start_dt = db.Column(db.DateTime, nullable=False, index=True)
    end_dt = db.Column(db.DateTime, nullable=False)
    session_key = db.Column(db.String(64), nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)


class BlockedPeriod(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=True)
    title = db.Column(db.String(120), nullable=False)
    block_type = db.Column(db.String(20), default='manual', nullable=False)  # vacation | training | manual | holiday
    start_dt = db.Column(db.DateTime, nullable=False, index=True)
    end_dt = db.Column(db.DateTime, nullable=False, index=True)
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    company = db.relationship('Company', back_populates='blocked_periods')
    employee = db.relationship('Employee', back_populates='blocked_periods')


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)

    guest_name = db.Column(db.String(120), nullable=True)
    guest_phone = db.Column(db.String(50), nullable=True)
    guest_email = db.Column(db.String(120), nullable=True)
    guest_dni = db.Column(db.String(40), nullable=True)

    start_dt = db.Column(db.DateTime, nullable=False, index=True)
    end_dt = db.Column(db.DateTime, nullable=False, index=True)

    status = db.Column(db.String(30), default='BOOKED', nullable=False, index=True)

    # 🔥 NUEVO
    canceled_at = db.Column(db.DateTime, nullable=True)
    rescheduled_from_id = db.Column(db.Integer, nullable=True)
    penalty_applied = db.Column(db.Boolean, default=False)
    google_event_id = db.Column(db.String(255), nullable=True, index=True)
    manage_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

    notes = db.Column(db.String(255), nullable=True)
    reminder_sent = db.Column(db.Boolean, default=False, nullable=False)

    # ── Pago del turno (lo que cobra el negocio a SU cliente) ──────────
    payment_status = db.Column(db.String(20), nullable=True)   # PAID | PENDING | None (sin registrar)
    payment_method = db.Column(db.String(40), nullable=True)
    paid_amount    = db.Column(db.Numeric(10, 2), nullable=True)
    payment_notes  = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    company  = db.relationship('Company',  back_populates='appointments')
    service  = db.relationship('Service',  back_populates='appointments')
    employee = db.relationship('Employee', back_populates='appointments')
    customer = db.relationship('Customer', back_populates='appointments')

    @property
    def customer_display_name(self) -> str:
        if self.customer:
            return self.customer.full_name
        return self.guest_name or 'Invitado'

    @property
    def customer_display_phone(self) -> str:
        if self.customer and self.customer.phone:
            return self.customer.phone
        return self.guest_phone or 'Sin teléfono'


class GoogleCalendarConnection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), unique=True, nullable=False)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_user.id'), nullable=True)

    enabled = db.Column(db.Boolean, default=True, nullable=False)
    calendar_id = db.Column(db.String(255), default='primary', nullable=False)

    refresh_token = db.Column(db.Text, nullable=True)
    access_token = db.Column(db.Text, nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True)
    scopes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = db.relationship('Company', back_populates='google_calendar')
    admin_user = db.relationship('AdminUser')


class AppointmentLog(db.Model):
    """Auditoría de cambios en turnos."""
    __tablename__ = 'appointment_log'

    id             = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False, index=True)
    action         = db.Column(db.String(30), nullable=False)
    # CREATED | STATUS_CHANGED | RESCHEDULED | REMINDER_SENT
    old_value      = db.Column(db.String(100), nullable=True)
    new_value      = db.Column(db.String(100), nullable=True)
    actor_type     = db.Column(db.String(20), nullable=True)
    # actor_type: 'admin' | 'staff' | 'customer' | 'guest' | 'system'
    actor_id       = db.Column(db.Integer, nullable=True)
    actor_name     = db.Column(db.String(120), nullable=True)
    notes          = db.Column(db.String(255), nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    appointment = db.relationship('Appointment',
        backref=db.backref('logs', lazy='dynamic',
                           order_by='AppointmentLog.created_at'))


WEEKDAY_LABELS = {
    0: 'Lunes',
    1: 'Martes',
    2: 'Miércoles',
    3: 'Jueves',
    4: 'Viernes',
    5: 'Sábado',
    6: 'Domingo',
}