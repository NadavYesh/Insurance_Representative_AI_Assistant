"""The whole flow for one rep question: read → decide (asking the rep if needed) → reply."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum

from assistant.fixed_reply import FixedReply
from assistant.forms import Decision, Maybe, Outcome, Question, Request
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
    decision: Decision
    source: ReplySource
    rejected_numbers: tuple[str, ...] = ()  # what NumberCheck caught, if it fell back
    seconds: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)


# Asks the rep a Question; returns their answer, or Unknown for "I don't know".
type AskRep = Callable[[Question], Maybe[bool]]


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
            seconds=time.perf_counter() - start,
            timings={"read": read_done - start, **reply.timings},
        )

    def answer_request(self, request: Request, ask_rep: AskRep) -> Reply:
        """From an already-read Request. Evals use this to test the rules without the reader."""
        decision = self.engine.decide(request)
        # Ends: a Decision never asks a question that was already answered.
        while decision.questions:
            answers = {q.field: ask_rep(q) for q in decision.questions}
            decision = self.engine.decide(replace(decision.request, **answers))

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
        return Reply(text.strip() + self.fixed.notes_block(decision), decision, ReplySource.WRITTEN, timings=timings)
