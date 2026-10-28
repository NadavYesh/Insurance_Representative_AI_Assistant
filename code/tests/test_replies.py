"""FixedReply, NumberCheck, and the two LLM workers with a fake model."""

from datetime import date
from decimal import Decimal

import pytest

from assistant.fixed_reply import FixedReply
from assistant.forms import Block, Decision, Intent, Note, Outcome, Question, Request, Unknown, Value
from assistant.llm import AnswerWriter, QuestionReader
from assistant.number_check import NumberCheck
from tests.helpers import FakeLLM, make_policy

REQUEST = Request(question="לקוח 4471 רוצה לבטל", intent=Intent.CANCEL, policy_id="4471")
ANSWER = Decision(
    REQUEST,
    Outcome.ANSWER,
    make_policy(),
    values=(
        Value("cancellation_fee", Decimal(150), "04-א"),
        Value("effective_date", date(2026, 10, 31), "01-§1"),
        Value("seniority_bonus", Unknown("לא ידוע אם שולמה תביעה"), "02-§3", is_estimate=True),
    ),
    notes=(Note("ההנחה של 5% תבוטל", "04-ג"),),
)


# --- FixedReply ---


def test_escalation_reply_names_reason_rule_target_and_time():
    blocks = (
        Block("01-§6", "תביעה פתוחה", route_to="מנהל משמרת", response_time="2 ימי עסקים"),
        Block("04-ה", "תלונה לרגולטור", route_to="מנהל משמרת"),
    )
    text = FixedReply().render(Decision(REQUEST, Outcome.ESCALATE, make_policy(), blocks=blocks))
    for part in ("מנהל משמרת", "תביעה פתוחה", "01-§6", "2 ימי עסקים", "סיבות נוספות", "04-ה"):
        assert part in text


def test_block_reply():
    text = FixedReply().render(Decision(REQUEST, Outcome.BLOCKED, make_policy(), blocks=(Block("04-ד", "פוליסה מוקפאת"),)))
    assert "פוליסה מוקפאת" in text and "04-ד" in text


def test_need_info_reply_lists_notes_and_questions():
    question = Question("claim_paid_last_12_months", "האם שולמה תביעה?", "02-§3")
    decision = Decision(REQUEST, Outcome.NEED_INFO, make_policy(), notes=(Note("חסר"),), questions=(question,))
    text = FixedReply().render(decision)
    assert "חסר" in text and "האם שולמה תביעה?" in text


def test_fixed_reply_refuses_answers():
    with pytest.raises(ValueError):
        FixedReply().render(ANSWER)


def test_same_decision_same_words():
    decision = Decision(REQUEST, Outcome.BLOCKED, make_policy(), blocks=(Block("04-ד", "פוליסה מוקפאת"),))
    assert FixedReply().render(decision) == FixedReply().render(decision)


# --- NumberCheck ---


@pytest.mark.parametrize(
    "answer",
    [
        "דמי ביטול: ₪150 (04-א)",
        "הביטול ייכנס לתוקף ב-31/10/2026",
        "הביטול ייכנס לתוקף ב-31.10.2026",
        "הביטול ייכנס לתוקף ב-31 באוקטובר 2026",
        "פוליסה 4471, לקוח C-1088, פרמיה 410",
        "ההנחה של 5% תבוטל (נוהל 04-ג)",
    ],
)
def test_numbers_from_the_decision_pass(answer):
    assert NumberCheck().unsupported(answer, ANSWER) == []


@pytest.mark.parametrize(
    "answer, bad",
    [
        ("דמי ביטול: ₪200", ["200"]),
        ("החזר משוער: 1,230 ₪", ["1,230"]),
        ("הביטול ייכנס לתוקף ב-30/11/2026", ["30/11/2026"]),
        ("ב150 ₪ ועוד 75", ["75"]),
        ("מענק של 15%", ["15"]),
    ],
)
def test_invented_numbers_are_caught(answer, bad):
    assert NumberCheck().unsupported(answer, ANSWER) == bad


def test_numbers_from_the_question_alone_are_not_allowed():
    request = Request(question="הלקוח אומר שמגיע לו 900", intent=Intent.CANCEL, policy_id="4471")
    decision = Decision(request, Outcome.ANSWER, make_policy())
    assert NumberCheck().unsupported("מגיע לו 900", decision) == ["900"]


# --- QuestionReader ---


def reader(**parsed) -> QuestionReader:
    fields = dict(policy_id=None, customer_id=None, intent="cancel", mentions_regulator=False) | parsed
    return QuestionReader(FakeLLM(parsed=fields))


def test_reader_builds_a_request():
    request = reader(policy_id="4471").read("לקוח 4471 רוצה לבטל, מה מגיע לו?")
    assert request == Request(question="לקוח 4471 רוצה לבטל, מה מגיע לו?", intent=Intent.CANCEL, policy_id="4471")


def test_reader_drops_an_id_not_in_the_question():
    assert reader(policy_id="4472").read("לקוח 4471 רוצה לבטל").policy_id is None


def test_reader_drops_a_malformed_policy_id():
    assert reader(policy_id="44711").read("פוליסה 44711").policy_id is None


def test_reader_normalises_customer_id():
    assert reader(customer_id="c1072").read("לקוח C-1072 רוצה לבטל").customer_id == "C-1072"


def test_regulator_keyword_overrides_the_model():
    request = reader(mentions_regulator=False).read("הלקוח מאיים להתלונן ברשות שוק ההון על 4471")
    assert request.mentions_regulator


# --- AnswerWriter ---


def test_writer_sends_question_and_facts():
    llm = FakeLLM(written="תשובה")
    assert AnswerWriter(llm).write(ANSWER) == "תשובה"
    _, text = llm.calls[0]
    assert REQUEST.question in text
    assert '"UNKNOWN"' in text and "לא ידוע אם שולמה תביעה" in text


def test_writer_refuses_non_answers():
    decision = Decision(REQUEST, Outcome.BLOCKED, make_policy(), blocks=(Block("04-ד", "מוקפאת"),))
    with pytest.raises(ValueError):
        AnswerWriter(FakeLLM()).write(decision)
