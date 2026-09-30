"""Run, spend and time budgets (section 24.4). An unset paid budget disables paid runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from harness import ROOT

BUDGET_PATH = ROOT / "configs" / "budgets.yaml"
_PAID_FIELDS = ("spend_ceiling_usd", "max_fresh_runs", "per_run_deadline_s", "experiment_deadline_s")


@dataclass(frozen=True)
class Budget:
    max_repair_cycles: int
    max_active_attempts: int
    spend_ceiling_usd: float | None
    max_fresh_runs: int | None
    per_run_deadline_s: float | None
    experiment_deadline_s: float | None

    @property
    def paid_runs_allowed(self) -> bool:
        return all(getattr(self, name) is not None for name in _PAID_FIELDS)

    def missing_paid_fields(self) -> list[str]:
        return [name for name in _PAID_FIELDS if getattr(self, name) is None]


def load_budget(path: Path = BUDGET_PATH) -> Budget:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    offline, paid = data["offline"], data["paid"]
    return Budget(
        max_repair_cycles=int(offline["max_repair_cycles"]),
        max_active_attempts=int(offline["max_active_attempts"]),
        **{name: paid.get(name) for name in _PAID_FIELDS},
    )
