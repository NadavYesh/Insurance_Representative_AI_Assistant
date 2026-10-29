"""The rulebook against the procedures. Expected numbers are worked out by hand from
data/policies/01–04, with today = 2026-10-25 (the export date)."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from assistant.forms import Intent, Outcome, PolicyStatus, Product, Request, Unknown, is_unknown
from assistant.rules import BLOCKING_RULES, NOTE_RULES, TABLES, RuleEngine
from assistant.rules.rulebook import bonus_rate, month_end, months_between
from assistant.sources import CsvPolicySource
from tests.helpers import FakeSource, make_policy

TODAY = date(2026, 10, 25)
REAL_CSV = Path(__file__).parents[2] / "data" / "policies.csv"


def ask(source, policy_id: str, intent=Intent.CANCEL, **fields):
    engine = RuleEngine(source, BLOCKING_RULES, TABLES, NOTE_RULES, TODAY)
    return engine.decide(Request(question="q", intent=intent, policy_id=policy_id, **fields))


def values(decision) -> dict:
    return {v.name: v.value for v in decision.values}


def rule_ids(items) -> list[str]:
    return [i.rule_id for i in items]


# --- Helpers ---


@pytest.mark.parametrize(
    "start, end, months",
    [
        (date(2023, 2, 10), TODAY, 44),
        (date(2025, 10, 25), TODAY, 12),
        (date(2025, 10, 26), TODAY, 11),
        (date(2026, 11, 8), TODAY, 0),  # not started yet
    ],
)
def test_months_between(start, end, months):
    assert months_between(start, end) == months


@pytest.mark.parametrize("months, rate", [(0, 0), (11, 0), (12, 5), (35, 5), (36, 10), (60, 10), (61, 15)])
def test_bonus_rate_brackets(months, rate):
    assert bonus_rate(months) == rate


def test_month_end():
    assert month_end(date(2026, 2, 3)) == date(2026, 2, 28)
    assert month_end(TODAY) == date(2026, 10, 31)


# --- Made-up policies, for cases the CSV doesn't cover ---


def test_non_car_under_a_year_pays_50():
    source = FakeSource(make_policy(product=Product.HOME, start_date=date(2026, 3, 1)))
    assert values(ask(source, "4471"))["cancellation_fee"] == 50


def test_health_bonus_skipped_when_claim_paid():
    source = FakeSource(make_policy(product=Product.HEALTH, start_date=date(2024, 6, 1)))
    decision = ask(source, "4471", claim_paid_last_12_months=True)
    assert values(decision)["seniority_bonus"] == 0


def test_health_under_a_year_does_not_ask_the_rep():
    source = FakeSource(make_policy(product=Product.HEALTH, start_date=date(2026, 3, 1)))
    assert ask(source, "4471").questions == ()


def test_prepaid_past_cancellation_leaves_prorated_part_to_finance():
    source = FakeSource(make_policy(paid_through=date(2026, 12, 31)))
    v = values(ask(source, "4471"))
    assert is_unknown(v["prorated_premium"])
    assert is_unknown(v["refund_estimate"])


@pytest.mark.parametrize(
    "last_payment, debt",
    [
        (date(2026, 8, 26), 0),  # 60 days: not arrears yet
        (date(2026, 8, 20), 2 * 410),  # 66 days: September and October
        (date(2026, 7, 31), 3 * 410),  # a month-end payment covers only its own month: August to October
        (date(2026, 6, 2), 4 * 410),  # July to October
    ],
)
def test_arrears_debt_counts_unpaid_months(last_payment, debt):
    source = FakeSource(make_policy(last_payment_date=last_payment))
    assert values(ask(source, "4471"))["arrears_debt"] == debt


def test_debt_smaller_than_refund_is_offset():
    # Paid through September by an earlier payment: only October is owed.
    policy = make_policy(
        product=Product.HOME,
        start_date=date(2019, 1, 1),
        monthly_premium=Decimal(100),
        last_payment_date=date(2026, 8, 20),
        paid_through=date(2026, 9, 30),
    )
    decision = ask(FakeSource(policy), "4471")
    v = values(decision)
    assert decision.outcome is Outcome.ANSWER
    assert v["arrears_debt"] == 100
    assert v["refund_estimate"] == 80  # 0 − 0 + 180 (15% × 1,200) − 100
    assert "01-§5" in rule_ids(decision.notes)


def test_debt_with_unknown_refund_is_answered_not_escalated():
    """The refund can't be compared with the debt, so the rep gets the debt and the 01-§5 note."""
    policy = make_policy(product=Product.HEALTH, start_date=date(2022, 1, 1), last_payment_date=date(2026, 6, 2))
    decision = ask(FakeSource(policy), "4471", claim_paid_last_12_months=Unknown("הנציג לא יודע"))
    v = values(decision)
    assert decision.outcome is Outcome.ANSWER
    assert v["arrears_debt"] == 4 * 410
    assert is_unknown(v["refund_estimate"])
    assert "01-§5" in rule_ids(decision.notes)


def test_policy_not_started_owes_nothing():
    policy = make_policy(product=Product.TRAVEL, start_date=date(2026, 11, 20), last_payment_date=date(2026, 7, 1))
    assert values(ask(FakeSource(policy), "4471"))["arrears_debt"] == 0


def test_debt_does_not_block_claim_questions():
    source = FakeSource(make_policy(last_payment_date=date(2026, 6, 2)))
    assert ask(source, "4471", intent=Intent.CLAIM).outcome is Outcome.ANSWER


def test_regulator_wins_over_everything():
    source = FakeSource(make_policy(open_claims=1, status=PolicyStatus.FROZEN))
    decision = ask(source, "4471", mentions_regulator=True)
    assert decision.outcome is Outcome.ESCALATE
    assert rule_ids(decision.blocks) == ["04-ה", "01-§6", "04-ד"]


# --- Real policies ---


@pytest.fixture(scope="module")
def real():
    if not REAL_CSV.exists():
        pytest.skip("data/ is not committed")
    return CsvPolicySource(REAL_CSV)


def test_4471_car_three_plus_years(real):
    decision = ask(real, "4471")
    v = values(decision)
    assert decision.outcome is Outcome.ANSWER
    assert v["seniority_months"] == 44
    assert v["effective_date"] == date(2026, 10, 31)  # end of the billing month (01-§1)
    assert v["cancellation_fee"] == 150  # car, any seniority (04-א)
    assert v["seniority_bonus_rate_percent"] == 10
    assert v["seniority_bonus"] == Decimal(492)  # 10% × 410 × 12
    assert v["prorated_premium"] == 0  # paid for October only
    assert v["arrears_debt"] == 0
    assert v["refund_estimate"] == Decimal(342)  # 0 − 150 + 492 − 0
    assert decision.value("refund_estimate").is_estimate
    assert "04-ג" not in rule_ids(decision.notes)


def test_4425_open_claim_escalates(real):
    decision = ask(real, "4425")
    assert decision.outcome is Outcome.ESCALATE
    assert decision.blocks[0].rule_id == "01-§6"
    assert decision.blocks[0].response_time == "2 ימי עסקים"


def test_4455_frozen_is_blocked(real):
    decision = ask(real, "4455")
    assert decision.outcome is Outcome.BLOCKED
    assert decision.blocks[0].rule_id == "04-ד"


def test_4437_trip_started_is_blocked(real):
    decision = ask(real, "4437")
    assert decision.outcome is Outcome.BLOCKED
    assert decision.blocks[0].rule_id == "01-§4"


def test_4402_already_cancelled_is_blocked(real):
    assert ask(real, "4402").outcome is Outcome.BLOCKED


def test_4403_future_trip_has_no_cooling_off(real):
    """Travel is cancellable free of charge until the day before the trip (01-§4)."""
    decision = ask(real, "4403")
    v = values(decision)
    assert decision.outcome is Outcome.ANSWER
    assert v["cooling_off"] is False
    assert decision.value("cooling_off").rule_id == "01-§4"
    assert v["effective_date"] == date(2026, 10, 31)  # end of the month (01-§1)
    assert v["cancellation_fee"] == 0
    assert decision.value("cancellation_fee").rule_id == "01-§4"
    assert v["refund_estimate"] == 0  # 0 − 0 + 0
    assert "01-§4" in rule_ids(decision.notes)


def test_trip_the_day_after_can_still_be_cancelled():
    source = FakeSource(make_policy(product=Product.TRAVEL, start_date=TODAY + timedelta(days=1)))
    decision = ask(source, "4471")
    assert decision.outcome is Outcome.ANSWER
    assert values(decision)["cooling_off"] is False


def test_trip_starting_today_is_blocked():
    decision = ask(FakeSource(make_policy(product=Product.TRAVEL, start_date=TODAY)), "4471")
    assert decision.outcome is Outcome.BLOCKED
    assert decision.blocks[0].rule_id == "01-§4"


def test_trip_before_month_end_leaves_effective_date_unknown():
    """Cancelling at the end of the month would end the policy after the trip has started."""
    source = FakeSource(make_policy(product=Product.TRAVEL, start_date=date(2026, 10, 28)))
    v = values(ask(source, "4471"))
    assert is_unknown(v["effective_date"])
    assert is_unknown(v["refund_estimate"])


def test_non_travel_not_yet_started_is_cooling_off():
    source = FakeSource(make_policy(product=Product.HOME, start_date=date(2026, 11, 1)))
    assert values(ask(source, "4471"))["cooling_off"] is True


def test_cooling_off_ends_after_14_days():
    in_window = FakeSource(make_policy(product=Product.HOME, start_date=TODAY - timedelta(days=14)))
    after = FakeSource(make_policy(product=Product.HOME, start_date=TODAY - timedelta(days=15)))
    assert values(ask(in_window, "4471"))["cooling_off"] is True
    assert values(ask(after, "4471"))["cooling_off"] is False


def test_4416_car_in_cooling_off_pays_no_150(real):
    decision = ask(real, "4416")
    assert values(decision)["cancellation_fee"] == 0
    assert decision.value("cancellation_fee").rule_id == "01-§2"


def test_4441_fee_above_refund_goes_to_collections(real):
    """No debt, but the ₪150 car fee is more than the refund: no refund, talk to collections."""
    decision = ask(real, "4441")
    v = values(decision)
    assert decision.outcome is Outcome.ESCALATE
    assert decision.blocks[0].rule_id == "01-§5"
    assert decision.blocks[0].route_to == "מחלקת גבייה"
    assert v["cancellation_fee"] == 150
    assert v["seniority_bonus"] == 0
    assert v["arrears_debt"] == 0
    assert v["refund_estimate"] == 0


def test_refund_covering_the_fee_is_answered(real):
    assert ask(real, "4471").outcome is Outcome.ANSWER  # 492 bonus − 150 fee = 342


def test_unknown_refund_is_answered_not_sent_to_collections(real):
    decision = ask(real, "4401", claim_paid_last_12_months=Unknown("הנציג לא יודע"))
    assert decision.outcome is Outcome.ANSWER
    assert is_unknown(decision.value("refund_estimate").value)


def test_no_answer_ever_has_a_refund_below_zero(real):
    """A balance below 0 always goes to collections, so no answer can carry one."""
    for policy_id in [f"{n}" for n in range(4401, 4461)] + ["4471"]:
        decision = ask(real, policy_id, claim_paid_last_12_months=False)
        if decision.outcome is Outcome.ANSWER:
            refund = decision.value("refund_estimate").value
            assert is_unknown(refund) or refund >= 0, policy_id


def test_4401_old_health_asks_the_rep_first(real):
    decision = ask(real, "4401")
    assert decision.outcome is Outcome.NEED_INFO
    assert [q.field for q in decision.questions] == ["claim_paid_last_12_months"]


def test_4401_old_health_no_claim_paid(real):
    decision = ask(real, "4401", claim_paid_last_12_months=False)
    v = values(decision)
    assert v["effective_date"] == date(2026, 11, 24)  # 30 days' notice (04-ב)
    assert v["cancellation_fee"] == 0
    assert v["seniority_months"] == 73
    assert v["seniority_bonus"] == Decimal(288)  # 15% × 160 × 12
    assert v["refund_estimate"] == Decimal(288)
    assert "04-ב" in rule_ids(decision.notes)


def test_4401_rep_does_not_know_leaves_only_the_bonus_unknown(real):
    decision = ask(real, "4401", claim_paid_last_12_months=Unknown("הנציג לא יודע"))
    v = values(decision)
    assert decision.outcome is Outcome.ANSWER
    assert v["effective_date"] == date(2026, 11, 24)
    assert v["cancellation_fee"] == 0
    assert [u.name for u in decision.unknowns] == ["seniority_bonus_rate_percent", "seniority_bonus", "refund_estimate"]


def test_4446_health_from_2024_has_no_30_day_notice(real):
    v = values(ask(real, "4446", claim_paid_last_12_months=False))
    assert v["effective_date"] == date(2026, 10, 31)
    assert v["seniority_bonus_rate_percent"] == 5  # 33 months


def test_4412_debt_above_refund_goes_to_collections(real):
    decision = ask(real, "4412")
    v = values(decision)
    assert decision.outcome is Outcome.ESCALATE
    assert decision.blocks[0].rule_id == "01-§5"
    assert decision.blocks[0].route_to == "מחלקת גבייה"
    assert v["days_since_last_payment"] == 145
    assert v["arrears_debt"] == 580  # paid through 30/06; July to October unpaid: 4 × 145
    assert v["seniority_bonus"] == Decimal("87.00")  # 5% × 145 × 12, 25 months
    assert v["refund_estimate"] == 0  # 0 − 0 + 87 − 580 = −493, floored
    assert decision.value("arrears_debt").is_estimate


def test_4418_multi_policy_customer_is_warned(real):
    assert "04-ג" in rule_ids(ask(real, "4418").notes)


def test_4428_claim_question(real):
    decision = ask(real, "4428", intent=Intent.CLAIM)
    v = values(decision)
    assert decision.outcome is Outcome.ANSWER  # open claims block cancellation, not claim questions
    assert v["open_claims"] == 2
    assert v["acknowledgement_business_days"] == 3
    assert v["assessor_appointment_business_days"] == 10
    assert is_unknown(v["claim_stage"])
    assert is_unknown(v["claim_payment_date"])  # no payment timeline in the procedure
    assert "03-§6" in rule_ids(decision.notes)
    assert "03-§4" in rule_ids(decision.notes)


def test_only_health_policies_ask_about_a_paid_claim(real):
    """02-§3 is a health rule: no other product ever asks the rep, for any intent."""
    for policy_id in [f"{n}" for n in range(4401, 4461)] + ["4471"]:
        product = real.get_policy(policy_id).product
        for intent in (Intent.CANCEL, Intent.REFUND, Intent.CLAIM):
            fields = [q.field for q in ask(real, policy_id, intent=intent).questions]
            if product is not Product.HEALTH or intent is Intent.CLAIM:
                assert "claim_paid_last_12_months" not in fields, (policy_id, intent)


def test_every_active_policy_gets_a_decision(real):
    """No rule crashes on any real policy, for any intent."""
    for policy_id in [f"{n}" for n in range(4401, 4461)] + ["4471"]:
        for intent in (Intent.CANCEL, Intent.REFUND, Intent.CLAIM):
            for answer in (None, True, False, Unknown("x")):
                ask(real, policy_id, intent=intent, claim_paid_last_12_months=answer)


# --- Explanations: the calculation the rep sees ---


def test_4471_calculation_shows_every_input(real):
    decision = ask(real, "4471")
    assert decision.value("seniority_months").explanation == "מ-10/02/2023 עד 25/10/2026 = 44 חודשים מלאים"
    assert decision.value("seniority_bonus").explanation == "10% × 410 ₪ × 12 = 492 ₪"
    assert decision.value("refund_estimate").explanation == (
        "0 (חלק יחסי) − 150 (דמי ביטול) + 492 (מענק ותק) − 0 (חוב) = 342 ₪"
    )


def test_4412_calculation_shows_the_debt(real):
    decision = ask(real, "4412")
    assert decision.value("arrears_debt").explanation == (
        "שולם עד 30/06/2026; 4 חודשים שלא שולמו (07/2026–10/2026, כולל החודש הנוכחי) × 145 ₪ = 580 ₪"
    )
    assert decision.value("refund_estimate").explanation == (
        "0 (חלק יחסי) − 0 (דמי ביטול) + 87 (מענק ותק) − 580 (חוב): הניכויים גבוהים מההחזר (הפרש 493 ₪) → אין החזר, 0 ₪"
    )


def test_unknown_inputs_show_as_question_marks(real):
    decision = ask(real, "4401", claim_paid_last_12_months=Unknown("הנציג לא יודע"))
    assert decision.value("seniority_bonus_rate_percent").explanation is None  # its reason is shown instead
    assert decision.value("seniority_bonus").explanation == "?% × 160 ₪ × 12 = ? ₪"
    assert decision.value("refund_estimate").explanation.endswith("+ ? (מענק ותק) − 0 (חוב) = לא ידוע")


def test_every_calculated_cancellation_value_is_explained(real):
    """Fixed values (e.g. 14 business days) and Unknowns show themselves; everything else explains."""
    for policy_id in ["4471", "4401", "4403", "4408", "4412", "4416", "4421", "4441", "4449"]:
        decision = ask(real, policy_id, claim_paid_last_12_months=False)
        for v in decision.values:
            if v.name != "refund_transfer_business_days" and not is_unknown(v.value):
                assert v.explanation, f"{policy_id}: {v.name} has no explanation"
