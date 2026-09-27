"""Planes de Turnex, en un solo lugar.

Todo lo que distingue a los planes sale de acá: los límites y funciones que
controla el servidor, la tabla que muestra "Mi plan" y la lista de la landing.
Para mover una función de plan alcanza con cambiarla en este archivo.
"""
from __future__ import annotations

from datetime import datetime

PLAN_CODES = ('BASE', 'PRO', 'PREMIUM')

# ── Funciones que se habilitan por plan ─────────────────────────────────────
GOOGLE_CALENDAR = 'google_calendar'   # sincronización con Google Calendar
CANCEL_PENALTY = 'cancel_penalty'     # penalidad por cancelación tardía
APPOINTMENT_PAYMENTS = 'payments'     # registro de pagos de turnos (sección Pagos)
BRANDING = 'branding'                 # portada, color y redes en la página pública
EXPORT_CSV = 'export_csv'             # exportar la agenda a Excel (CSV)
AUDIT_LOG = 'audit_log'               # historial de cambios de cada turno
PRIORITY_SUPPORT = 'priority_support'

_PRO_FEATURES = {GOOGLE_CALENDAR, CANCEL_PENALTY, APPOINTMENT_PAYMENTS, BRANDING, EXPORT_CSV}

PLANS = {
    'BASE': {
        'name': 'BASE',
        'tagline': 'Para profesionales que trabajan solos.',
        'limits': {'professionals': 1, 'users': 1},
        'features': set(),
    },
    'PRO': {
        'name': 'PRO',
        'tagline': 'Para negocios con equipo.',
        'limits': {'professionals': 5, 'users': 3},
        'features': set(_PRO_FEATURES),
    },
    'PREMIUM': {
        'name': 'PREMIUM',
        'tagline': 'Sin límites y con soporte prioritario.',
        'limits': {'professionals': None, 'users': None},   # None = ilimitado
        'features': _PRO_FEATURES | {AUDIT_LOG, PRIORITY_SUPPORT},
    },
}

# Nombre corto de cada función para avisos ("… está incluido en PRO")
FEATURE_LABELS = {
    GOOGLE_CALENDAR: 'Google Calendar',
    CANCEL_PENALTY: 'La penalidad por cancelación tardía',
    APPOINTMENT_PAYMENTS: 'El registro de pagos de turnos',
    BRANDING: 'La portada, el color y las redes en tu página',
    EXPORT_CSV: 'Exportar la agenda a Excel',
    AUDIT_LOG: 'El historial de cambios de cada turno',
    PRIORITY_SUPPORT: 'El soporte prioritario',
}


def _limit_text(n, singular, plural):
    return f'{plural.capitalize()} ilimitados' if n is None else f'{n} {singular if n == 1 else plural}'


# Tabla comparativa: (texto, valor BASE, valor PRO, valor PREMIUM).
# True = incluido, False = no incluido, str = texto a mostrar.
COMPARISON = [
    ('Profesionales', '1', 'Hasta 5', 'Ilimitados'),
    ('Usuarios del panel', 'Solo el dueño', 'Dueño + 2', 'Ilimitados'),
    ('Página pública y reservas online', True, True, True),
    ('Agenda, clientes y bloqueos', True, True, True),
    ('Mails de confirmación y recordatorios', True, True, True),
    ('Google Calendar', False, True, True),
    ('Penalidad por cancelación tardía', False, True, True),
    ('Registro de pagos de turnos', False, True, True),
    ('Portada, color y redes en tu página', 'Solo logo', True, True),
    ('Exportar la agenda a Excel', False, True, True),
    ('Historial de cambios de cada turno', False, False, True),
    ('Soporte prioritario', False, False, True),
]


def plan_bullets(code: str) -> list[str]:
    """Lista corta de lo que incluye un plan (landing y "Mi plan")."""
    plan = PLANS[code]
    lim = plan['limits']
    base = [
        _limit_text(lim['professionals'], 'profesional', 'profesionales'),
        'Solo el dueño en el panel' if lim['users'] == 1 else
        ('Usuarios ilimitados en el panel' if lim['users'] is None else f'Dueño + {lim["users"] - 1} usuarios en el panel'),
    ]
    if code == 'BASE':
        return base + ['Página pública y reservas online', 'Agenda, clientes y bloqueos',
                       'Mails de confirmación y recordatorios']
    if code == 'PRO':
        return base + ['Todo lo del plan BASE', 'Google Calendar', 'Penalidad por cancelación tardía',
                       'Registro de pagos de turnos', 'Portada, color y redes en tu página',
                       'Exportar la agenda a Excel']
    return base + ['Todo lo del plan PRO', 'Historial de cambios de cada turno', 'Soporte prioritario']


# Tipos de pedido desde "Mi plan"
REQUEST_CHANGE = 'CHANGE'
REQUEST_CANCEL = 'CANCEL'


# ── Consultas sobre el plan de un negocio ───────────────────────────────────
def plan_code(company) -> str:
    code = ((company.plan_name if company else '') or '').strip().upper()
    return code if code in PLANS else 'BASE'


def plan_is_usable(company) -> bool:
    """El plan está vigente: activo, o en prueba sin vencer. Durante la prueba
    el negocio usa todas las funciones del plan que eligió."""
    status = ((company.plan_status or '') if company else '').upper()
    if status == 'ACTIVE':
        return True
    if status == 'TRIAL':
        exp = company.trial_expires_at
        return exp is None or exp > datetime.utcnow()
    return False


def plan_has(company, feature: str) -> bool:
    return feature in PLANS[plan_code(company)]['features']


def plan_limit(company, key: str):
    """Límite del plan (int) o None si es ilimitado."""
    return PLANS[plan_code(company)]['limits'][key]


def minimum_plan_for(feature: str) -> str:
    """El plan más barato que incluye una función (para los avisos)."""
    for code in PLAN_CODES:
        if feature in PLANS[code]['features']:
            return code
    return 'PREMIUM'
