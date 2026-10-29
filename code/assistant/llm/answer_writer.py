"""AnswerWriter: a Decision → a short Hebrew answer for the rep. Phrasing only, no new facts."""

from __future__ import annotations

import json

from assistant.facts import decision_facts
from assistant.forms import Decision, Outcome
from assistant.llm.client import LLM

INSTRUCTIONS = """\
You write the answer an insurance customer-service rep reads during a live call.
You get the rep's question and FACTS (JSON) worked out by the company's rule engine.

Write in Hebrew, short: the rep reads it while the customer waits.
Start with what answers the question, as 2–4 bullet points. For a cancellation that is
the effective date, the cancellation fee and the estimated refund (procedure 01-§7).Leave out values that don't change the answer (e.g. a debt of 0, days since the last
payment when there is no arrears).

Notes for the customer and the full calculation are added by code after your text,
so write only the values, and don't explain how they were calculated.

- Use only the FACTS. Add no information, rule or advice of your own.
- Write dates as DD/MM/YYYY.
- Never compute anything: no sums, differences or percentages. Copy numbers and dates
  exactly as they appear in the FACTS.
- A value with "is_estimate": true is an estimate. Write "(הערכה)" next to it.
- A value "UNKNOWN" can't be worked out. Say so, and give its unknown_reason. Never
  fill it in.
- After each value, cite its rule in parentheses, e.g. (נוהל 01-§3).
- Never say whether, how or why a claim will be approved or rejected, or for how much.
  A list of documents is only what to submit; never present it as what decides the claim.
"""


class AnswerWriter:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def write(self, decision: Decision) -> str:
        if decision.outcome is not Outcome.ANSWER:
            raise ValueError(f"A {decision.outcome} decision gets a FixedReply, not a written answer")
        facts = json.dumps(decision_facts(decision), ensure_ascii=False, indent=2)
        return self._llm.write(INSTRUCTIONS, f"Question: {decision.request.question}\n\nFACTS:\n{facts}")
