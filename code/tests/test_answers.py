import pytest

from assistant.answers import hint, parse_answer
from assistant.forms import Intent, Question, is_unknown

CLAIM_PAID = Question("claim_paid_last_12_months", "?", "02-§3")
ANY_POLICY = Question("policy_id", "?")
TWO_POLICIES = Question("policy_id", "?", choices=("4418", "4433"))
INTENT = Question("intent", "?", choices=("ביטול", "החזר", "תביעה"))


@pytest.mark.parametrize("text, expected", [("כן", True), (" Yes ", True), ("לא", False), ("n", False)])
def test_yes_no(text, expected):
    assert parse_answer(CLAIM_PAID, text) is expected


@pytest.mark.parametrize("text", ["לא יודע", "לא  יודעת", "?", "IDK"])
def test_dont_know_is_unknown(text):
    assert is_unknown(parse_answer(CLAIM_PAID, text))


@pytest.mark.parametrize(
    "question, text, expected",
    [
        (ANY_POLICY, "4471", "4471"),
        (ANY_POLICY, "פוליסה 4471", "4471"),
        (ANY_POLICY, "447", None),  # too short
        (ANY_POLICY, "44711", None),  # too long
        (ANY_POLICY, "4471 או 4472", None),  # ambiguous
        (TWO_POLICIES, "4433", "4433"),
        (TWO_POLICIES, "4471", None),  # not one of the customer's policies
    ],
)
def test_policy_id(question, text, expected):
    assert parse_answer(question, text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [("ביטול", Intent.CANCEL), ("לבטל", Intent.CANCEL), ("החזר", Intent.REFUND), ("Claim", Intent.CLAIM), ("כתובת", None)],
)
def test_intent(text, expected):
    assert parse_answer(INTENT, text) == expected


def test_invalid_yes_no():
    assert parse_answer(CLAIM_PAID, "אולי") is None


def test_hint_lists_choices():
    assert hint(TWO_POLICIES) == "4418 / 4433"
    assert hint(CLAIM_PAID) == "כן / לא / לא יודע"
