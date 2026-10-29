"""The shapes rules take. The rulebook fills these in; the RuleEngine runs them."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType

# import the classes that define a claim
from assistant.forms import Block, Intent, Maybe, Policy, Question, Request, UnknownBranchError, Value

ALL_INTENTS = frozenset(Intent)

# A rule's condition: a function of the Case, or plain True for "always".
type Condition = Callable[[Case], bool] | bool


def holds(condition: Condition, case: Case) -> bool:
    return condition if isinstance(condition, bool) else condition(case)


@dataclass(frozen=True)
class Case:
    """
    This class gathers all information to conclude a decision. 
    Everything a rule may look at."""

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
    """
    This is a rule. 
    A stop sign: when it applies, the rep gets a fixed reply instead of an answer."""

    rule_id: str
    reason: str
    applies: Condition
    route_to: str | None = None  # None blocks the request; a name escalates it
    response_time: str | None = None
    say: str | None = None  # what the rep tells the customer, when more than "it's being passed on"
    intents: frozenset[Intent] = ALL_INTENTS
    needs_policy: bool = True  # False for rules that read only the request
    needs_values: bool = False  # True for rules that read table values; checked after the tables run

    def block(self) -> Block:
        return Block(self.rule_id, self.reason, self.route_to, self.response_time, self.say)


@dataclass(frozen=True)
class Row:
    """One line of a decision table. The first row whose `when` holds gives the value.

    `then` is a function of the Case, or the value itself when it is fixed.

    `asks` lists facts from the rep that `then` needs. If the row applies and one of
    them hasn't been asked yet, the engine asks the rep instead of computing.

    `explain` writes out how the value was worked out, with the actual inputs, from
    the Case and the result (e.g. "10% × 410 ₪ × 12 = 492 ₪"). Text when it is fixed.
    """

    rule_id: str
    when: Condition
    then: Callable[[Case], Maybe[object]] | object
    asks: tuple[Question, ...] = ()
    explain: Callable[[Case, object], str] | str | None = None

    def value(self, case: Case) -> Maybe[object]:
        return self.then(case) if callable(self.then) else self.then

    def explanation(self, case: Case, result: object) -> str | None:
        if not callable(self.explain):
            return self.explain
        try:
            return self.explain(case, result)
        except UnknownBranchError:  # can't explain a branch on missing data; the reason is shown instead
            return None


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
    applies: Condition
    intents: frozenset[Intent] = ALL_INTENTS
