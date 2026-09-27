"""Planes de Turnex, en un solo lugar (panel "Mi plan" y plataforma).
Los textos coinciden con la sección de planes de la landing."""

PLANS = {
    'BASE': {
        'name': 'BASE',
        'features': ['URL pública del negocio', 'Servicios, profesionales y horarios',
                     'Agenda online y alta manual', 'Panel de administración'],
    },
    'PRO': {
        'name': 'PRO',
        'features': ['Todo lo del plan BASE', 'Sincronización con Google Calendar',
                     'Recordatorios automáticos', 'Gestión rápida de agenda diaria'],
    },
    'PREMIUM': {
        'name': 'PREMIUM',
        'features': ['Todo lo del plan PRO', 'Soporte prioritario',
                     'Funcionalidades a medida', 'Onboarding personalizado'],
    },
}

PLAN_CODES = tuple(PLANS.keys())

# Tipos de pedido que el negocio puede hacer desde "Mi plan"
REQUEST_CHANGE = 'CHANGE'
REQUEST_CANCEL = 'CANCEL'
