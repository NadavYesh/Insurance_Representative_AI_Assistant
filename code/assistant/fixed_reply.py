"""FixedReply: escalations, blocks and missing-info replies, worded the same every time.

No LLM here (Ronit's requirement #3): a case above the rep's authority must not
depend on how a model phrases it.
"""

from assistant.facts import LABELS
from assistant.formatting import show
from assistant.forms import Decision, Outcome, is_unknown


class FixedReply:
    def render(self, decision: Decision) -> str:
        if decision.outcome is Outcome.ESCALATE:
            return self._escalation(decision)
        if decision.outcome is Outcome.BLOCKED:
            return self._block(decision)
        if decision.outcome is Outcome.NEED_INFO:
            return self._need_info(decision)
        raise ValueError("Answers are written by the AnswerWriter, not FixedReply")

    def _escalation(self, decision: Decision) -> str:
        block = decision.blocks[0]
        lines = [
            f"⚠️ להעביר ל{block.route_to}. אין לתת ללקוח תשובה.",
            f"סיבה: {block.reason} (נוהל {block.rule_id})",
        ]
        if block.response_time:
            lines.append(f"מה לומר ללקוח: הבקשה מועברת ל{block.route_to}, ותשובה תינתן תוך {block.response_time}.")
        else:
            lines.append(f"מה לומר ללקוח: הבקשה מועברת ל{block.route_to}.")
        lines += self._other_reasons(decision)
        return "\n".join(lines)

    def _block(self, decision: Decision) -> str:
        block = decision.blocks[0]
        lines = [f"⛔ לא ניתן לבצע את הבקשה. {block.reason} (נוהל {block.rule_id})"]
        lines += self._other_reasons(decision)
        return "\n".join(lines)

    def _need_info(self, decision: Decision) -> str:
        lines = ["❓ חסר מידע כדי לענות."]
        lines += [f"- {note.text}" for note in decision.notes]
        lines += [f"- {q.text}" + (f" (נוהל {q.rule_id})" if q.rule_id else "") for q in decision.questions]
        return "\n".join(lines)

    def plain_answer(self, decision: Decision) -> str:
        """An ANSWER decision as a plain list, with no LLM. The fallback when the
        written answer fails NumberCheck or the model is unavailable."""
        if decision.outcome is not Outcome.ANSWER:
            raise ValueError(f"A {decision.outcome} decision is rendered with render()")
        p = decision.policy
        lines = [f"פוליסה {p.policy_id} · {p.customer_name} · {p.product} · {p.status}"]
        for v in decision.values:
            estimate = " (הערכה)" if v.is_estimate and not is_unknown(v.value) else ""
            lines.append(f"- {LABELS.get(v.name, v.name)}: {show(v.value)}{estimate} (נוהל {v.rule_id})")
        return "\n".join(lines) + self.answer_footer(decision)

    def answer_footer(self, decision: Decision) -> str:
        """What code adds under every answer, written or plain: the notes, then the
        full calculation."""
        return self.notes_block(decision) + self.calculation_block(decision)

    def calculation_block(self, decision: Decision) -> str:
        """Every value with how it was worked out, from the rules themselves, so the
        rep can check the answer by eye."""
        if not decision.values:
            return ""
        lines = []
        for v in decision.values:
            how = v.explanation or show(v.value)
            estimate = " (הערכה)" if v.is_estimate and not is_unknown(v.value) else ""
            lines.append(f"- {LABELS.get(v.name, v.name)}: {how}{estimate} (נוהל {v.rule_id})")
        return "\n\nחישוב מלא (לבדיקה):\n" + "\n".join(lines)

    def notes_block(self, decision: Decision) -> str:
        """The notes, word for word. Added by code after any answer, so a required
        disclosure (e.g. the lost multi-policy discount, 04-ג) never depends on the LLM."""
        if not decision.notes:
            return ""
        lines = [f"- {n.text}" + (f" (נוהל {n.rule_id})" if n.rule_id else "") for n in decision.notes]
        return "\n\nלומר ללקוח / לשים לב:\n" + "\n".join(lines)

    def _other_reasons(self, decision: Decision) -> list[str]:
        others = decision.blocks[1:]
        if not others:
            return []
        return ["סיבות נוספות:"] + [f"- {b.reason} (נוהל {b.rule_id})" for b in others]

