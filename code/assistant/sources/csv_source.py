"""PolicySource backed by the policies.csv export."""

import csv
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from assistant.dates import parse_date
from assistant.forms import Policy, PolicyStatus, Product
from assistant.sources.base import PolicyDataError

_COLUMNS = (
    "policy_id",
    "customer_id",
    "customer_name",
    "product",
    "start_date",
    "monthly_premium",
    "status",
    "last_payment_date",
    "open_claims",
    "notes",
)


class CsvPolicySource:
    """Loads the whole export once. About 60 rows, so lookups are instant.

    A row that can't be read doesn't stop the others from loading. Asking for that
    policy (or its customer's policies) raises PolicyDataError instead, so one bad
    record never becomes a wrong answer or a "not found". `load_errors` lists every
    such row, for the startup log.
    """

    def __init__(self, path: Path | str) -> None:
        # utf-8-sig strips the BOM the export starts with.
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            missing = [c for c in _COLUMNS if c not in (reader.fieldnames or ())]
            if missing:
                # The whole file is the wrong shape; no row can be trusted.
                raise PolicyDataError(f"{path} is missing columns: {missing}")
            rows = list(reader)

        self._by_id: dict[str, Policy] = {}
        self._bad: dict[str, tuple[str, PolicyDataError]] = {}  # policy_id -> (customer_id, error)
        self.load_errors: list[PolicyDataError] = []

        counts = Counter(_field(row, "policy_id") for row in rows)
        for line, row in enumerate(rows, start=2):  # line 1 is the header
            policy_id = _field(row, "policy_id")
            try:
                if not policy_id:
                    raise PolicyDataError(f"Line {line}: row has no policy ID")
                if counts[policy_id] > 1:
                    # Which copy is right is unknowable, so neither is used.
                    raise PolicyDataError(f"Policy {policy_id} appears {counts[policy_id]} times in the data")
                self._by_id[policy_id] = _parse_row(row, line)
            except PolicyDataError as e:
                self.load_errors.append(e)
                if policy_id:
                    self._bad[policy_id] = (_field(row, "customer_id"), e)

    def get_policy(self, policy_id: str) -> Policy | None:
        policy_id = policy_id.strip()
        if policy_id in self._bad:
            raise self._bad[policy_id][1]
        return self._by_id.get(policy_id)

    def get_customer_policies(self, customer_id: str) -> list[Policy]:
        customer_id = customer_id.strip()
        for bad_customer, error in self._bad.values():
            if bad_customer == customer_id:
                raise error
        return sorted(
            (p for p in self._by_id.values() if p.customer_id == customer_id),
            key=lambda p: p.policy_id,
        )


def _field(row: dict[str | None, str | None], name: str) -> str:
    """A field's text, or "" if the row is too short to have it."""
    return (row.get(name) or "").strip()


def _parse_row(row: dict[str | None, str | None], line: int) -> Policy:
    policy_id = _field(row, "policy_id")
    # DictReader puts surplus fields under None. That means an unquoted comma, most
    # likely in notes, so the notes we'd keep are cut short.
    if row.get(None):
        raise PolicyDataError(f"Policy {policy_id} (line {line}): more fields than columns, notes may be cut off")
    # A short row leaves fields as None. Notes may be empty; nothing else may.
    short = [c for c in _COLUMNS if c != "notes" and not _field(row, c)]
    if short:
        raise PolicyDataError(f"Policy {policy_id} (line {line}): empty fields {short}")

    try:
        open_claims = int(_field(row, "open_claims"))
        monthly_premium = Decimal(_field(row, "monthly_premium"))
        policy = Policy(
            policy_id=policy_id,
            customer_id=_field(row, "customer_id"),
            customer_name=_field(row, "customer_name"),
            product=Product(_field(row, "product")),
            status=PolicyStatus(_field(row, "status")),
            start_date=parse_date(_field(row, "start_date")),
            monthly_premium=monthly_premium,
            last_payment_date=parse_date(_field(row, "last_payment_date")),
            open_claims=open_claims,
            notes=_field(row, "notes"),
        )
    except (ValueError, InvalidOperation) as e:
        raise PolicyDataError(f"Can't read policy {policy_id} (line {line}): {e}") from e

    if open_claims < 0 or not monthly_premium.is_finite() or monthly_premium < 0:
        raise PolicyDataError(f"Policy {policy_id} (line {line}): negative or invalid number")
    return policy
