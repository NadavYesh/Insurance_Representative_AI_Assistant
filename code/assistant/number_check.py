"""NumberCheck: every number in a written answer must come from the Decision.

The last line of defence against an invented amount or date (Ronit's requirement #1).
"""

import json
import re
from datetime import date
from decimal import Decimal

from assistant.facts import decision_facts
from assistant.forms import Decision

# No \b: Hebrew letters count as word characters, so "ב-31" or "ב31" would be missed.
_DATE = re.compile(
    r"(?<!\d)(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})[./](\d{1,2})[./](\d{4}))(?!\d)"
)
_NUMBER = re.compile(r"(?<!\d)\d+(?:,\d{3})*(?:\.\d+)?(?!\d)")


class NumberCheck:
    def unsupported(self, answer: str, decision: Decision) -> list[str]:
        """Numbers and dates in `answer` that the Decision doesn't support. Empty means OK."""
        fact_dates, fact_numbers = _extract(json.dumps(decision_facts(decision), ensure_ascii=False))
        allowed_dates = {d for _, d in fact_dates}
        allowed_numbers = {n for _, n in fact_numbers}
        # A date may also be written in words, e.g. "31 באוקטובר 2026".
        for d in allowed_dates:
            allowed_numbers |= {Decimal(d.day), Decimal(d.month), Decimal(d.year)}

        dates, numbers = _extract(answer)
        bad = [token for token, d in dates if d not in allowed_dates]
        bad += [token for token, n in numbers if n not in allowed_numbers]
        return bad


def _extract(text: str) -> tuple[list[tuple[str, date]], list[tuple[str, Decimal]]]:
    """(token, value) pairs for the dates and numbers in the text. Dates are taken out first."""
    dates: list[tuple[str, date]] = []

    def take_date(m: re.Match) -> str:
        y, mo, d = (m[1], m[2], m[3]) if m[1] else (m[6], m[5], m[4])
        try:
            dates.append((m[0], date(int(y), int(mo), int(d))))
        except ValueError:
            return m[0]  # not a real date; its parts get checked as numbers
        return " "

    rest = _DATE.sub(take_date, text)
    numbers = [(m[0], Decimal(m[0].replace(",", ""))) for m in _NUMBER.finditer(rest)]
    return dates, numbers
