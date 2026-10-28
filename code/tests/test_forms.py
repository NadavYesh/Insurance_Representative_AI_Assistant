from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from assistant.forms import (
    UNKNOWN,
    Block,
    Decision,
    Intent,
    Note,
    Outcome,
    Policy,
    PolicyStatus,
    Product,
    Question,
    Request,
    Unknown,
    Value,
    is_unknown,
)


def make_policy(**overrides) -> Policy:
    fields = dict(
        policy_id="4471",
        customer_id="C-1088",
        customer_name="רונן אביטל",
        product=Product.CAR,
        status=PolicyStatus.ACTIVE,
        start_date=date(2023, 2, 10),
        monthly_premium=Decimal(410),
        last_payment_date=date(2026, 10, 5),
        open_claims=0,
    )
    return Policy(**(fields | overrides))


REQUEST = Request(question="customer 4471 wants to cancel", intent=Intent.CANCEL, policy_id="4471")


# --- Unknown ---


def test_arithmetic_with_unknown_stays_unknown():
    missing = Unknown("no payout history")
    assert (Decimal(240) - missing) is missing
    assert (missing * 12) is missing
    assert (-missing) is missing
    assert (date(2026, 10, 25) + missing) is missing
    assert (timedelta(days=30) + missing) is missing


def test_comparison_with_unknown_is_unknown():
    assert (UNKNOWN < 12) is UNKNOWN
    assert (12 < UNKNOWN) is UNKNOWN
    assert (date(2026, 1, 1) >= UNKNOWN) is UNKNOWN


def test_unknown_cannot_be_branched_on():
    with pytest.raises(TypeError, match="no payout history"):
        if Unknown("no payout history") < 12:
            pass


def test_first_unknown_reason_wins():
    a, b = Unknown("a"), Unknown("b")
    assert (a + b) is a


def test_is_unknown():
    assert is_unknown(UNKNOWN)
    assert is_unknown(Unknown("x"))
    assert not is_unknown(0)
    assert not is_unknown(None)


# --- Enums ---


def test_enums_parse_hebrew_data_values():
    assert Product("רכב") is Product.CAR
    assert PolicyStatus("מוקפאת") is PolicyStatus.FROZEN


# --- Policy ---


def test_fields_missing_from_csv_default_to_unknown():
    policy = make_policy()
    assert is_unknown(policy.paid_through)
    assert is_unknown(policy.claim_stage)


def test_policy_is_frozen():
    with pytest.raises(AttributeError):
        make_policy().status = PolicyStatus.CANCELLED


# --- Request ---


def test_rep_fact_starts_unasked():
    assert REQUEST.claim_paid_last_12_months is None


def test_rep_dont_know_blocks_dependent_decisions():
    request = replace(REQUEST, claim_paid_last_12_months=Unknown("rep doesn't know"))
    with pytest.raises(TypeError, match="rep doesn't know"):
        if not request.claim_paid_last_12_months:
            pass


# --- Question ---


def test_question_must_name_a_rep_answerable_field():
    with pytest.raises(ValueError):
        Question("customer_name", "?", "02-§3")


# --- Decision ---


def test_answer_decision():
    decision = Decision(
        request=REQUEST,
        outcome=Outcome.ANSWER,
        policy=make_policy(),
        values=(
            Value("cancellation_fee", Decimal(150), "04-א"),
            Value("seniority_bonus", Unknown("x"), "02-§3", is_estimate=True),
        ),
        notes=(Note("multi-policy discount ends", "04-ג"),),
    )
    assert decision.value("cancellation_fee").value == 150
    assert [v.name for v in decision.unknowns] == ["seniority_bonus"]
    assert decision.rules_used == ("04-א", "02-§3", "04-ג")
    assert decision.winning_block is None


def test_escalation_lists_all_blocks_and_first_wins():
    regulator = Block("04-ה", "regulator complaint", route_to="מנהל משמרת")
    claim = Block("01-§6", "open claim", route_to="מנהל משמרת", response_time="2 ימי עסקים")
    decision = Decision(REQUEST, Outcome.ESCALATE, make_policy(), blocks=(regulator, claim))
    assert decision.winning_block is regulator
    assert decision.rules_used == ("04-ה", "01-§6")


def test_rules_used_has_no_repeats():
    decision = Decision(
        REQUEST,
        Outcome.ANSWER,
        make_policy(),
        values=(Value("fee", Decimal(0), "01-§2"), Value("effective_date", date(2026, 10, 25), "01-§2")),
    )
    assert decision.rules_used == ("01-§2",)


def test_need_info_may_have_no_policy():
    request = Request(question="customer wants to cancel", intent=Intent.CANCEL)
    assert Decision(request, Outcome.NEED_INFO).policy is None


CLAIM_PAID = Question("claim_paid_last_12_months", "האם שולמה ללקוח תביעה ב-12 החודשים האחרונים?", "02-§3")


def test_need_info_asks_the_rep():
    decision = Decision(REQUEST, Outcome.NEED_INFO, make_policy(product=Product.HEALTH), questions=(CLAIM_PAID,))
    assert decision.questions == (CLAIM_PAID,)
    assert decision.rules_used == ("02-§3",)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(outcome=Outcome.ANSWER, questions=(CLAIM_PAID,)),  # only NEED_INFO asks
        dict(  # asking again after the rep answered "don't know"
            outcome=Outcome.NEED_INFO,
            request=replace(REQUEST, claim_paid_last_12_months=UNKNOWN),
            questions=(CLAIM_PAID,),
        ),
        dict(outcome=Outcome.ESCALATE),  # escalation without a block
        dict(outcome=Outcome.BLOCKED, blocks=(Block("04-ה", "x", route_to="מנהל משמרת"),)),  # routed block
        dict(outcome=Outcome.ESCALATE, blocks=(Block("04-ד", "frozen"),)),  # unrouted escalation
        dict(outcome=Outcome.ANSWER, blocks=(Block("04-ד", "frozen"),)),  # answer with a block
        dict(outcome=Outcome.ANSWER, policy=None),  # answer without a policy
        dict(outcome=Outcome.ANSWER, values=(Value("fee", 0, "a"), Value("fee", 50, "b"))),
    ],
)
def test_inconsistent_decisions_are_rejected(kwargs):
    fields = dict(request=REQUEST, policy=make_policy()) | kwargs
    with pytest.raises(ValueError):
        Decision(**fields)
