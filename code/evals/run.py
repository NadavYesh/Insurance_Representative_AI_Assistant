"""Runs evals/cases.yaml and scores every case.

    python -m evals.run             # full: real LLM reads the question and writes the answer
    python -m evals.run --offline   # no LLM: the expected Request goes straight to the rules
    python -m evals.run -k 4401     # only cases whose id contains "4401"

Exits non-zero if any check fails, so it can gate a change.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

from assistant.__main__ import ENV_PATH
from assistant.answers import parse_answer
from assistant.config import load_config
from assistant.forms import Intent, Question, Request, is_unknown
from assistant.llm import LLMError, OpenAILLM
from assistant.pipeline import Assistant, Reply, ReplySource
from assistant.sources import CsvPolicySource

CASES = Path(__file__).with_name("cases.yaml")
MAX_SECONDS = 30  # Ronit's requirement #4


class OfflineLLM:
    """No model: the writer 'fails', so answers come out as the plain list."""

    def parse(self, instructions, text, schema):
        raise LLMError("offline")

    def write(self, instructions, text):
        raise LLMError("offline")


def run_case(assistant: Assistant, case: dict, offline: bool) -> tuple[list[str], Reply]:
    expect = case["expect"]
    answers = case.get("rep_answers", {})

    def ask_rep(question: Question):
        # The rep's typed text goes through the same parser as in the CLI; "" skips.
        if question.field not in answers:
            raise AssertionError(f"rep was asked {question.field}, but the case gives no answer")
        text = str(answers[question.field])
        if not text:
            return None
        parsed = parse_answer(question, text)
        if parsed is None:
            raise AssertionError(f"case answer {text!r} isn't valid for {question.field}")
        return parsed

    if offline:
        fields = {k: v for k, v in expect["request"].items() if k != "intent"}
        intent = Intent(expect["request"].get("intent", "cancel"))
        reply = assistant.answer_request(Request(question=case["question"], intent=intent, **fields), ask_rep)
    else:
        reply = assistant.answer(case["question"], ask_rep)

    return check(case, reply, offline), reply


def check(case: dict, reply: Reply, offline: bool) -> list[str]:
    expect = case["expect"]
    decision = reply.decision
    failures = []

    if not offline:
        for field_name, expected in expect["request"].items():
            actual = getattr(reply.first_request, field_name)
            actual = actual.value if isinstance(actual, Intent) else actual
            if actual != expected:
                failures.append(f"request.{field_name}: expected {expected!r}, got {actual!r}")

    if decision.outcome.value != expect["outcome"]:
        failures.append(f"outcome: expected {expect['outcome']}, got {decision.outcome.value}")
        return failures  # the rest would only repeat this

    if "rule" in expect and (not decision.blocks or decision.blocks[0].rule_id != expect["rule"]):
        got = decision.blocks[0].rule_id if decision.blocks else None
        failures.append(f"rule: expected {expect['rule']}, got {got}")

    actual_values = {v.name: v.value for v in decision.values}
    for name, expected in expect.get("values", {}).items():
        if name not in actual_values:
            failures.append(f"value {name}: missing")
        elif expected == "UNKNOWN":
            if not is_unknown(actual_values[name]):
                failures.append(f"value {name}: expected UNKNOWN, got {actual_values[name]}")
        elif is_unknown(actual_values[name]) or actual_values[name] != expected:
            failures.append(f"value {name}: expected {expected}, got {actual_values[name]}")

    note_ids = {n.rule_id for n in decision.notes}
    failures += [f"note {rule_id}: missing" for rule_id in expect.get("notes", []) if rule_id not in note_ids]

    failures += [f"answer drops note {n.rule_id}" for n in decision.notes if n.text not in reply.text]
    if reply.written:
        # Notes are added by code; the model restating one in its own words duplicates it.
        note_only = {n.rule_id for n in decision.notes} - {v.rule_id for v in decision.values}
        failures += [f"written part restates note {r}" for r in sorted(note_only) if r and r in reply.written]
    failures += [
        f"answer lacks the calculation of {v.name}"
        for v in decision.values
        if v.explanation and v.explanation not in reply.text
    ]
    failures += [f"answer lacks {text!r}" for text in expect.get("answer_contains", []) if text not in reply.text]
    failures += [f"answer has {text!r}" for text in expect.get("answer_excludes", []) if text in reply.text]

    if reply.seconds > MAX_SECONDS:
        failures.append(f"took {reply.seconds:.1f}s (limit {MAX_SECONDS}s)")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.run")
    parser.add_argument("--offline", action="store_true", help="skip the LLM; test the rules only")
    parser.add_argument("-k", default="", help="only cases whose id contains this")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every reply")
    args = parser.parse_args(argv)

    suite = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    today: date = suite["today"]
    cases = [c for c in suite["cases"] if args.k in c["id"]]

    load_dotenv(ENV_PATH)
    config = load_config()
    llm = OfflineLLM() if args.offline else OpenAILLM(config.model_name)
    assistant = Assistant(llm, CsvPolicySource(config.policies_csv), today)

    failed, replies = 0, []
    for case in cases:
        try:
            failures, reply = run_case(assistant, case, args.offline)
        except Exception as e:  # one broken case must not hide the others
            failures, reply = [f"crashed: {e!r}"], None
        replies.append(reply)
        failed += bool(failures)
        mark = "✗" if failures else "✓"
        extra = f" [{reply.source.value}, {reply.seconds:.1f}s]" if reply and not args.offline else ""
        print(f"{mark} {case['id']}{extra}")
        for failure in failures:
            print(f"    - {failure}")
        if args.verbose and reply:
            print("      " + reply.text.replace("\n", "\n      "))

    done = [r for r in replies if r is not None]
    print(f"\n{len(cases) - failed}/{len(cases)} cases passed")
    if not args.offline and done:
        answered = [r for r in done if r.source is not ReplySource.FIXED]
        written = sum(r.source is ReplySource.WRITTEN for r in answered)
        rejected = [n for r in answered for n in r.rejected_numbers]
        seconds = [r.seconds for r in done]
        print(f"written answers that passed NumberCheck: {written}/{len(answered)}")
        if rejected:
            print(f"numbers NumberCheck rejected: {', '.join(rejected)}")
        print(f"latency: median {statistics.median(seconds):.1f}s, max {max(seconds):.1f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
