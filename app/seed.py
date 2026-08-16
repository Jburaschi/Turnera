from datetime import time, datetime, timedelta
import os
import secrets
from .extensions import db
from .models import (
    PlatformUser,
    Company,
    CompanyConfig,
    SubscriptionPayment,
    AdminUser,
    Employee,
    EmployeeSchedule,
    Service,
    Appointment,
    Customer,
    BlockedPeriod,
)


def _ensure_platform_owner():
    email = os.environ.get('PLATFORM_ADMIN_EMAIL', '').strip().lower()
    password = os.environ.get('PLATFORM_ADMIN_PASSWORD', '').strip()

    if PlatformUser.query.first():
        return  # ya existe al menos un usuario de plataforma, no crear otro por defecto

    if not email:
        email = 'owner@turnex.com'

    if not password:
        # Sin variables de entorno configuradas: generamos una contraseña aleatoria
        # en vez de una fija/adivinable, y la mostramos UNA sola vez en el log de arranque.
        password = secrets.token_urlsafe(12)
        print('=' * 70)
        print('⚠  PLATFORM_ADMIN_PASSWORD no configurada — se generó una al azar:')
        print(f'   Email:      {email}')
        print(f'   Contraseña: {password}')
        print('   Configurá PLATFORM_ADMIN_EMAIL / PLATFORM_ADMIN_PASSWORD en tu .env')
        print('   antes de producción para fijar credenciales propias.')
        print('=' * 70)

    owner = PlatformUser(email=email, name='Owner Turnex', active=True)
    owner.set_password(password)
    db.session.add(owner)


def seed_if_empty():
    _ensure_platform_owner()
    if Company.query.first():
        db.session.commit()
        return

    company = Company(
        slug='pepito',
        name='Pepito Studio',
        logo_url='https://dummyimage.com/200x80/198754/ffffff&text=Pepito+Studio',
        description='Centro de estética con turnos online. Elegí servicio, profesional y horario en pocos pasos.',
        address='Av. Siempre Viva 123, Santos Lugares',
        phone='+54 11 5555-1234',
        email='hola@pepitostudio.com',
        brand_color='#198754',
        plan_name='PRO',
        plan_status='ACTIVE',
        active=True,
    )
    config = CompanyConfig(
        company=company,
        require_customer_login=False,
        allow_booking_by_availability=True,
        allow_booking_by_employee=True,
        allow_customer_choose_employee=True,
        required_name=True,
        required_phone=True,
        required_email=False,
        required_dni=False,
    )
    db.session.add_all([company, config])

    admin = AdminUser(company=company, email='admin@pepito.com', name='Admin Pepito', active=True)
    admin.set_password('admin123')
    db.session.add(admin)

    services = [
        Service(company=company, name='Uñas', short_description='Manicuría completa', long_description='Servicio completo de uñas con esmaltado y cuidado.', duration_min=120, price=18000, active=True),
        Service(company=company, name='Pelo', short_description='Corte y peinado', long_description='Corte, lavado y peinado. Duración promedio de una hora.', duration_min=60, price=15000, active=True),
        Service(company=company, name='Pestañas', short_description='Lifting de pestañas', long_description='Realce y lifting de pestañas con productos premium.', duration_min=90, price=22000, active=True),
    ]
    db.session.add_all(services)
    db.session.flush()

    maria = Employee(company=company, name='María', color='#0d6efd', active=True)
    carla = Employee(company=company, name='Carla', color='#dc3545', active=True)
    juan = Employee(company=company, name='Juan', color='#6f42c1', active=True)
    db.session.add_all([maria, carla, juan])
    db.session.flush()

    maria.services.extend([services[0], services[1]])
    carla.services.extend([services[0], services[2]])
    juan.services.extend([services[1]])

    schedules = []
    for employee in [maria, carla, juan]:
        for wd in range(0, 5):
            schedules.append(EmployeeSchedule(employee=employee, weekday=wd, start_time=time(9, 0), end_time=time(17, 0)))
        schedules.append(EmployeeSchedule(employee=employee, weekday=5, start_time=time(9, 0), end_time=time(13, 0)))
    db.session.add_all(schedules)

    customer = Customer(company=company, full_name='Lucía Demo', email='lucia@demo.com', phone='1133334444', dni='30111222')
    customer.set_password('cliente123')
    db.session.add(customer)
    db.session.flush()

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    sample = Appointment(
        company=company,
        service=services[0],
        employee=maria,
        guest_name='Cliente Demo',
        guest_phone='1133334444',
        start_dt=today + timedelta(days=1, hours=9),
        end_dt=today + timedelta(days=1, hours=11),
        status='BOOKED',
    )
    sample_customer = Appointment(
        company=company,
        service=services[1],
        employee=juan,
        customer=customer,
        start_dt=today + timedelta(days=1, hours=12),
        end_dt=today + timedelta(days=1, hours=13),
        status='BOOKED',
    )
    db.session.add_all([sample, sample_customer])
    db.session.add(SubscriptionPayment(company=company, amount=30000, status='PAID', method='Transferencia', notes='Plan mensual febrero'))
    db.session.add(SubscriptionPayment(company=company, amount=30000, status='PAID', method='Mercado Pago', notes='Plan mensual marzo'))
    db.session.add(BlockedPeriod(company=company, employee=carla, title='Capacitación', start_dt=today + timedelta(days=2, hours=10), end_dt=today + timedelta(days=2, hours=13), notes='No tomar turnos'))
    db.session.commit()
