from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from assistant.forms import Policy, PolicyStatus, Product
from assistant.sources import PolicyDataError


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


class FakeSource:
    def __init__(self, *policies: Policy, broken: set[str] = frozenset()) -> None:
        self._policies = {p.policy_id: p for p in policies}
        self._broken = broken

    def get_policy(self, policy_id: str) -> Policy | None:
        if policy_id in self._broken:
            raise PolicyDataError(f"policy {policy_id} is broken")
        return self._policies.get(policy_id)

    def get_customer_policies(self, customer_id: str) -> list[Policy]:
        return sorted((p for p in self._policies.values() if p.customer_id == customer_id), key=lambda p: p.policy_id)


class FakeLLM:
    """Returns canned output and records what it was asked."""

    def __init__(self, parsed: dict | None = None, written: str = "") -> None:
        self._parsed = parsed
        self._written = written
        self.calls: list[tuple[str, str]] = []

    def parse(self, instructions: str, text: str, schema: type[BaseModel]) -> BaseModel:
        self.calls.append((instructions, text))
        return schema(**self._parsed)

    def write(self, instructions: str, text: str) -> str:
        self.calls.append((instructions, text))
        return self._written
