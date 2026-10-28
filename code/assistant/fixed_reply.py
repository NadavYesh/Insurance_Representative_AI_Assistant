"""FixedReply: escalations, blocks and missing-info replies, worded the same every time.

No LLM here (Ronit's requirement #3): a case above the rep's authority must not
depend on how a model phrases it.
"""

from assistant.forms import Decision, Outcome


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
            f"⚠️ להעביר ל{block.route_to}. אין לתת ללקוח תשובה עניינית.",
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
        lines += [f"- {q.text} (נוהל {q.rule_id})" for q in decision.questions]
        return "\n".join(lines)

    def _other_reasons(self, decision: Decision) -> list[str]:
        others = decision.blocks[1:]
        if not others:
            return []
        return ["סיבות נוספות:"] + [f"- {b.reason} (נוהל {b.rule_id})" for b in others]
