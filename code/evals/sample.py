"""Picks the policies for the eval set: 15 of the ~60 in policies.csv (25%).

    python -m evals.sample

Random, with a fixed seed so anyone can rerun it and get the same policies. One part
is not random: the sample must hold the two kinds of policy with rules of their own,
so one of each is drawn first, at random from its own group:

- a travel policy whose trip hasn't started (01-§4: free cancellation until the day before);
- a health policy (02-§3: the rep is asked about paid claims; 04-ב for older ones).

The other 13 are drawn at random from all the rest. The expected results for these
policies are then worked out by hand from the procedures, not by running the tool.
"""

from __future__ import annotations

import csv
import random
from datetime import date

from assistant.__main__ import use_utf8_console
from assistant.config import load_config
from assistant.forms import Policy, Product
from assistant.sources import CsvPolicySource

SEED = 2026
SIZE = 15
TODAY = date(2026, 10, 25)  # the export date, as in cases.yaml


def is_future_trip(p: Policy) -> bool:
    return p.product is Product.TRAVEL and p.start_date > TODAY


def is_health(p: Policy) -> bool:
    return p.product is Product.HEALTH


def sample(policies: list[Policy], seed: int = SEED, size: int = SIZE) -> list[Policy]:
    rng = random.Random(seed)
    picked = []
    for group in (is_future_trip, is_health):
        picked.append(rng.choice(sorted((p for p in policies if group(p)), key=lambda p: p.policy_id)))
    rest = sorted((p for p in policies if p not in picked), key=lambda p: p.policy_id)
    picked += rng.sample(rest, size - len(picked))
    return sorted(picked, key=lambda p: p.policy_id)


def main() -> None:
    use_utf8_console()
    path = load_config().policies_csv
    # The IDs come from the file itself: PolicySource looks policies up, it doesn't list them.
    with open(path, encoding="utf-8-sig", newline="") as f:
        ids = sorted(row["policy_id"].strip() for row in csv.DictReader(f))
    source = CsvPolicySource(path)
    for p in sample([source.get_policy(i) for i in ids]):
        print(p.policy_id, p.product.value, p.status.value, p.start_date, p.last_payment_date, p.open_claims, p.notes)


if __name__ == "__main__":
    main()
