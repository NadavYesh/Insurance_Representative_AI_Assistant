"""The whole flow for one rep question: read → decide (asking the rep if needed) → reply."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum

from assistant.fixed_reply import FixedReply
from assistant.forms import Decision, Outcome, Question, Request
from assistant.llm import LLM, AnswerWriter, LLMError, QuestionReader
from assistant.number_check import NumberCheck
from assistant.rules import BLOCKING_RULES, NOTE_RULES, TABLES, RuleEngine
from assistant.sources import PolicySource


class ReplySource(StrEnum):
    FIXED = "fixed"  # escalation, block or missing info: fixed wording
    WRITTEN = "written"  # written by the LLM and passed NumberCheck
    PLAIN = "plain"  # the written answer was rejected or failed; plain list instead


@dataclass(frozen=True)
class Reply:
    text: str
    decision: Decision  # its request includes the rep's answers to follow-up questions
    source: ReplySource
    rejected_numbers: tuple[str, ...] = ()  # what NumberCheck caught, if it fell back
    first_request: Request | None = None  # as read from the question, before any follow-up
    seconds: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)


# Asks the rep a Question. Returns the parsed answer (Unknown for "I don't know"),
# or None if the rep skips it; the reply then explains what is missing.
type AskRep = Callable[[Question], object | None]


class Assistant:
    def __init__(self, llm: LLM, source: PolicySource, today: date) -> None:
        self.reader = QuestionReader(llm)
        self.engine = RuleEngine(source, BLOCKING_RULES, TABLES, NOTE_RULES, today)
        self.writer = AnswerWriter(llm)
        self.fixed = FixedReply()
        self.check = NumberCheck()

    def answer(self, question: str, ask_rep: AskRep) -> Reply:
        start = time.perf_counter()
        request = self.reader.read(question)
        read_done = time.perf_counter()
        reply = self.answer_request(request, ask_rep)
        return replace(
            reply,
            seconds=reply.seconds + (read_done - start),
            timings={"read": read_done - start, **reply.timings},
        )

    def answer_request(self, request: Request, ask_rep: AskRep) -> Reply:
        """From an already-read Request. Evals use this to test the rules without the reader.

        `seconds` is the tool's own time: time the rep spends answering is left out.
        """
        start = time.perf_counter()
        rep_time = 0.0
        decision = self.engine.decide(request)
        # Ends when the rep answers or skips; "I don't know" is never asked twice (see Decision).
        while decision.questions:
            answers = {}
            for q in decision.questions:
                asked = time.perf_counter()
                answer = ask_rep(q)
                rep_time += time.perf_counter() - asked
                if answer is None:  # skipped: say what's missing instead of answering
                    reply = Reply(self.fixed.render(decision), decision, ReplySource.FIXED)
                    return replace(reply, first_request=request, seconds=time.perf_counter() - start - rep_time)
                answers[q.field] = answer
            decision = self.engine.decide(replace(decision.request, **answers))

        reply = self._reply(decision)
        return replace(reply, first_request=request, seconds=time.perf_counter() - start - rep_time)

    def _reply(self, decision: Decision) -> Reply:
        if decision.outcome is not Outcome.ANSWER:
            return Reply(self.fixed.render(decision), decision, ReplySource.FIXED)

        start = time.perf_counter()
        try:
            text = self.writer.write(decision)
        except LLMError:
            return Reply(self.fixed.plain_answer(decision), decision, ReplySource.PLAIN)
        timings = {"write": time.perf_counter() - start}

        bad = self.check.unsupported(text, decision)
        if bad:
            return Reply(self.fixed.plain_answer(decision), decision, ReplySource.PLAIN, tuple(bad), timings=timings)
        return Reply(text.strip() + self.fixed.answer_footer(decision), decision, ReplySource.WRITTEN, timings=timings)
