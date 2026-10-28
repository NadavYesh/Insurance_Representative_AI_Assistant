"""How values are written for the rep. One place, so the answer and its calculation agree."""

from datetime import date
from decimal import Decimal

from assistant.forms import Unknown


def show(value: object) -> str:
    if isinstance(value, Unknown):
        return f"לא ידוע ({value.reason})" if value.reason else "לא ידוע"
    if isinstance(value, bool):
        return "כן" if value else "לא"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)
