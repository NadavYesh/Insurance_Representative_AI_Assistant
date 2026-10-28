"""Forms: plain data classes passed between the workers.

They hold information and do nothing on their own. One worker fills a form in,
the next one reads it. All forms are frozen so no worker can change what an
earlier one wrote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import NoReturn, TypeAlias, TypeVar, Union


# --- UNKNOWN ---------------------------------------------------------------


@dataclass(frozen=True)
class Unknown:
    """A value we don't have. Used instead of guessing (Ronit's requirement #1).

    Anything calculated from an Unknown is that same Unknown, so the reason it is
    missing travels with it: `fee + Unknown("...")` is the Unknown.

    An Unknown can't be used in an `if`. A comparison like `seniority < 12` with an
    unknown seniority gives back the Unknown, and branching on it raises. The rule
    has to handle the missing data on purpose, it can't fall into the else branch.
    """

    reason: str = "" # this is defined in the __init__. the reason an be assigned with the object creation. 

    def __bool__(self) -> NoReturn:
        raise UnknownBranchError(self)

    def _propagate(self, _other: object = None) -> Unknown:
        return self

    __add__ = __radd__ = __sub__ = __rsub__ = _propagate
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _propagate
    __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = _propagate
    __neg__ = __pos__ = __abs__ = _propagate
    __lt__ = __le__ = __gt__ = __ge__ = _propagate  # type: ignore[assignment]

    def __str__(self) -> str:
        return f"UNKNOWN ({self.reason})" if self.reason else "UNKNOWN"


class UnknownBranchError(TypeError):
    """Raised when code branches on an Unknown. Carries the Unknown, so the
    RuleEngine can report the value as unknown, with its reason, instead of crashing."""

    def __init__(self, unknown: Unknown) -> None:
        super().__init__(f"Cannot branch on an unknown value ({unknown.reason or 'no reason given'})")
        self.unknown = unknown


UNKNOWN = Unknown() # a global Unknown object.

# T is a type parameter. either T or Unknown 
#type Maybe[T] = T | Unknown #  uses the type statement added in Python 3.12
T = TypeVar("T")
Maybe: TypeAlias = Union[T, Unknown]


def is_unknown(value: object) -> bool:
    return isinstance(value, Unknown)


# --- Enums -----------------------------------------------------------------
# Values are the Hebrew strings used in the policy data, so a source can parse
# them with `Product("רכב")`.


class Product(StrEnum):
    HEALTH = "בריאות"
    TRAVEL = "נסיעות"
    HOME = "דירה"
    CAR = "רכב"


class PolicyStatus(StrEnum):
    ACTIVE = "פעילה"
    CANCELLED = "מבוטלת"
    FROZEN = "מוקפאת"


class Intent(StrEnum):
    CANCEL = "cancel"
    REFUND = "refund"
    CLAIM = "claim"
    OTHER = "other"  # outside what the tool answers; never guessed into one of the above


class Outcome(StrEnum):
    ANSWER = "answer"  # rules ran; the AnswerWriter phrases the values
    BLOCKED = "blocked"  # not allowed (e.g. frozen policy, trip already started)
    ESCALATE = "escalate"  # above the rep's authority; route to a manager
    NEED_INFO = "need_info"  # no policy ID given, or the policy wasn't found


# --- Policy ----------------------------------------------------------------

_NOT_IN_CSV = "not provided by the policy data source"


@dataclass(frozen=True)
class Policy:
    """One policy's record, as the PolicySource returns it.

    The core fields are always present in the data; a source that can't read one
    (e.g. a malformed date) raises instead of guessing. The last two fields are
    needed by the procedures but don't exist in policies.csv. They stay Unknown
    until a source that has them (the company API) fills them in.
    """

    policy_id: str
    customer_id: str
    customer_name: str
    product: Product
    status: PolicyStatus
    start_date: date
    monthly_premium: Decimal
    last_payment_date: date
    open_claims: int  # a count only; the CSV has no claim stage or amount
    notes: str = ""  # free text; may hold facts that matter (e.g. a freeze request)

    # Refunds 02-§2א: the prorated part depends on what was prepaid past cancellation.
    paid_through: Maybe[date] = Unknown(_NOT_IN_CSV)
    # Claims 03-§3: the rep may tell the customer the current claim stage.
    claim_stage: Maybe[str] = Unknown(_NOT_IN_CSV)


# --- Request ---------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """What the rep asked, as the QuestionReader understood it.

    It holds only what was said. The QuestionReader extracts; it decides nothing.

    Facts the data source doesn't have are asked of the rep (see `Question`). Each
    has three states: None means not asked yet, a value is the rep's answer, and
    Unknown means the rep doesn't know. Anything that depends on an Unknown answer
    stays Unknown; no value is decided from it.
    """

    question: str  # the rep's original text, kept for logs and evals
    intent: Intent
    policy_id: str | None = None
    customer_id: str | None = None
    mentions_regulator: bool = False  # Exceptions 04-ה: goes straight to the shift manager

    # Refunds 02-§3: the health seniority bonus needs "no claim paid in 12 months".
    claim_paid_last_12_months: Maybe[bool] | None = None


@dataclass(frozen=True)
class Question:
    """A fact the engine needs from the rep before it can decide.

    `field` names the Request attribute the answer fills in. The CLI asks `text`,
    stores the answer (or Unknown for "I don't know") and runs the engine again.
    """

    field: str
    text: str  # in Hebrew, shown to the rep
    rule_id: str  # the procedure that needs the fact

    def __post_init__(self) -> None:
        if self.field not in _REP_ANSWERABLE:
            raise ValueError(f"Request has no fact the rep can answer called {self.field!r}")


_REP_ANSWERABLE = {"claim_paid_last_12_months"}


# --- Decision --------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """A blocking rule that matched: why the rep can't answer, and what to do instead."""

    rule_id: str  # procedure reference, e.g. "01-§6", "04-ד"
    reason: str
    route_to: str | None = None  # who takes the case; None means blocked, not escalated
    response_time: str | None = None  # what to promise the customer, e.g. "2 ימי עסקים"


@dataclass(frozen=True)
class Value:
    """One value a decision table worked out, with the row it came from."""

    name: str  # e.g. "cancellation_fee", "effective_date"
    value: Maybe[Decimal | date | int | bool]
    rule_id: str
    is_estimate: bool = False  # Refunds 02-§5: refunds are always estimates


@dataclass(frozen=True)
class Note:
    """Something the rep must tell the customer or know, e.g. a lost discount.

    `rule_id` is None for notes that don't come from a procedure, e.g. "policy not found".
    """

    text: str
    rule_id: str | None = None


@dataclass(frozen=True)
class Decision:
    """What the RuleEngine decided. The only place answers get their facts from.

    `blocks` is in priority order: the first one decides the outcome, the others
    are listed so the manager sees every reason.

    A NEED_INFO decision may carry `questions` for the rep. Once they are answered,
    the engine runs again on the updated Request.
    """

    request: Request
    outcome: Outcome
    policy: Policy | None = None
    blocks: tuple[Block, ...] = ()
    values: tuple[Value, ...] = ()
    notes: tuple[Note, ...] = ()
    questions: tuple[Question, ...] = ()

    def __post_init__(self) -> None:
        if self.questions:
            if self.outcome is not Outcome.NEED_INFO:
                raise ValueError(f"A {self.outcome} decision can't ask the rep questions")
            asked = [q.field for q in self.questions if getattr(self.request, q.field) is not None]
            if asked:
                raise ValueError(f"The rep already answered: {asked}")

        if self.outcome in (Outcome.BLOCKED, Outcome.ESCALATE):
            if not self.blocks:
                raise ValueError(f"A {self.outcome} decision needs at least one block")
            escalates = self.blocks[0].route_to is not None
            if escalates != (self.outcome is Outcome.ESCALATE):
                raise ValueError("The first block's route_to must match the outcome")
        elif self.blocks:
            raise ValueError(f"A {self.outcome} decision can't carry blocks")

        # An escalation may come before any policy lookup (e.g. a regulator mention).
        if self.outcome in (Outcome.ANSWER, Outcome.BLOCKED) and self.policy is None:
            raise ValueError(f"A {self.outcome} decision needs the policy it was made on")

        names = [v.name for v in self.values]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate value names: {names}")

    @property
    def winning_block(self) -> Block | None:
        return self.blocks[0] if self.blocks else None

    def value(self, name: str) -> Value:
        for v in self.values:
            if v.name == name:
                return v
        raise KeyError(name)

    @property
    def unknowns(self) -> tuple[Value, ...]:
        """Values the rep must report as missing rather than answer."""
        return tuple(v for v in self.values if is_unknown(v.value))

    @property
    def rules_used(self) -> tuple[str, ...]:
        """Every procedure reference behind this decision, in order, without repeats."""
        ids = [b.rule_id for b in self.blocks]
        ids += [v.rule_id for v in self.values]
        ids += [n.rule_id for n in self.notes if n.rule_id is not None]
        ids += [q.rule_id for q in self.questions]
        return tuple(dict.fromkeys(ids))
