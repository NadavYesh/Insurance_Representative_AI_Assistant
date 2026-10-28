import time
from datetime import date

import pytest

from assistant.forms import Product, Unknown, is_unknown
from assistant.llm import LLMError
from assistant.pipeline import Assistant, ReplySource
from tests.helpers import FakeLLM, FakeSource, make_policy

TODAY = date(2026, 10, 25)
CANCEL_4471 = dict(policy_id="4471", customer_id=None, intent="cancel", mentions_regulator=False)


def assistant(llm, *policies) -> Assistant:
    return Assistant(llm, FakeSource(*(policies or (make_policy(),))), TODAY)


def never_asked(question):
    raise AssertionError(f"rep should not be asked: {question}")


def test_written_answer_that_passes_number_check():
    reply = assistant(FakeLLM(CANCEL_4471, written="דמי ביטול ₪150 (04-א)")).answer("4471 רוצה לבטל", never_asked)
    assert reply.source is ReplySource.WRITTEN
    assert reply.text.startswith("דמי ביטול ₪150 (04-א)")


@pytest.mark.parametrize("written", ["דמי ביטול ₪150", "דמי ביטול ₪999"])
def test_every_note_is_in_the_reply_word_for_word(written):
    """Written or fallback, the notes come from code, not from the model."""
    second = make_policy(policy_id="4472")
    reply = assistant(FakeLLM(CANCEL_4471, written=written), make_policy(), second).answer("4471 רוצה לבטל", never_asked)
    assert "04-ג" in reply.decision.rules_used
    for note in reply.decision.notes:
        assert note.text in reply.text


def test_invented_number_falls_back_to_plain_answer():
    reply = assistant(FakeLLM(CANCEL_4471, written="דמי ביטול ₪999")).answer("4471 רוצה לבטל", never_asked)
    assert reply.source is ReplySource.PLAIN
    assert reply.rejected_numbers == ("999",)
    assert "999" not in reply.text
    assert "150" in reply.text


def test_writer_failure_falls_back_to_plain_answer():
    class FailingWriter(FakeLLM):
        def write(self, instructions, text):
            raise LLMError("timeout")

    reply = assistant(FailingWriter(CANCEL_4471)).answer("4471 רוצה לבטל", never_asked)
    assert reply.source is ReplySource.PLAIN


def test_escalation_never_calls_the_writer():
    llm = FakeLLM(CANCEL_4471 | {"mentions_regulator": True}, written="should not be used")
    reply = assistant(llm).answer("4471 מאיים בתלונה", never_asked)
    assert reply.source is ReplySource.FIXED
    assert len(llm.calls) == 1  # the reader only


def test_rep_is_asked_and_answer_is_used():
    asked = []

    def rep(question):
        asked.append(question.field)
        return Unknown("הנציג לא יודע")

    health = make_policy(product=Product.HEALTH, start_date=date(2022, 1, 1))
    reply = assistant(FakeLLM(CANCEL_4471, written="תשובה"), health).answer("4471 רוצה לבטל", rep)
    assert asked == ["claim_paid_last_12_months"]
    assert is_unknown(reply.decision.value("seniority_bonus").value)
    assert reply.decision.value("cancellation_fee").value == 0


def test_timings_are_recorded():
    reply = assistant(FakeLLM(CANCEL_4471, written="תשובה")).answer("4471 רוצה לבטל", never_asked)
    assert set(reply.timings) == {"read", "write"}
    assert reply.seconds >= 0


# --- Follow-up questions in the same conversation ---

TWO_POLICIES = (make_policy(), make_policy(policy_id="4472", product=Product.HOME))
CANCEL_BY_CUSTOMER = CANCEL_4471 | {"policy_id": None, "customer_id": "C-1088"}


def test_rep_picks_a_policy_without_starting_over():
    asked = []

    def rep(question):
        asked.append(question)
        return "4472"

    reply = assistant(FakeLLM(CANCEL_BY_CUSTOMER, written="תשובה"), *TWO_POLICIES).answer("C-1088 רוצה לבטל", rep)
    assert [q.choices for q in asked] == [("4471", "4472")]
    assert reply.decision.policy.policy_id == "4472"
    assert reply.first_request.policy_id is None  # what was read, before the rep's answer


def test_rep_skipping_a_question_explains_what_is_missing():
    llm = FakeLLM(CANCEL_BY_CUSTOMER, written="should not be used")
    reply = assistant(llm, *TWO_POLICIES).answer("C-1088 רוצה לבטל", lambda q: None)
    assert reply.source is ReplySource.FIXED
    assert "4471" in reply.text and "4472" in reply.text
    assert len(llm.calls) == 1  # the reader only


def test_rep_thinking_time_is_not_counted():
    def slow_rep(question):
        time.sleep(0.2)
        return "4471"

    reply = assistant(FakeLLM(CANCEL_BY_CUSTOMER, written="תשובה"), *TWO_POLICIES).answer("C-1088 רוצה לבטל", slow_rep)
    assert reply.seconds < 0.2


@pytest.mark.parametrize("written", ["דמי ביטול ₪150", "דמי ביטול ₪999"])
def test_full_calculation_is_at_the_bottom_of_every_answer(written):
    """Written or fallback, the calculation comes from code, last."""
    reply = assistant(FakeLLM(CANCEL_4471, written=written)).answer("4471 רוצה לבטל", never_asked)
    assert "חישוב מלא (לבדיקה):" in reply.text
    refund = reply.decision.value("refund_estimate").explanation
    assert reply.text.rstrip().splitlines()[-2].startswith("- החזר משוער")
    assert refund in reply.text
