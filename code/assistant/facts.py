"""The facts of a Decision in plain JSON-able form.

The AnswerWriter gets exactly these, and NumberCheck allows only numbers that
appear in them, so the two always agree on what the answer may contain.
"""

from datetime import date
from decimal import Decimal

from assistant.forms import Decision, Unknown


def decision_facts(decision: Decision) -> dict:
    facts: dict = {"intent": decision.request.intent.value}
    if decision.policy is not None:
        p = decision.policy
        facts["policy"] = {
            "policy_id": p.policy_id,
            "customer_id": p.customer_id,
            "customer_name": p.customer_name,
            "product": p.product.value,
            "status": p.status.value,
            "start_date": p.start_date.isoformat(),
            "monthly_premium": _plain(p.monthly_premium),
            "last_payment_date": p.last_payment_date.isoformat(),
            "open_claims": p.open_claims,
            "notes": p.notes,
        }
    facts["values"] = [
        {
            "name": v.name,
            "value": _plain(v.value),
            **({"unknown_reason": v.value.reason} if isinstance(v.value, Unknown) else {}),
            "rule": v.rule_id,
            "is_estimate": v.is_estimate,
        }
        for v in decision.values
    ]
    facts["notes"] = [{"text": n.text, "rule": n.rule_id} for n in decision.notes]
    return facts


def _plain(value: object) -> object:
    if isinstance(value, Unknown):
        return "UNKNOWN"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    return value
