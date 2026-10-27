from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

ONES = (
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
    "Eighteen", "Nineteen",
)
TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")
# Pakistani numbering: crore (10^7), lakh (10^5), thousand, hundred.
SCALES = ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand"), (100, "Hundred"))


def _words(number):
    if number < 20:
        return ONES[number]
    if number < 100:
        return " ".join(part for part in (TENS[number // 10], ONES[number % 10]) if part)
    for size, name in SCALES:
        if number >= size:
            rest = number % size
            return " ".join(part for part in (_words(number // size), name, _words(rest)) if part)
    return ""


@register.filter
def rupees_words(value):
    """3500 -> "Three Thousand Five Hundred Rupees Only"."""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return ""
    rupees = int(amount)
    paisa = int((amount - rupees) * 100)
    text = f"{_words(rupees) or 'Zero'} Rupees"
    if paisa:
        text += f" and {_words(paisa)} Paisa"
    return f"{text} Only"
