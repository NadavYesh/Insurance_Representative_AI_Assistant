"""Parsing the rep's answer to a Question. Code, not the LLM: the answer is short and
must be one of a few valid forms, so it is checked, never interpreted."""

from __future__ import annotations

import re
from collections.abc import Callable

from assistant.forms import REP_ANSWERABLE, Intent, Question, Unknown

_DONT_KNOW = {"לא יודע", "לא יודעת", "?", "idk", "dont know", "don't know"}
_YES = {"כן", "y", "yes"}
_NO = {"לא", "n", "no"}
_INTENTS = {
    "ביטול": Intent.CANCEL,
    "לבטל": Intent.CANCEL,
    "cancel": Intent.CANCEL,
    "החזר": Intent.REFUND,
    "refund": Intent.REFUND,
    "תביעה": Intent.CLAIM,
    "claim": Intent.CLAIM,
}
_POLICY_ID = re.compile(r"(?<!\d)\d{4}(?!\d)")


def _normalise(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _yes_no(question: Question, text: str) -> bool | Unknown | None:
    if text in _DONT_KNOW:
        return Unknown("הנציג לא יודע")
    if text in _YES:
        return True
    if text in _NO:
        return False
    return None


def _policy_id(question: Question, text: str) -> str | None:
    # "4418" or "פוליסה 4418"; exactly one 4-digit number, and one of the choices if given.
    ids = _POLICY_ID.findall(text)
    if len(ids) != 1 or (question.choices and ids[0] not in question.choices):
        return None
    return ids[0]


def _intent(question: Question, text: str) -> Intent | None:
    return _INTENTS.get(text)


_PARSERS: dict[str, Callable[[Question, str], object | None]] = {
    "claim_paid_last_12_months": _yes_no,
    "policy_id": _policy_id,
    "intent": _intent,
}
if _PARSERS.keys() != REP_ANSWERABLE:
    raise RuntimeError("every rep-answerable Request field needs a parser here")

HINTS = {
    "claim_paid_last_12_months": "כן / לא / לא יודע",
    "policy_id": "מספר פוליסה בן 4 ספרות",
    "intent": "ביטול / החזר / תביעה",
}


def parse_answer(question: Question, text: str) -> object | None:
    """The value to store in the Request, or None if the answer isn't valid."""
    return _PARSERS[question.field](question, _normalise(text))


def hint(question: Question) -> str:
    """What a valid answer looks like, for re-prompting."""
    if question.choices:
        return " / ".join(question.choices)
    return HINTS[question.field]
