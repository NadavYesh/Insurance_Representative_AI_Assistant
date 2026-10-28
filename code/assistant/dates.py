"""Date parsing for the mixed formats in the policy data."""

from datetime import date, datetime

# ISO first; the export also has some DD/MM/YYYY dates (Israeli order, never MM/DD).
_FORMATS = ("%Y-%m-%d", "%d/%m/%Y")


def parse_date(text: str) -> date:
    text = text.strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognised date: {text!r}")
