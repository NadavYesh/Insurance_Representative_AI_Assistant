"""AnswerWriter: a Decision → a short Hebrew answer for the rep. Phrasing only, no new facts."""

from __future__ import annotations

import json

from assistant.facts import decision_facts
from assistant.forms import Decision, Outcome
from assistant.llm.client import LLM

INSTRUCTIONS = """\
You write the answer an insurance customer-service rep reads during a live call.
You get the rep's question and FACTS (JSON) worked out by the company's rule engine.

Write in Hebrew, short, as bullet points the rep can read out.
- Use only the FACTS. Add no information, rule or advice of your own.
- Never compute anything: no sums, differences or percentages. Copy numbers and dates
  exactly as they appear in the FACTS.
- A value with "is_estimate": true is an estimate. Say "הערכה" next to it, and that the
  final amount is set by the finance department.
- A value "UNKNOWN" can't be worked out. Say so, and give its unknown_reason. Never
  fill it in.
- After each value or note, cite its rule in parentheses, e.g. (נוהל 01-§3).
- Include every note.
- Never say whether a claim will be approved, or for how much.
"""


class AnswerWriter:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def write(self, decision: Decision) -> str:
        if decision.outcome is not Outcome.ANSWER:
            raise ValueError(f"A {decision.outcome} decision gets a FixedReply, not a written answer")
        facts = json.dumps(decision_facts(decision), ensure_ascii=False, indent=2)
        return self._llm.write(INSTRUCTIONS, f"Question: {decision.request.question}\n\nFACTS:\n{facts}")
