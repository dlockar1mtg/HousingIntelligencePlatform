"""Per-source data ages (V11.1 audit amendment, finding 6).

A fail-safe refresh keeps the installed file when a download fails, and an evicted Actions cache falls back
to the 2026-09-13 baseline files, so an input can quietly grow old. Each source has two ages, counted from
its newest observation to the run date:

- `warn_days`: older than this is published in the contract's `warnings` and shown as a ::warning;
- `max_days`: older than this is an ::error and the production run stops before publishing.

The ages allow for each source's normal publication delay (FHFA's quarterly HPI is dated the first day of
its quarter and published about five months later; an ACS 5-year year is released twelve months after it
ends, plus the 12 months until the next one).

Usage in CI: python -m validation.freshness outputs/v10_data_freshness_report.csv [outputs/data_quality.json]
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

# name -> (warn_days, max_days)
MARKET_FILE_AGES = {
    "Zillow ZHVI": (75, 150),
    "Zillow ZORI": (75, 150),
    "Realtor Inventory": (75, 150),
    "Census ACS income": (800, 1100),
}
FRED_AGES = {
    "MORTGAGE30US": (14, 35),
    "DGS10": (10, 30),
    "FEDFUNDS": (70, 130),
    "CPIAUCSL": (75, 130),
}
FRED_QUARTERLY_HPI = (250, 400)
FRED_ANNUAL = (900, 1250)          # annual county HPI and permits (dated 1 January, published ~May next year)
FRED_MONTHLY = (120, 240)


def fred_ages(series_id: str) -> tuple[int, int]:
    if series_id in FRED_AGES:
        return FRED_AGES[series_id]
    if series_id.startswith("ATNHPIUS") and series_id.endswith("Q"):
        return FRED_QUARTERLY_HPI
    if (series_id.startswith("ATNHPIUS") and series_id.endswith("A")) or series_id.startswith("BPPRIV0"):
        return FRED_ANNUAL
    return FRED_MONTHLY


def assess(observations: dict[str, str | None], today: date, kind: dict[str, tuple[int, int]] | None = None) -> list[dict]:
    """One row per source: newest observation, age in days, the two limits and the level (OK/WARN/ERROR).
    A source with no observation date is an ERROR."""
    rows = []
    for name, observed in observations.items():
        warn, limit = (kind or {}).get(name) or MARKET_FILE_AGES.get(name) or fred_ages(name.replace("FRED ", ""))
        if not observed:
            rows.append({"source": name, "latest_observation": None, "age_days": None, "warn_days": warn, "max_days": limit, "level": "ERROR"})
            continue
        age = (today - date.fromisoformat(str(observed)[:10])).days
        level = "ERROR" if age > limit else "WARN" if age > warn else "OK"
        rows.append({"source": name, "latest_observation": str(observed)[:10], "age_days": age, "warn_days": warn,
                     "max_days": limit, "level": level})
    return rows


def warnings_for(rows: list[dict]) -> list[str]:
    """Contract warnings for the sources past their warning age."""
    out = []
    for r in rows:
        if r["level"] == "OK":
            continue
        if r["age_days"] is None:
            out.append(f"STALE_INPUT: {r['source']} has no observation date")
        else:
            out.append(f"STALE_INPUT: {r['source']} newest observation {r['latest_observation']} is {r['age_days']} days old "
                       f"(warn after {r['warn_days']}, limit {r['max_days']})")
    return out


def annotate(rows: list[dict]) -> int:
    """GitHub annotations; returns 1 when any source is past its limit."""
    worst = 0
    for r in rows:
        msg = f"newest {r['latest_observation']}, {r['age_days']} days old (warn after {r['warn_days']}, limit {r['max_days']})"
        if r["level"] == "ERROR":
            print(f"::error title={r['source']}::{msg}")
            worst = 1
        elif r["level"] == "WARN":
            print(f"::warning title={r['source']}::{msg}")
        else:
            print(f"::notice title={r['source']}::{msg}")
    return worst


def census_latest(path: Path) -> str | None:
    """Newest ACS year in the market income file, as its date (e.g. 2024-12-31)."""
    import pandas as pd
    if not Path(path).exists():
        return None
    d = pd.to_datetime(pd.read_csv(path)["date"], errors="coerce").dropna()
    return d.max().date().isoformat() if len(d) else None


def main(argv=None) -> int:
    import pandas as pd
    argv = sys.argv[1:] if argv is None else argv
    today = date.today()
    obs = {}
    report = Path(argv[0]) if argv else Path("outputs/v10_data_freshness_report.csv")
    if report.exists():
        for _, x in pd.read_csv(report).iterrows():
            obs[str(x["dataset"])] = None if pd.isna(x["latest_observation"]) else str(x["latest_observation"])
    obs["Census ACS income"] = census_latest(Path("inputs/census_income.csv"))
    if len(argv) > 1 and Path(argv[1]).exists():
        quality = json.loads(Path(argv[1]).read_text())
        obs.update({f"FRED {k}": v for k, v in (quality.get("fred_observations") or {}).items()})
    return annotate(assess(obs, today))


if __name__ == "__main__":
    raise SystemExit(main())
