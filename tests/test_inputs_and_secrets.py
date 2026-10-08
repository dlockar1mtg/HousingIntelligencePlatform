"""No secrets or personal data in the repository; the profile template covers what V10 reads."""
import gzip
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_settings_carry_no_api_key():
    settings = json.loads((ROOT / "config" / "settings.json").read_text())
    assert not [k for k in settings if "key" in k.lower()]


def test_personal_files_are_ignored():
    ignored = (ROOT / ".gitignore").read_text()
    for name in ("inputs/personal_profile.json", "inputs/data_sources_config.json", "inputs/backups/"):
        assert name in ignored


def test_no_tracked_file_looks_like_it_holds_a_key():
    pattern = re.compile(r"(api[_-]?key|token|secret)\"?\s*[:=]\s*\"[A-Za-z0-9]{24,}\"", re.I)
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".json", ".md", ".yml", ".txt"} and ".git" not in path.parts:
            assert not pattern.search(path.read_text(errors="ignore")), path


def test_profile_template_has_every_field_the_optimizer_reads():
    template = json.loads((ROOT / "inputs" / "personal_profile_template.json").read_text())
    code = (ROOT / "decision" / "purchase_optimizer.py").read_text()
    sections = {"income", "cash_assets", "debts", "credit", "home_purchase", "monthly_budget", "preferences", "assumptions", "goals", "profile"}
    assert sections <= set(template)
    fields = set(re.findall(r'\.get\("([a-z_]+)"', code)) - sections
    present = {k for section in template.values() if isinstance(section, dict) for k in section}
    market_side = {"affordability_score", "entry_score", "entry_score_change_since_last_run", "entry_signal", "forecast_confidence_score", "risk_score"}
    assert fields - market_side <= present


def test_baseline_inputs_cover_both_markets():
    base = ROOT / "baseline" / "v10-2026-09-13" / "inputs"
    with gzip.open(base / "zhvi_metro.csv.gz", "rt") as handle:
        names = set(pd.read_csv(handle)["RegionName"])
    assert {"Dallas, TX", "Wichita, KS"} <= names
