"""The updater's fail-safe validation, on small synthetic files (no network)."""
import pandas as pd
import pytest

from data_sources import market_file_updater as U


def zillow(tmp_path, names):
    rows = [{"RegionName": n, "2026-06-30": 1.0, "2026-07-31": 2.0} for n in names]
    path = tmp_path / "z.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_valid_zillow_file_passes_and_reports_latest_month(tmp_path):
    info = U._validate_zillow(zillow(tmp_path, ["Wichita, KS", "Dallas, TX"] + [f"M{i}" for i in range(60)]))
    assert info["latest_observation"] == "2026-07-31" and info["wichita_coverage"] == "PASS"


@pytest.mark.parametrize("names,message", [(["Wichita, KS", "Dallas, TX"], "few rows"),
                                           ([f"M{i}" for i in range(60)] + ["Dallas, TX"], "Wichita")])
def test_bad_zillow_files_are_refused(tmp_path, names, message):
    with pytest.raises(ValueError, match=message):
        U._validate_zillow(zillow(tmp_path, names))
