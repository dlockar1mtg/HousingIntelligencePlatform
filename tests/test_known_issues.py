"""Issues found in the migration review (docs/MODEL_LIMITATIONS.md). V10 keeps them on purpose, so the
baseline reproduces; V11 fixes them (docs/V11_PLAN.md, docs/V11_RESULTS.md). Each fix is tested both ways."""
import pandas as pd
import pytest

from data_sources.local_files import market_from_metro_name, market_from_text

UNRELATED = ("Huntsville, AL", "Fort Collins, CO", "Johnson City, TN", "Parkersburg, WV", "Wichita Falls, TX")


def test_v10_alias_matching_still_pulls_unrelated_metros(monkeypatch):
    monkeypatch.setenv("HOUSING_MODEL_VERSION", "V10")
    assert any(market_from_metro_name(name) for name in UNRELATED)


def test_v11_matches_only_the_real_metros(monkeypatch):
    monkeypatch.setenv("HOUSING_MODEL_VERSION", "V11")
    for name in UNRELATED:
        assert market_from_metro_name(name) is None, name
    assert market_from_metro_name("Dallas-Fort Worth-Arlington, TX") == "DFW Composite"
    assert market_from_metro_name("Dallas, TX") == "DFW Composite"
    assert market_from_metro_name("Wichita, KS") == "Wichita Composite"


def test_the_real_metros_are_matched():
    assert market_from_text("Dallas-Fort Worth-Arlington, TX") == "DFW Composite"
    assert market_from_text("Wichita, KS") == "Wichita Composite"


def test_v11_walk_forward_trains_only_on_known_targets(monkeypatch):
    monkeypatch.setenv("HOUSING_MODEL_VERSION", "V11")
    from models import housing_model as M
    seen = []

    class Spy:
        def fit(self, x, y):
            seen.append(x.index.max())
            return self

        def predict(self, x):
            return [0.0] * len(x)
    monkeypatch.setattr(M, "create_model", lambda **k: Spy())
    idx = pd.date_range("2000-03-31", periods=60, freq="QE")
    df = pd.DataFrame({"market": "Wichita Composite", "f": range(60), "target_4q_growth": 0.03}, index=idx)
    out = M.walk_forward_validation(df, ["f"], "target_4q_growth")
    assert len(out) and len(seen) == len(out)
    for (_, row), last_train in zip(out.iterrows(), seen):
        assert last_train <= row["date"] - pd.offsets.QuarterEnd(4)
    assert seen[0] == idx[36]                       # first test quarter idx[40] trains through idx[36]


def test_v11_point_in_time_percentile_uses_no_later_quarter():
    from scoring.entry_score import point_in_time_percentile
    s = pd.Series([1.0, 3.0, 2.0, 5.0, 4.0])
    full = point_in_time_percentile(s)
    for k in range(1, len(s) + 1):
        assert point_in_time_percentile(s.iloc[:k]).iloc[-1] == pytest.approx(full.iloc[k - 1])
