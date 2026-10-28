"""The engine's mechanics, with small made-up rules. The real rulebook is tested separately."""

from datetime import date
from decimal import Decimal

import pytest

from assistant.forms import Intent, Outcome, PolicyStatus, Product, Question, Request, Unknown, is_unknown
from assistant.rules import BlockingRule, DecisionTable, NoteRule, Row, RuleEngine
from tests.helpers import FakeSource, make_policy

TODAY = date(2026, 10, 25)
CLAIM_PAID = Question("claim_paid_last_12_months", "האם שולמה תביעה?", "02-§3")

REGULATOR = BlockingRule(
    "04-ה", "תלונה לרגולטור", lambda c: c.request.mentions_regulator, route_to="מנהל משמרת", needs_policy=False
)
OPEN_CLAIM = BlockingRule(
    "01-§6",
    "תביעה פתוחה",
    lambda c: c.known_policy.open_claims > 0,
    route_to="מנהל משמרת",
    response_time="2 ימי עסקים",
    intents=frozenset({Intent.CANCEL}),
)
FROZEN = BlockingRule("04-ד", "פוליסה מוקפאת", lambda c: c.known_policy.status is PolicyStatus.FROZEN)

FEE = DecisionTable(
    "fee",
    (
        Row("04-א", lambda c: c.known_policy.product is Product.CAR, lambda c: Decimal(150)),
        Row("01-§3", lambda c: True, lambda c: Decimal(50)),
    ),
)
BONUS = DecisionTable(
    "bonus",
    (
        Row(
            "02-§3",
            lambda c: c.known_policy.product is Product.HEALTH,
            lambda c: Decimal(0) if c.request.claim_paid_last_12_months else Decimal(100),
            asks=(CLAIM_PAID,),
        ),
        Row("02-§2", lambda c: True, lambda c: Decimal(100)),
    ),
    is_estimate=True,
)
REFUND = DecisionTable("refund", (Row("02-§2", lambda c: True, lambda c: c.value("bonus") - c.value("fee")),), is_estimate=True)
MULTI = NoteRule("04-ג", "ההנחה תבוטל", lambda c: len(c.customer_policies) > 1)


def engine(*policies, broken=frozenset()):
    return RuleEngine(FakeSource(*policies, broken=broken), [REGULATOR, OPEN_CLAIM, FROZEN], [FEE, BONUS, REFUND], [MULTI], TODAY)


def cancel(**kwargs) -> Request:
    return Request(**({"question": "q", "intent": Intent.CANCEL, "policy_id": "4471"} | kwargs))


def test_answer_runs_tables_in_order():
    decision = engine(make_policy()).decide(cancel())
    assert decision.outcome is Outcome.ANSWER
    assert decision.value("fee").value == 150
    assert decision.value("refund").value == -50
    assert decision.value("refund").is_estimate


def test_first_matching_row_wins():
    decision = engine(make_policy(product=Product.HOME)).decide(cancel())
    assert decision.value("fee").rule_id == "01-§3"


def test_escalation_lists_every_matching_block_in_priority_order():
    decision = engine(make_policy(open_claims=1)).decide(cancel(mentions_regulator=True))
    assert decision.outcome is Outcome.ESCALATE
    assert [b.rule_id for b in decision.blocks] == ["04-ה", "01-§6"]
    assert decision.values == ()


def test_unrouted_block_blocks():
    decision = engine(make_policy(status=PolicyStatus.FROZEN)).decide(cancel())
    assert decision.outcome is Outcome.BLOCKED


def test_rule_limited_to_other_intents_is_skipped():
    decision = engine(make_policy(open_claims=1)).decide(cancel(intent=Intent.REFUND))
    assert decision.outcome is Outcome.ANSWER


def test_regulator_escalates_even_without_a_policy():
    decision = engine().decide(Request(question="q", intent=Intent.OTHER, mentions_regulator=True))
    assert decision.outcome is Outcome.ESCALATE
    assert decision.policy is None


def test_missing_rep_fact_asks_the_rep():
    decision = engine(make_policy(product=Product.HEALTH)).decide(cancel())
    assert decision.outcome is Outcome.NEED_INFO
    assert decision.questions == (CLAIM_PAID,)


def test_rep_dont_know_leaves_only_dependent_values_unknown():
    request = cancel(claim_paid_last_12_months=Unknown("הנציג לא יודע"))
    decision = engine(make_policy(product=Product.HEALTH)).decide(request)
    assert decision.outcome is Outcome.ANSWER
    assert decision.value("fee").value == 50
    assert decision.value("bonus").value == Unknown("הנציג לא יודע")
    assert is_unknown(decision.value("refund").value)  # computed from the unknown bonus
    assert [v.name for v in decision.unknowns] == ["bonus", "refund"]


def test_rep_answer_is_used():
    decision = engine(make_policy(product=Product.HEALTH)).decide(cancel(claim_paid_last_12_months=True))
    assert decision.value("bonus").value == 0


def test_notes_are_added():
    decision = engine(make_policy(), make_policy(policy_id="4472")).decide(cancel())
    assert [n.rule_id for n in decision.notes] == ["04-ג"]


OTHER_CUSTOMER = make_policy(policy_id="5000", customer_id="C-2000")


@pytest.mark.parametrize(
    "request_fields, choices",
    [
        (dict(policy_id="9999"), ()),  # not found: any policy ID
        (dict(policy_id=None), ()),  # nothing given
        (dict(policy_id=None, customer_id="C-0001"), ()),  # customer not found
        (dict(policy_id=None, customer_id="C-1088"), ("4471", "4472")),  # customer has two policies
        (dict(policy_id="4471", customer_id="C-2000"), ("5000",)),  # policy belongs to someone else
    ],
)
def test_lookup_problems_ask_the_rep_which_policy(request_fields, choices):
    decision = engine(make_policy(), make_policy(policy_id="4472"), OTHER_CUSTOMER).decide(cancel(**request_fields))
    assert decision.outcome is Outcome.NEED_INFO
    assert decision.policy is None
    [question] = decision.questions
    assert question.field == "policy_id"
    assert question.choices == choices


def test_unknown_customer_id_does_not_block_a_valid_policy():
    decision = engine(make_policy()).decide(cancel(customer_id="C-0001"))
    assert decision.outcome is Outcome.ANSWER


def test_missing_policy_and_intent_are_asked_together():
    decision = engine(make_policy()).decide(cancel(policy_id=None, intent=Intent.OTHER))
    assert [q.field for q in decision.questions] == ["policy_id", "intent"]


def test_customer_with_one_policy_is_found_by_customer_id():
    decision = engine(make_policy()).decide(cancel(policy_id=None, customer_id="C-1088"))
    assert decision.policy.policy_id == "4471"


def test_broken_record_is_reported_not_guessed():
    decision = engine(broken={"4471"}).decide(cancel())
    assert decision.outcome is Outcome.NEED_INFO
    assert "פגומה" in decision.notes[0].text


def test_other_intent_asks_what_the_customer_wants():
    decision = engine(make_policy()).decide(cancel(intent=Intent.OTHER))
    assert decision.outcome is Outcome.NEED_INFO
    [question] = decision.questions
    assert question.field == "intent"
    assert question.choices == ("ביטול", "החזר", "תביעה")
