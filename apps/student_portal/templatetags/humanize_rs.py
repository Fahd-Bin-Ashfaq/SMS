from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def rs(value):
    """Format an amount as rupees with thousands separators, e.g. Rs 3,000."""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    text = f"{amount:,.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    return f"Rs {text}"
