from __future__ import annotations


def format_ars(amount) -> str:
    """Formato de pesos argentinos: 1500 -> '$ 1.500' · 1500.5 -> '$ 1.500,50'."""
    value = float(amount or 0)
    if value == int(value):
        txt = f'{int(value):,}'.replace(',', '.')
    else:
        txt = f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'$ {txt}'
