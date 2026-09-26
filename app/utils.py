from __future__ import annotations


def format_ars(amount) -> str:
    """Formato de pesos argentinos: 1500 -> '$ 1.500' · 1500.5 -> '$ 1.500,50'."""
    value = float(amount or 0)
    if value == int(value):
        txt = f'{int(value):,}'.replace(',', '.')
    else:
        txt = f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'$ {txt}'


DIAS_CORTOS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
MESES_CORTOS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


def dia_corto(dt) -> str:
    """Día de la semana abreviado en español (strftime('%a') depende del
    idioma del servidor y salía en inglés: 'Sun', 'Mon'...)."""
    return DIAS_CORTOS[dt.weekday()] if dt else ''


def mes_corto(dt) -> str:
    """Mes abreviado en español ('Ago', 'Dic'...)."""
    return MESES_CORTOS[dt.month - 1] if dt else ''
