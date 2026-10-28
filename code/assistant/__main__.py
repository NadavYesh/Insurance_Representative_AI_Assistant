"""CLI for the rep.

    python -m assistant "לקוח 4471 רוצה לבטל, מה מגיע לו?"    # one question
    python -m assistant                                       # ask questions until an empty line
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from assistant.answers import hint, parse_answer
from assistant.config import DEFAULT_PATH, load_config
from assistant.forms import Question
from assistant.llm import LLMError, OpenAILLM
from assistant.pipeline import Assistant, Reply, ReplySource
from assistant.sources import CsvPolicySource

ENV_PATH = Path(__file__).parents[1] / ".env"

def ask_rep(question: Question) -> object | None:
    """Asks until the answer is valid. An empty line skips the question (returns None)."""
    print(f"❓ {question.text}")
    while True:
        text = input(f"   ({hint(question)}; Enter לדילוג) > ")
        if not text.strip():
            return None
        answer = parse_answer(question, text)
        if answer is not None:
            return answer
        print(f"   תשובה לא תקינה. נא לענות: {hint(question)}")


def show(reply: Reply) -> None:
    print()
    print(reply.text)
    if reply.source is ReplySource.PLAIN:
        why = f"מספרים שלא מופיעים בנתונים: {', '.join(reply.rejected_numbers)}" if reply.rejected_numbers else "המודל לא זמין"
        print(f"\n(התשובה המנוסחת נפסלה ({why}), ולכן מוצגים הנתונים כרשימה.)")
    rules = ", ".join(reply.decision.rules_used)
    print(f"\nנהלים: {rules or '—'} · {reply.seconds:.1f} שניות")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m assistant", description="Insurance rep assistant")
    parser.add_argument("question", nargs="?", help="the rep's question; omit for interactive mode")
    parser.add_argument("--config", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)

    load_dotenv(ENV_PATH)
    config = load_config(args.config)
    source = CsvPolicySource(config.policies_csv)
    for error in source.load_errors:
        print(f"warning: {error}", file=sys.stderr)

    try:
        assistant = Assistant(OpenAILLM(config.model_name), source, config.today)
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    questions = [args.question] if args.question else None
    while True:
        if questions is None:
            try:
                question = input("שאלה> ").strip()
            except EOFError:
                return 0
            if not question:
                return 0
        elif questions:
            question = questions.pop()
        else:
            return 0

        try:
            show(assistant.answer(question, ask_rep))
        except LLMError as e:
            # The question couldn't be read; nothing was decided, so say so plainly.
            print(f"\nלא ניתן לפענח את השאלה כרגע ({e}). נסו שוב.\n", file=sys.stderr)
            if questions is not None:
                return 1


if __name__ == "__main__":
    sys.exit(main())
