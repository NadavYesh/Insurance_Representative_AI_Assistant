"""RuleEngine: turns a Request and the policy data into a Decision. No LLM, no guessing."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from types import MappingProxyType

from assistant.forms import Decision, Intent, Note, Outcome, Policy, Question, Request, UnknownBranchError, Value
from assistant.rules.base import BlockingRule, Case, DecisionTable, NoteRule
from assistant.sources import PolicyDataError, PolicySource


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
        try:
            policy, lookup_problem = self._find_policy(request)
            customer_policies = tuple(self._source.get_customer_policies(policy.customer_id)) if policy else ()
        except PolicyDataError as e:
            # The record exists but is broken: say so, never "not found" or a guess.
            policy, customer_policies = None, ()
            lookup_problem = f"רשומת הפוליסה במערכת פגומה ולא ניתן לענות על סמך הנתונים. יש לדווח לתמיכה. ({e})"
        case = Case(request, policy, customer_policies, self._today)

        # Blocking rules come first and are all checked, so the manager sees every reason.
        blocks = tuple(
            rule.block()
            for rule in self._blocking_rules
            if request.intent in rule.intents
            and (policy is not None or not rule.needs_policy)
            and rule.applies(case)
        )
        if blocks:
            outcome = Outcome.ESCALATE if blocks[0].route_to else Outcome.BLOCKED
            return Decision(request, outcome, policy, blocks=blocks)

        if lookup_problem:
            return Decision(request, Outcome.NEED_INFO, policy, notes=(Note(lookup_problem),))
        assert policy is not None
        if request.intent is Intent.OTHER:
            note = Note("הכלי עונה רק על שאלות ביטול, החזר ותביעות.")
            return Decision(request, Outcome.NEED_INFO, policy, notes=(note,))

        values, questions = self._run_tables(case)
        if questions:
            return Decision(request, Outcome.NEED_INFO, policy, questions=questions)

        case = Case(request, policy, customer_policies, self._today, MappingProxyType(values))
        notes = tuple(
            Note(rule.text, rule.rule_id)
            for rule in self._note_rules
            if request.intent in rule.intents and rule.applies(case)
        )
        return Decision(request, Outcome.ANSWER, policy, values=tuple(values.values()), notes=notes)

    def _find_policy(self, request: Request) -> tuple[Policy | None, str | None]:
        """The policy the request is about, or why it couldn't be pinned down."""
        if request.policy_id:
            policy = self._source.get_policy(request.policy_id)
            if policy is None:
                return None, f"פוליסה {request.policy_id} לא נמצאה במערכת."
            # Mismatch: don't run any rule on what may be the wrong policy.
            if request.customer_id and request.customer_id != policy.customer_id:
                return None, (
                    f"פוליסה {policy.policy_id} שייכת ללקוח {policy.customer_id}, "
                    f"לא ל-{request.customer_id}. יש לוודא את הפרטים."
                )
            return policy, None

        if request.customer_id:
            policies = self._source.get_customer_policies(request.customer_id)
            if not policies:
                return None, f"לקוח {request.customer_id} לא נמצא במערכת."
            if len(policies) > 1:
                ids = ", ".join(p.policy_id for p in policies)
                return None, f"ללקוח {request.customer_id} יש כמה פוליסות ({ids}). על איזו מהן מדובר?"
            return policies[0], None

        return None, "לא צוין מספר פוליסה או מספר לקוח."

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
                    if not row.when(table_case):
                        continue
                except UnknownBranchError as e:
                    values[table.name] = Value(table.name, e.unknown, row.rule_id, table.is_estimate)
                    break

                missing = tuple(q for q in row.asks if getattr(case.request, q.field) is None)
                if missing:
                    return values, missing

                try:
                    result = row.then(table_case)
                except UnknownBranchError as e:
                    result = e.unknown
                values[table.name] = Value(table.name, result, row.rule_id, table.is_estimate)
                break
        return values, ()
