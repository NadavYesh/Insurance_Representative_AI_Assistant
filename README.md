# Rep assistant

A CLI for insurance customer-service reps. The rep types a free-text question
(Hebrew or English), for example `לקוח 4471 רוצה לבטל, מה מגיע לו?`. The tool answers
from that policy's data and the company's procedures. If a case is above the rep's
authority, it routes it to a manager instead of answering.

## Requirements

- Python 3.12+
- An OpenAI API key in `code/.env`: `OPEN_AI_API_KEY=...` (`OPENAI_API_KEY` also works)
- The input data in `data/` (`policies.csv` and `policies/*.md`), which is not committed
- `code/config.json`: the model (`gpt-4.1-mini`), the CSV path, and the date the tool treats as "today"

## Setup and run

```bash
cd code
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python -m assistant "לקוח 4471 רוצה לבטל, מה מגיע לו?"   # one question
.venv/bin/python -m assistant                                      # interactive; empty line exits
```

When something is missing, the tool asks the rep a follow-up question in the same
conversation, so the rep doesn't have to ask again from the start:

- which policy, when the customer has several (only their policy IDs are accepted);
- the policy number, when none was given or it wasn't found;
- whether the question is about a cancellation, a refund or a claim, when that's unclear;
- for some health policies, whether a claim was paid in the last 12 months
  (`כן` / `לא` / `לא יודע`, i.e. yes / no / don't know).

Answers are checked by code, not the model; an invalid one is asked again. An empty
line skips the question, and the tool says what's missing.

## Tests and evals

```bash
.venv/bin/pytest                         # unit tests: every rule, the engine, the workers (no LLM)
.venv/bin/python -m evals.run --offline  # 32 rep questions against the rules (no LLM, no key)
.venv/bin/python -m evals.run            # the same questions end to end with the real model
```

`evals/cases.yaml` holds rep questions with expected results worked out by hand from the
procedures. Each case checks:

- what the model extracted from the question;
- the outcome (answer, blocked, escalate, or missing info) and the deciding rule;
- every calculated value;
- that each required note appears in the answer;
- text the answer must or must not contain (e.g. an amount that must not be given);
- that it answered within 30 seconds.

Latest full run: 32/32 cases passed, 21/21 written answers passed the number check,
median 2.9s, max 5.2s. Time the rep spends answering a follow-up question isn't counted.

## How it works

The LLM is used twice: to read the question into a fixed form, and to word the answer.
Everything in between is plain code: finding the policy, blocking rules, calculations
(the rulebook in `code/assistant/rules/rulebook.py`, each rule cites its procedure section).

- **Escalations and blocks** use fixed wording, with no LLM.
- **Every number** in a written answer is checked against the calculated values. If one
  doesn't match, the tool shows a plain list of the values instead.
- **Notes the rep must pass on** are added by code, word for word.
- **The full calculation** is added by code at the bottom of every answer: each value
  with its inputs and the rule behind it (e.g. `0 (חלק יחסי) − 150 (דמי ביטול) + 492
  (מענק ותק) − 0 (חוב) = 342 ₪`), so the rep can check it by eye. Each rule writes
  its own explanation, so the explanation can't drift from what was actually computed.

See [`architecture.md`](docs/architecture.md) and [`DECISIONS.md`](docs/DECISIONS.md).

## What works

- Cancellation and refund questions:
  - cancellation date (including 30 days' notice for older health policies, and immediate cancellation in the cooling-off period);
  - cancellation fee (including the flat ₪150 car fee);
  - seniority bonus and refund estimate, always marked as an estimate.
- Escalation to the shift manager:
  - a regulator complaint is mentioned (also detected by keywords, so it doesn't depend on the model);
  - cancelling a policy with an open claim.
- Blocks:
  - frozen policy;
  - trip already started;
  - policy already cancelled.
- Warnings:
  - the multi-policy discount is lost;
  - the customer is in arrears;
  - a written cancellation request is required.
- Claim questions:
  - service times (acknowledgement in 3 business days, assessor in 10);
  - required documents for each product;
  - what may not be disclosed.
- Missing information is asked for in the same conversation (see above). A broken data
  row is reported, never guessed around.

## What doesn't (by design: the data isn't there)

- **Claim payment date and claim stage.** The procedure gives no payment timeline, and
  the CSV only counts open claims. The answer says these are unknown.
- **Debt amount for customers in arrears, and the amount paid in the cooling-off period.**
  Not in the data, so the refund is shown as unknown rather than guessed.
- **Prepaid premium.** The CSV doesn't say how far ahead a customer has paid. The tool
  assumes the last payment covers its own month, and says so.
- **Refunds outside a cancellation** (double charges, reduced cover) aren't handled.
- **The written cancellation request** is assumed to arrive today.

These are the open questions for the client in [`QUESTIONS.md`](docs/QUESTIONS.md).
