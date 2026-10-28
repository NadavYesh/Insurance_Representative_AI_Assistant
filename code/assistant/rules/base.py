"""The shapes rules take. The rulebook fills these in; the RuleEngine runs them."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType

from assistant.forms import Block, Intent, Maybe, Policy, Question, Request, Value

ALL_INTENTS = frozenset(Intent)


@dataclass(frozen=True)
class Case:
    """Everything a rule may look at."""

    request: Request
    policy: Policy | None  # None only for rules with needs_policy=False
    customer_policies: tuple[Policy, ...]  # all of the customer's policies, this one included
    today: date
    values: Mapping[str, Value] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def known_policy(self) -> Policy:
        if self.policy is None:
            raise RuntimeError("Rule needs a policy but ran without one; set needs_policy")
        return self.policy

    def value(self, name: str) -> Maybe[object]:
        """A value an earlier table worked out. Tables run in order, so this one must come later."""
        return self.values[name].value


@dataclass(frozen=True)
class BlockingRule:
    """A stop sign: when it applies, the rep gets a fixed reply instead of an answer."""

    rule_id: str
    reason: str
    applies: Callable[[Case], bool]
    route_to: str | None = None  # None blocks the request; a name escalates it
    response_time: str | None = None
    intents: frozenset[Intent] = ALL_INTENTS
    needs_policy: bool = True  # False for rules that read only the request

    def block(self) -> Block:
        return Block(self.rule_id, self.reason, self.route_to, self.response_time)


@dataclass(frozen=True)
class Row:
    """One line of a decision table. The first row whose `when` holds gives the value.

    `asks` lists facts from the rep that `then` needs. If the row applies and one of
    them hasn't been asked yet, the engine asks the rep instead of computing.
    """

    rule_id: str
    when: Callable[[Case], bool]
    then: Callable[[Case], Maybe[object]]
    asks: tuple[Question, ...] = ()


@dataclass(frozen=True)
class DecisionTable:
    """Works out one value. Rows are read top to bottom, so exceptions sit above the rule."""

    name: str
    rows: tuple[Row, ...]
    intents: frozenset[Intent] = ALL_INTENTS
    is_estimate: bool = False


@dataclass(frozen=True)
class NoteRule:
    """Something the rep must tell the customer whenever it applies, e.g. a lost discount."""

    rule_id: str
    text: str
    applies: Callable[[Case], bool]
    intents: frozenset[Intent] = ALL_INTENTS
