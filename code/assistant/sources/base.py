"""The plug socket: what any policy data source must provide (Ronit's requirement #2)."""

from typing import Protocol

from assistant.forms import Policy


class PolicyDataError(ValueError):
    """A policy record exists but can't be read. Raised instead of guessing a value.

    Different from "not found": the rep must hear that the record is broken, not
    that the customer has no policy.
    """


class PolicySource(Protocol):
    """Where policy records come from: the CSV today, the company API later.

    The RuleEngine only knows this interface, so swapping the source doesn't touch it.
    """

    def get_policy(self, policy_id: str) -> Policy | None:
        """The policy with this ID, or None if there is none.

        Raises PolicyDataError if the record exists but can't be read.
        """
        ...

    def get_customer_policies(self, customer_id: str) -> list[Policy]:
        """All of a customer's policies, in any status, ordered by policy ID.

        Raises PolicyDataError if any of them can't be read: the multi-policy rules
        (04-ג) need the complete list, so a partial one would be a wrong answer.
        """
        ...
