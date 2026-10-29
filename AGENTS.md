
This file provides guidance to Claude Code (claude.ai/code) and/or other ai agents when working with code in this repository.

## Commands (run from `code/`)

- Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- Run: `.venv/bin/python -m assistant "<question>"` (no argument: interactive)
- Unit tests: `.venv/bin/pytest`
- Evals: `.venv/bin/python -m evals.run --offline` (rules only, no key), `.venv/bin/python -m evals.run` (real LLM; `-k <id>` filters, `-v` prints replies)

## What this is

A take-home assignment (AI Builder role). The brief is `instructions/take_home_assignment.pdf` (Hebrew). Build a CLI assistant for insurance customer-service reps. A rep asks a free-text question, for example "customer 4471 wants to cancel, what are they entitled to?". The tool answers by combining that policy's data with the company's policy documents. No UI is needed; a basic CLI is enough.

## Repo layout (paths relative to the repo root, where this file lives)

- `AGENTS.md` (`CLAUDE.md` is a symlink to it) and `README.md` (in English) at the root.
- `docs/`: the other deliverable docs (`QUESTIONS.md`, `DECISIONS.md`, `architecture.md`). `DECISIONS.md` and `QUESTIONS.md` are written in Hebrew.
- `code/`: all source code (`code/config.json`; secrets in `code/.env`, git-ignored).
- `instructions/take_home_assignment.pdf`: the brief (git-ignored).
- `data/`: input data (git-ignored, not committed).

Input data lives in `data/`:
- `policies.csv`: about 60 policies exported as of **2026-10-25**. Treat this as "today" for all date calculations (seniority, arrears, the 14-day cooling-off period, travel start).
- `policies/*.md`: 4 Hebrew procedure docs: cancellation (01), refunds (02), claims handling (03), exceptions (04).

## Architecture
look at @docs/architecture.md

## Client requirements (from "Ronit"; these drive every design decision)

1. **Never invent anything.** If a data point is missing or ambiguous, say so. A wrong answer about money becomes a complaint to the regulator.
2. **The data source must be swappable.** In production, policy data will come from the company's policy-system API, not a CSV. Keep data access behind an interface so moving from CSV to the API doesn't require a rewrite.
3. **Escalation instead of an answer.** Some cases are above the rep's authority, for example cancelling while a claim is open. In those cases the tool must route to a manager rather than decide.
4. **Speed.** The rep is live on the phone, so answers must take well under ~30s.
5. Nice to have: tell the customer *when* their claim will be paid. Note that the claims doc gives SLAs for acknowledgement (3 business days) and assessor appointment (10 business days) but **no payment timeline**. The tool must not invent one.
6. "How will I know it answers correctly?" The submission needs real evaluation (an eval set or tests), not "I tried a few questions."

## Required deliverables (`docs/`, except the README at the root)

- `README.md`: how to run, what's required (keys, models, dependencies), and what works and what doesn't.
- `QUESTIONS.md`: 3–5 questions for Ronit. For each: the assumption made, and what would change if the answer were the opposite.
- `DECISIONS.md`: 2–3 key decisions. For each: the choice and why (tied to Ronit's requirements), what was rejected, and where the AI's suggestion was overruled and why.
- Keep the docs short (about one page total). The reviewer reads the **git log**, so make small, honest, meaningful commits. Time budget: about 4 hours.

## Domain rules that are easy to miss

- `04_חריגים.md` (exceptions) **overrides** the other procedures:
  - Car cancellation fee is a flat ₪150.
  - Health policies started before 2024-01-01 need 30 days' notice.
  - Multi-policy customers lose their 5% discount on the remaining policies when one is cancelled.
  - **Frozen (`מוקפאת`) policies can't be cancelled.**
  - Any mention of a regulator complaint goes straight to the shift manager.
- The rep may give only *estimates* of refunds, never a final amount. The rep never assesses claim approval odds or amounts. The assessor's recommendation can't be disclosed before the written decision.
- Arrears means more than 60 days since `last_payment_date`. The debt is offset against any refund.
- Travel policies can be cancelled only until the day before the trip starts.

## Known data quirks in `policies.csv`

- The file has a UTF-8 BOM, and Hebrew values for `product`, `status` and `notes`.
- Dates are mixed: mostly `YYYY-MM-DD`, some `DD/MM/YYYY` (e.g. policies 4408, 4421, 4449).
- One customer has several policies (C-1072 holds 4418 and 4433), so the multi-policy rules apply. The same name can appear under different customer IDs (e.g. "הילה אברהם").
- Policy 4471 is out of sequence. Several travel policies have future start dates.
- `open_claims` is a count, not a claim stage. The CSV has **no claim status, claim amount, payment-history or prior-claim-payout fields**. Any answer that needs those (e.g. the health seniority bonus, which requires that no claim was paid in the last 12 months) must flag the data as missing.
- The free-text `notes` column can carry facts that matter (e.g. 4440 cancellation date, 4455 freeze).
