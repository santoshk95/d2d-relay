"""Sample estate: the synthetic 17-integration estate from estate.py, no server needed — for demos, UAT and the
end-to-end tests. Runs and seeded risks are generated relative to now, so the trend charts always have data."""
from __future__ import annotations

from . import estate

KIND, LABEL, GROUP = "sample", "Sample estate", "Sample"
AUTH = "none — synthetic data"
DOCS = "Synthetic (DemoData): the 17 integrations of the signed-off design, with seeded failures"
CONFIG: list[dict] = []
SECRETS: list[dict] = []


def discover(cfg: dict, secrets: dict, now: float | None = None) -> dict:
    return estate.discovery(estate.ESTATE, now)
