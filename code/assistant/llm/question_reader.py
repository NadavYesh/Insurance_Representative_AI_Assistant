"""QuestionReader: the rep's free text → a Request. The LLM extracts; it decides nothing."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from assistant.forms import Intent, Request
from assistant.llm.client import LLM

INSTRUCTIONS = """\
You read a question that an insurance customer-service rep typed during a live call.
The question is usually in Hebrew. Extract only what the text says. Never guess.

- policy_id: a policy number, 4 digits (e.g. 4471). A bare 4-digit number is a policy
  number even if the rep calls it "customer" (לקוח). null if none is given.
- customer_id: a customer number in the form C-1234. null if none is given.
- intent:
  - "cancel": the customer wants to cancel, or asks what cancelling means for them.
  - "refund": asks about money owed back to them, without cancelling.
  - "claim": asks about a claim (תביעה): status, documents, timing, payment.
  - "other": anything else, or you can't tell.
- mentions_regulator: true if the text mentions a complaint, or a threat of one, to the
  regulator (רשות שוק ההון, ביטוח וחיסכון, the insurance commissioner, "רגולטור").
"""

# Any of these forces mentions_regulator, whatever the model says: an escalation must
# not depend on the model noticing it (Exceptions 04-ה).
_REGULATOR_WORDS = ("רשות שוק ההון", "רגולטור", "רגולציה", "המפקח על הביטוח", "הממונה על שוק ההון", "regulator")

_POLICY_ID = re.compile(r"^\d{4}$")
_CUSTOMER_ID = re.compile(r"^C-?(\d+)$", re.IGNORECASE)


class _Extraction(BaseModel):
    policy_id: str | None = Field(description="4-digit policy number, or null")
    customer_id: str | None = Field(description="customer number like C-1234, or null")
    intent: Literal["cancel", "refund", "claim", "other"]
    mentions_regulator: bool


class QuestionReader:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def read(self, question: str) -> Request:
        extraction = self._llm.parse(INSTRUCTIONS, question, _Extraction)
        return Request(
            question=question,
            intent=Intent(extraction.intent),
            policy_id=_checked_policy_id(extraction.policy_id, question),
            customer_id=_checked_customer_id(extraction.customer_id, question),
            mentions_regulator=extraction.mentions_regulator or _mentions_regulator(question),
        )


def _checked_policy_id(policy_id: str | None, question: str) -> str | None:
    """Keeps an ID only if it is well formed and actually appears in the question."""
    if policy_id is None:
        return None
    policy_id = policy_id.strip()
    if not _POLICY_ID.match(policy_id) or not re.search(rf"(?<!\d){policy_id}(?!\d)", question):
        return None
    return policy_id


def _checked_customer_id(customer_id: str | None, question: str) -> str | None:
    if customer_id is None:
        return None
    m = _CUSTOMER_ID.match(customer_id.strip())
    if not m or not re.search(rf"(?<!\d){m[1]}(?!\d)", question):
        return None
    return f"C-{m[1]}"


def _mentions_regulator(question: str) -> bool:
    lowered = question.lower()
    return any(word in lowered for word in _REGULATOR_WORDS)
