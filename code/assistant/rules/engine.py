"""RuleEngine: turns a Request and the policy data into a Decision."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from types import MappingProxyType

from assistant.forms import Decision, Intent, Note, Outcome, Policy, Question, Request, UnknownBranchError, Value
from assistant.rules.base import BlockingRule, Case, DecisionTable, NoteRule, holds
from assistant.sources import PolicyDataError, PolicySource

# a one class module: a rule engine
class RuleEngine:
    def __init__(
        self,
        source: PolicySource,
        blocking_rules: Sequence[BlockingRule],
        tables: Sequence[DecisionTable],
        note_rules: Sequence[NoteRule],
        today: date,
    ) -> None:
        self._source = source
        self._blocking_rules = tuple(blocking_rules)  # in priority order
        self._tables = tuple(tables)  # in dependency order
        self._note_rules = tuple(note_rules)
        self._today = today

    def decide(self, request: Request) -> Decision:
        '''
        Returbs a decision for a Request type. 
        '''
        try:
            policy, which_policy = self._find_policy(request)
            customer_policies = tuple(self._source.get_customer_policies(policy.customer_id)) if policy else ()
        except PolicyDataError as e:
            # The record exists but is broken: say so, never "not found" or a guess.
            # Asking the rep can't fix it, so this is a note, not a question.
            note = Note(f"רשומת הפוליסה במערכת פגומה ולא ניתן לענות על סמך הנתונים. יש לדווח לתמיכה. ({e})")
            return Decision(request, Outcome.NEED_INFO, notes=(note,))
        case = Case(request, policy, customer_policies, self._today)


        # --------------------------------- BLOCKING PROCEDURE
        # Blocking rules come first and are all checked, so the manager sees every reason.
        blocks = tuple(
            rule.block()
            for rule in self._blocking_rules
            if request.intent in rule.intents and (policy is not None or not rule.needs_policy) and holds(rule.applies, case)
        )
        if blocks: # blocked decision
            outcome = Outcome.ESCALATE if blocks[0].route_to else Outcome.BLOCKED
            return Decision(request, outcome, policy, blocks=blocks)


        # --------------------------------- MISSING INFO: ASK THE REP
        # Which policy, and what the customer wants. Both are asked together, and the
        # pipeline runs the engine again with the rep's answers.
        questions = tuple(q for q in (which_policy, INTENT_QUESTION if request.intent is Intent.OTHER else None) if q)
        if questions:
            return Decision(request, Outcome.NEED_INFO, policy, questions=questions)
        assert policy is not None # unnecessary, really just a guard for crashing if the policy is none even though we made it till here


        # --------------------------------- IF THERE'RE QUESTIONS FROM THE DECISION TABLES
        values, questions = self._run_tables(case)
        if questions:
            return Decision(request, Outcome.NEED_INFO, policy, questions=questions)


        case = Case(request, policy, customer_policies, self._today, MappingProxyType(values))
        notes = tuple(
            Note(rule.text, rule.rule_id)
            for rule in self._note_rules
            if request.intent in rule.intents and holds(rule.applies, case)
        )
        # --------------------------------- FINAL ANSWER
        return Decision(request, Outcome.ANSWER, policy, values=tuple(values.values()), notes=notes)

    def _find_policy(self, request: Request) -> tuple[Policy | None, Question | None]:
        """Finds the policy based on policy id or customer id, or asks the rep which one."""
        # The customer's policies, if a customer ID was given and it exists.
        customer_policies = self._source.get_customer_policies(request.customer_id) if request.customer_id else []

        if request.policy_id:
            policy = self._source.get_policy(request.policy_id)
            if policy is None:
                return None, _ask_policy(f"פוליסה {request.policy_id} לא נמצאה במערכת.", customer_policies)
            # Mismatch with a real customer: don't run any rule on what may be the wrong policy.
            if customer_policies and policy.customer_id != request.customer_id:
                return None, _ask_policy(
                    f"פוליסה {policy.policy_id} שייכת ללקוח {policy.customer_id}, לא ל-{request.customer_id}.",
                    customer_policies,
                )
            return policy, None

        if request.customer_id:
            if not customer_policies:
                return None, _ask_policy(f"לקוח {request.customer_id} לא נמצא במערכת.", [])
            if len(customer_policies) > 1:
                return None, _ask_policy(f"ללקוח {request.customer_id} יש כמה פוליסות.", customer_policies)
            return customer_policies[0], None

        return None, _ask_policy("לא צוין מספר פוליסה או מספר לקוח.", [])

    def _run_tables(self, case: Case) -> tuple[dict[str, Value], tuple[Question, ...]]:
        """Runs each table in order. Stops to ask the rep if a needed fact is missing."""
        values: dict[str, Value] = {}
        for table in self._tables:
            if case.request.intent not in table.intents:
                continue
            table_case = Case(case.request, case.policy, case.customer_policies, case.today, MappingProxyType(dict(values)))
            for row in table.rows:
                # A row that can't tell whether it applies, or can't compute, because it
                # branched on an Unknown makes the value Unknown, with that reason.
                try:
                    if not holds(row.when, table_case):
                        continue
                except UnknownBranchError as e:
                    values[table.name] = Value(table.name, e.unknown, row.rule_id, table.is_estimate)
                    break

                missing = tuple(q for q in row.asks if getattr(case.request, q.field) is None)
                if missing:
                    return values, missing

                try:
                    result = row.value(table_case)
                except UnknownBranchError as e:
                    result = e.unknown
                values[table.name] = Value(table.name, result, row.rule_id, table.is_estimate)
                break
        return values, ()


INTENT_QUESTION = Question(
    "intent",
    "הכלי עונה על ביטול, החזר ותביעות. על מה הלקוח שואל?",
    choices=("ביטול", "החזר", "תביעה"),
)


def _ask_policy(problem: str, options: Sequence[Policy]) -> Question:
    """Asks which policy. With options (the customer's policies), only those are accepted."""
    if not options:
        return Question("policy_id", f"{problem} מה מספר הפוליסה?")
    listed = ", ".join(f"{p.policy_id} ({p.product})" for p in options)
    return Question("policy_id", f"{problem} על איזו פוליסה מדובר? {listed}", choices=tuple(p.policy_id for p in options))
