"""The facts of a Decision in plain JSON-able form.

The AnswerWriter gets exactly these, and NumberCheck allows only numbers that
appear in them, so the two always agree on what the answer may contain.
"""

from datetime import date
from decimal import Decimal

from assistant.forms import Decision, Unknown

# How each rulebook value is called in Hebrew, for the writer and the plain answer.
LABELS = {
    "cooling_off": "בתקופת התחרטות",
    "seniority_months": "ותק בחודשים",
    "effective_date": "מועד כניסת הביטול לתוקף",
    "cancellation_fee": "דמי ביטול (₪)",
    "seniority_bonus_rate_percent": "שיעור מענק ותק (%)",
    "seniority_bonus": "מענק ותק (₪)",
    "prorated_premium": "החזר החלק היחסי של הפרמיה (₪)",
    "days_since_last_payment": "ימים מאז התשלום האחרון",
    "arrears_debt": "חוב פיגורים (₪)",
    "refund_estimate": "החזר משוער (₪)",
    "refund_transfer_business_days": "ההחזר מועבר תוך (ימי עסקים)",
    "open_claims": "תביעות פתוחות",
    "claim_stage": "שלב הטיפול בתביעה",
    "acknowledgement_business_days": "אישור קבלת תביעה תוך (ימי עסקים)",
    "assessor_appointment_business_days": "מינוי מעריך תוך (ימי עסקים)",
    "claim_payment_date": "מועד תשלום התביעה",
}


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
            "label": LABELS.get(v.name, v.name),
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
