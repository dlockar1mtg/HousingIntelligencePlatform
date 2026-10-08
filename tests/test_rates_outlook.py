"""Mortgage-rate outlook (docs/RATES_PLAN.md): forward rates, point-in-time centers, walk-forward bands."""
import numpy as np
import pandas as pd
import pytest

from rates import outlook as R


def source_from(frame: pd.DataFrame):
    """A fake FRED: monthly first-of-month observations per series."""
    def get(sid):
        if sid not in frame:
            raise KeyError(sid)
        return frame[[sid]].dropna()
    return get


def synthetic(n=600, seed=3, slope=0.08):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1972-01-01", periods=n, freq="MS")
    short = 5 + np.cumsum(rng.normal(0, 0.25, n))
    df = pd.DataFrame(index=idx)
    for sid, m in R.MATURITIES.items():
        df[sid] = short + slope * m
    df[R.MORTGAGE] = df["DGS10"] + 1.7 + rng.normal(0, 0.1, n)
    return df


def test_forward_rate_of_a_flat_curve_is_the_curve():
    row = pd.Series({sid: 4.0 for sid in R.MATURITIES})
    assert R.forward_10y(row, 36) == pytest.approx(4.0, abs=1e-9)


def test_an_upward_curve_implies_higher_rates_later():
    row = pd.Series({sid: 3 + 0.1 * m for sid, m in R.MATURITIES.items()})
    assert R.forward_10y(row, 36) > row["DGS10"]
    assert R.yield_at(row, 13) == pytest.approx(3 + 0.1 * 10 + (0.1 * 20 - 0.1 * 10) * 3 / 10)


def test_a_missing_20_year_uses_the_30_year():
    row = pd.Series({sid: 3 + 0.1 * m for sid, m in R.MATURITIES.items()})
    row["DGS20"] = float("nan")
    assert R.yield_at(row, 13) == pytest.approx(4.0 + (6.0 - 4.0) * 3 / 20)


def test_centers_use_no_later_data():
    df = synthetic()
    data = R.load_monthly(source_from(df))
    t = data.index[300]
    a = R.centers(data, t, 36)
    later = df.copy()
    later.iloc[301:] = later.iloc[301:] + 5.0
    b = R.centers(R.load_monthly(source_from(later)), t, 36)
    assert a == b and set(a) == set(R.RULES)


def test_walk_forward_bands_hold_their_odds_on_a_stationary_world():
    df = synthetic()
    data = R.load_monthly(source_from(df))
    test = R.backtest(data, horizons=(36,))
    t36 = test[36]
    assert t36["origins_tested"] > 200 and t36["first_origin"] == "1985-01"
    assert 0.6 <= t36["band_coverage_10_90"] <= 0.95
    assert set(t36["rules"]) == set(R.RULES)
    out = R.outlook(data, test, horizons=(36,))
    row = out["horizons"][0]
    assert row["p10"] <= row["p50"] <= row["p90"] and row["rule"] in R.RULES
    assert row["month"] == str(data.index[-1] + 36)


def test_too_little_history_falls_back_to_no_change():
    assert R.choose_rule([]) == "NO_CHANGE"
    assert R.band_from([0.1] * 10) is None
