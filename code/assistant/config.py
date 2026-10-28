"""Settings from code/config.json."""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_PATH = Path(__file__).parents[1] / "config.json"


@dataclass(frozen=True)
class Config:
    model_name: str
    policies_csv: Path  # resolved against the config file's folder
    today: date  # "today" for every date rule; the export date of the policy data


def load_config(path: Path = DEFAULT_PATH) -> Config:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Config(
        model_name=raw["model_name"],
        policies_csv=(path.parent / raw["policies_csv"]).resolve(),
        today=date.fromisoformat(raw["today"]),
    )
