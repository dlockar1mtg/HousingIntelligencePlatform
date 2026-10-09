"""V11.1 amendments from the 2026-10-09 system audit (docs/V11_RESULTS.md, "V11.1 amendments").
One block per finding; synthetic data only, no network."""
import copy
import json
import re
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "baseline" / "v10-2026-09-13" / "outputs"
RATES = json.loads((ROOT / "docs" / "RATES_RESULTS.json").read_text())


@pytest.fixture(autouse=True)
def _v11_1(monkeypatch):
    monkeypatch.setenv("HOUSING_MODEL_VERSION", "V11.1")


# ---------------------------------------------------------------- finding 1: no PASS manifest before validation

def _workflow_jobs(text: str) -> dict[str, str]:
    jobs, name, buf, inside = {}, None, [], False
    for line in text.splitlines():
        if line.startswith("jobs:"):
            inside = True
            continue
        if inside and re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            if name:
                jobs[name] = "\n".join(buf)
            name, buf = line.strip()[:-1], []
        elif inside and name:
            buf.append(line)
    if name:
        jobs[name] = "\n".join(buf)
    return jobs


def test_every_workflow_job_with_a_pipe_runs_explicit_bash():
    checked = 0
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        for job, body in _workflow_jobs(path.read_text()).items():
            if any(re.search(r" \| \S", ln) for ln in body.splitlines() if not ln.strip().startswith("#")):
                checked += 1
                assert re.search(r"defaults:\s*\n\s+run:\s*\n\s+shell: bash\b", body), f"{path.name}:{job} pipes without pipefail"
    assert checked >= 3


def test_production_builds_the_rates_outlook_before_the_forecast():
    text = (ROOT / ".github" / "workflows" / "housing-production.yml").read_text()
    assert text.index("python -m rates.outlook") < text.index("python run_forecast.py")
    assert "python -m validation.freshness" in text


def _v10_contract():
    from publication.build_contract import build_contract
    return build_contract(BASE, source_commit="abc", run_id="1", generated_at="2026-10-09T00:00:00+00:00", model_version="V10")


def test_an_invalid_contract_raises_and_leaves_no_package(tmp_path):
    from publication.build_contract import write_package
    from publication.validate_contract import ContractError
    bad = _v10_contract()
    bad["markets"][0]["entry_score"] = 140
    target = tmp_path / "uip-package"
    with pytest.raises(ContractError):
        write_package(target, bad)
    assert not target.exists() and list(tmp_path.iterdir()) == []


def test_a_valid_contract_is_written_with_a_pass_manifest(tmp_path):
    from publication.build_contract import write_package
    from publication.validate_contract import validate_package
    target = tmp_path / "uip-package"
    (target).mkdir()
    (target / "old.txt").write_text("stale")
    manifest = write_package(target, _v10_contract())
    assert manifest["validation_status"] == "PASS" and validate_package(target)
    assert sorted(p.name for p in target.iterdir()) == ["housing_uip_contract.json", "manifest.json"]
    assert [p.name for p in tmp_path.iterdir()] == ["uip-package"]          # no temporary directory left


def test_publish_uip_exits_non_zero_on_an_invalid_contract(tmp_path, monkeypatch):
    import publish_uip
    from publication.validate_contract import ContractError
    out = tmp_path / "outputs"
    shutil.copytree(BASE, out)
    latest = pd.read_csv(out / "v10_latest_forecast.csv")
    latest.loc[0, "entry_signal"] = "Moon"
    latest.to_csv(out / "v10_latest_forecast.csv", index=False)
    monkeypatch.setenv("HOUSING_MODEL_VERSION", "V10")
    with pytest.raises(ContractError):
        publish_uip.main(["--outputs", str(out), "--package", str(tmp_path / "pkg")])
    assert not (tmp_path / "pkg").exists()


# ---------------------------------------------------------------- finding 2: the scored quarter uses today's rates

def _fred_dir(tmp_path):
    d = tmp_path / "fred"
    d.mkdir()
    weeks = pd.date_range("2024-01-04", "2026-10-08", freq="7D")
    pd.DataFrame({"MORTGAGE30US": np.linspace(6.0, 7.4, len(weeks))}, index=pd.Index(weeks, name="DATE")).to_csv(d / "MORTGAGE30US.csv")
    days = pd.bdate_range("2024-01-01", "2026-10-06")
    pd.DataFrame({"DGS10": np.linspace(4.0, 5.3, len(days))}, index=pd.Index(days, name="DATE")).to_csv(d / "DGS10.csv")
    months = pd.date_range("2024-01-01", "2026-09-01", freq="MS")
    pd.DataFrame({"FEDFUNDS": 4.0}, index=pd.Index(months, name="DATE")).to_csv(d / "FEDFUNDS.csv")
    return d


def test_latest_rate_features_come_from_the_newest_observations(tmp_path, monkeypatch):
    from data_sources import fred_loader as F
    monkeypatch.setattr(F, "SNAPSHOT_DIR", str(_fred_dir(tmp_path)))
    F.reset_run_state()
    r = F.latest_rate_features()
    assert r["mortgage_30yr"]["date"] == "2026-10-08" and r["mortgage_30yr"]["value"] == pytest.approx(7.4)
    assert r["ten_year"]["date"] == "2026-10-06" and 5.25 < r["ten_year"]["value"] < 5.3     # last week's average
    assert r["fed_funds"]["value"] == 4.0
    assert r["mortgage_30yr"]["value_4q_earlier"] < r["mortgage_30yr"]["value_1q_earlier"] < 7.4


def _quarters(n=12, market="Wichita Composite"):
    idx = pd.date_range("2023-09-30", periods=n, freq="QE")
    return pd.DataFrame({"market": market, "mortgage_30yr": 6.4, "ten_year": 4.3, "fed_funds": 4.3,
                         "mortgage_spread": 2.1, "yield_curve": 0.0, "mortgage_change_1q": 0.0, "mortgage_change_4q": 0.0,
                         "ten_year_change_4q": 0.0, "estimated_home_price": 250000.0, "median_household_income": 70000.0,
                         "estimated_monthly_pi_payment": 1250.0, "payment_to_income_ratio": 0.2143,
                         "payment_to_income_change_1yr": 0.0}, index=idx)


RATES_NOW = {"mortgage_30yr": {"date": "2026-10-08", "value": 7.40, "value_1q_earlier": 6.9, "value_4q_earlier": 6.3},
             "ten_year": {"date": "2026-10-06", "value": 5.30, "value_1q_earlier": 5.0, "value_4q_earlier": 4.4},
             "fed_funds": {"date": "2026-09-01", "value": 4.25, "value_1q_earlier": 4.3, "value_4q_earlier": 4.3}}


def test_only_the_scoring_row_gets_todays_rates():
    from features.build_features import apply_current_rates, mortgage_payment
    df = _quarters()
    out = apply_current_rates(df, RATES_NOW)
    pd.testing.assert_frame_equal(out.iloc[:-1].drop(columns="rate_features_as_of"), df.iloc[:-1])
    last = out.iloc[-1]
    assert last["mortgage_30yr"] == 7.40 and last["ten_year"] == 5.30 and last["fed_funds"] == 4.25
    assert last["mortgage_spread"] == pytest.approx(2.10) and last["yield_curve"] == pytest.approx(1.05)
    assert last["mortgage_change_4q"] == pytest.approx(1.10) and last["mortgage_change_1q"] == pytest.approx(0.50)
    pay = float(mortgage_payment(pd.Series([200000.0]), pd.Series([7.40])).iloc[0])
    assert last["estimated_monthly_pi_payment"] == pytest.approx(pay)
    assert last["payment_to_income_ratio"] == pytest.approx(pay / (70000 / 12))
    assert last["payment_to_income_change_1yr"] == pytest.approx(pay / (70000 / 12) - 0.2143)
    assert last["rate_features_as_of"] == "2026-10-08" and out["rate_features_as_of"].iloc[:-1].isna().all()


def test_the_trigger_is_measured_from_the_scored_rate():
    from decision.decision_tools import trigger_engine
    latest = pd.DataFrame([{"market": "Wichita Composite", "entry_score": 44.0, "mortgage_30yr": 7.40, "rate_features_as_of": "2026-10-08"}])
    t = trigger_engine(latest).iloc[0]
    assert t["mortgage_rate_now"] == 7.40 and t["mortgage_rate_target_estimate"] == pytest.approx(7.40 - 1.0)
    assert "from 7.40% on 2026-10-08 to about 6.40%" in t["plain_english"]


# ---------------------------------------------------------------- finding 7 (with 2): alerts and model versions

def _snapshot(rate, version):
    return pd.DataFrame([{"market": "Wichita Composite", "mortgage_30yr": rate, "entry_score": 40.0,
                          "predicted_12m_growth_pct": 1.0, "payment_to_income_ratio": 0.2, "model_version": version}])


def test_a_rate_rise_is_reported_as_a_rise(tmp_path):
    from decision.decision_tools import monitoring_snapshot
    from decision.purchase_optimizer import build_alerts
    _snapshot(6.41, "V11.1").drop(columns=[]).to_csv(tmp_path / "v9_monitoring_current_snapshot.csv", index=False)
    latest = _snapshot(7.40, "V11.1").drop(columns="model_version")
    mon = monitoring_snapshot(latest, tmp_path, model_version="V11.1")
    msgs = build_alerts(latest, mon, None, timing_advice=False)["message"].tolist()
    assert "Mortgage rate changed by +0.99 points (6.41% to 7.40%)." in msgs
    hist = pd.read_csv(tmp_path / "v9_monitoring_history.csv")
    assert hist["model_version"].iloc[-1] == "V11.1"


def test_a_model_switch_is_not_reported_as_a_market_move(tmp_path):
    from decision.decision_tools import monitoring_snapshot
    from decision.purchase_optimizer import build_alerts
    prior = _snapshot(6.41, "V11").assign(entry_score=50.0)
    prior.to_csv(tmp_path / "v9_monitoring_current_snapshot.csv", index=False)
    latest = _snapshot(7.40, "V11.1").drop(columns="model_version")
    alerts = build_alerts(latest, monitoring_snapshot(latest, tmp_path, model_version="V11.1"), None)
    assert set(alerts["alert_type"]) == {"Model Version Change"} and set(alerts["severity"]) == {"Informational"}
    prior.drop(columns="model_version").to_csv(tmp_path / "v9_monitoring_current_snapshot.csv", index=False)  # older files
    alerts = build_alerts(latest, monitoring_snapshot(latest, tmp_path, model_version="V11.1"), None)
    assert "High" not in set(alerts["severity"])


def test_the_unused_modules_are_gone():
    for name in ("scoring/signal_projection.py", "models/recursive_forecast.py", "models/economic_scenarios.py"):
        assert not (ROOT / name).exists()
    assert "V10" not in re.sub(r"export_v10|v10_", "", (ROOT / "run_forecast.py").read_text())


# ---------------------------------------------------------------- finding 3: Monte Carlo rates from the outlook

def test_rate_quantiles_hit_the_published_band():
    from models.monte_carlo_engine import outlook_bands, rate_at_quantile
    bands = outlook_bands(RATES, [0, 6, 12, 18, 24, 30, 36])
    row36 = next(h for h in RATES["outlook"]["horizons"] if h["months"] == 36)
    pts = bands[36]
    assert rate_at_quantile(pts, 0.10) == pytest.approx(row36["p10"]) and rate_at_quantile(pts, 0.5) == pytest.approx(row36["p50"])
    assert rate_at_quantile(pts, 0.90) == pytest.approx(row36["p90"])
    assert rate_at_quantile(pts, 0.0999) == pytest.approx(row36["p10"], abs=0.01)       # continuous into the tails
    assert rate_at_quantile(pts, 0.01) < row36["p10"] and rate_at_quantile(pts, 0.99) > row36["p90"]
    bad = copy.deepcopy(RATES)
    next(h for h in bad["outlook"]["horizons"] if h["months"] == 24).pop("p10")
    with pytest.raises(ValueError, match="24 months"):
        outlook_bands(bad, [0, 24])


def test_random_walk_dispersion_grows_with_sqrt_time():
    from models.monte_carlo_engine import _walk
    rng = np.random.default_rng(0)
    one = np.std([_walk(rng, 0.0, 1.0, 1, True) for _ in range(20000)])
    six = np.std([_walk(rng, 0.0, 1.0, 6, True) for _ in range(20000)])
    assert six / one == pytest.approx(np.sqrt(6), rel=0.05)
    assert np.mean([_walk(rng, 0.1, 0.0, 6, True) for _ in range(10)]) == pytest.approx(0.6)
    a, b = np.random.default_rng(5), np.random.default_rng(5)
    assert _walk(a, 0.2, 0.3, 4, False) == b.normal(0.2, 0.3) * 4                       # V10/V11 path unchanged


class _RateModel:
    """Predicts growth from the mortgage rate, so the simulated growth is checkable."""
    def predict(self, x):
        return (0.10 - 0.01 * x["mortgage_30yr"].to_numpy()).tolist()


def _history(n=40):
    idx = pd.date_range("2016-12-31", periods=n, freq="QE")
    rng = np.random.default_rng(1)
    return pd.DataFrame({"market": "Wichita Composite", "hpi": np.linspace(200, 300, n), "mortgage_30yr": rng.uniform(3, 8, n),
                         "ten_year": rng.uniform(1, 5, n), "fed_funds": rng.uniform(0, 5, n), "hpi_yoy": 0.04,
                         "metro_unemployment": 4.0, "months_supply": 4.0, "predicted_12m_growth": rng.normal(0.03, 0.01, n)}, index=idx)


def test_monte_carlo_rates_follow_the_outlook_and_publish_no_timing_advice():
    from models.monte_carlo_engine import run_monte_carlo_simulation
    hist = _history()
    hist.iloc[-1, hist.columns.get_loc("mortgage_30yr")] = 7.40
    sims, summary, _, best = run_monte_carlo_simulation(hist, ["mortgage_30yr"], _RateModel(), n_simulations=600, rates_outlook=RATES)
    for h in (6, 12, 24, 36):
        row = next(r for r in RATES["outlook"]["horizons"] if r["months"] == h)
        got = sims.loc[sims["horizon_months"] == h, "projected_mortgage_30yr"]
        assert got.quantile(0.5) == pytest.approx(row["p50"], abs=0.15)
        assert got.quantile(0.1) == pytest.approx(row["p10"], abs=0.25) and got.quantile(0.9) == pytest.approx(row["p90"], abs=0.3)
    assert (sims.loc[sims["horizon_months"] == 0, "projected_mortgage_30yr"] == 7.40).all()
    m36 = summary.loc[summary["horizon_months"] == 36].iloc[0]
    assert 6.5 < m36["mortgage_mean"] < 7.8                                   # not the 5.77% the old drift produced
    assert m36["growth_p10_pct"] <= m36["growth_median_pct"] <= m36["growth_p90_pct"]
    assert not best["timing_advice"].any() and "not timing advice" in best["interpretation"].iloc[0]
    low = sims[sims["horizon_months"] == 36].sort_values("projected_mortgage_30yr")
    assert set(low["scenario"].head(100)) == {"Bull"} and set(low["scenario"].tail(100)) == {"Bear"}


# ---------------------------------------------------------------- finding 4: release lags

def test_annual_county_series_are_dated_when_published(tmp_path, monkeypatch):
    from data_sources import fred_loader as F
    d = tmp_path / "fred"
    d.mkdir()
    years = pd.date_range("2015-01-01", "2025-01-01", freq="YS")
    for sid in ("ATNHPIUS20173A", "BPPRIV020173"):
        pd.DataFrame({sid: np.arange(len(years), dtype=float) + 100}, index=pd.Index(years, name="DATE")).to_csv(d / f"{sid}.csv")
    monkeypatch.setattr(F, "SNAPSHOT_DIR", str(d))
    F.reset_run_state()
    composite, _ = F.download_county_layer("Wichita Composite", {"Sedgwick KS": {"fips": "20173", "use_listing_data": False}})
    hpi = composite["composite_county_hpi"].dropna()
    assert hpi.index[0] == pd.Timestamp("2016-06-30")                         # 2015 value, published ~May 2016
    assert hpi.loc["2026-06-30"] == 110.0 and hpi.loc["2026-03-31"] == 109.0  # the 2025 value arrives in Q2 2026
    monkeypatch.setenv("HOUSING_MODEL_VERSION", "V11")
    F.reset_run_state()
    composite, _ = F.download_county_layer("Wichita Composite", {"Sedgwick KS": {"fips": "20173", "use_listing_data": False}})
    assert composite["composite_county_hpi"].dropna().index[0] == pd.Timestamp("2015-03-31")      # V11 unchanged


def test_acs_income_is_dated_when_released(tmp_path, monkeypatch):
    from data_sources import local_files as L
    pd.DataFrame({"date": ["2023-12-31", "2024-12-31"], "market": "Wichita Composite",
                  "median_household_income": [69000.0, 70700.0]}).to_csv(tmp_path / "census_income.csv", index=False)
    monkeypatch.setattr(L, "INPUT_DIR", tmp_path)
    q = L.load_affordability_layer()
    assert q.index.min() == pd.Timestamp("2024-12-31") and q.loc["2025-09-30", "median_household_income"] == 69000.0
    assert q.loc["2025-12-31", "median_household_income"] == 70700.0          # ACS 2024 5-year: December 2025


# ---------------------------------------------------------------- finding 5: missing data is reported or fails the run

def test_missing_series_are_recorded_and_core_series_fail(tmp_path, monkeypatch):
    from data_sources import fred_loader as F
    monkeypatch.setattr(F, "SNAPSHOT_DIR", str(tmp_path))
    F.reset_run_state()
    assert F.fred("WICH620LF", "metro_labor_force") is None
    assert F.MISSING[-1]["series_id"] == "WICH620LF" and F.MISSING[-1]["core"] is False
    with pytest.raises(F.MissingSeriesError, match="MORTGAGE30US"):
        F.fred("MORTGAGE30US", "mortgage_30yr")
    with pytest.raises(F.MissingSeriesError):
        F.download_target_hpi({"target_components": {"A": "ATNHPIUS19124Q", "B": "ATNHPIUS23104Q"},
                               "target_component_weights": {"A": 0.65, "B": 0.35}})


def test_neutral_50_inputs_are_listed():
    from scoring.entry_score import SCORE_INPUTS, neutral_inputs
    row = {c: 1.0 for c in SCORE_INPUTS}
    row.update(market="DFW Composite", realtor_dom_change_1yr=np.nan)
    row.pop("months_supply")
    assert neutral_inputs(pd.DataFrame([row])) == {"DFW Composite": ["months_supply", "realtor_dom_change_1yr"]}


def test_census_refuses_a_year_with_a_county_missing():
    from config.markets import MARKETS
    from data_sources.census_loader import CensusCoverageError, check_county_coverage
    rows = [{"market": m, "county": c, "fips": cfg["fips"], "year": y}
            for m, mc in MARKETS.items() for c, cfg in mc["counties"].items() for y in (2022, 2023, 2024)]
    check_county_coverage(pd.DataFrame(rows))
    short = [r for r in rows if not (r["fips"] == "48231" and r["year"] == 2023)]
    with pytest.raises(CensusCoverageError, match="DFW Composite ACS 2023: 10 of 11 counties"):
        check_county_coverage(pd.DataFrame(short))


# ---------------------------------------------------------------- finding 6: data ages

def test_data_ages_warn_then_fail():
    from validation.freshness import assess, warnings_for
    rows = {r["source"]: r for r in assess({"Zillow ZHVI": "2026-08-31", "Realtor Inventory": "2026-06-01",
                                             "FRED MORTGAGE30US": "2026-08-01", "Census ACS income": None}, date(2026, 10, 9))}
    assert rows["Zillow ZHVI"]["level"] == "OK" and rows["Realtor Inventory"]["level"] == "WARN"
    assert rows["FRED MORTGAGE30US"]["level"] == "ERROR" and rows["Census ACS income"]["level"] == "ERROR"
    w = warnings_for(list(rows.values()))
    assert any(x.startswith("STALE_INPUT: Realtor Inventory newest observation 2026-06-01 is 130 days old") for x in w)


def _v11_1_outputs(tmp_path, rate=7.40, as_of="2026-10-08"):
    out = tmp_path / "outputs"
    shutil.copytree(BASE, out)
    latest = pd.read_csv(out / "v10_latest_forecast.csv")
    latest["mortgage_30yr"] = rate
    latest["rate_features_as_of"] = as_of
    latest.to_csv(out / "v10_latest_forecast.csv", index=False)
    cal = pd.read_csv(out / "v10_calibration_diagnostics.csv")
    cal["in_sample"] = False
    cal.to_csv(out / "v10_calibration_diagnostics.csv", index=False)
    tr = pd.read_csv(out / "v10_trigger_conditions.csv")
    tr["mortgage_rate_now"] = rate
    tr["mortgage_rate_as_of"] = as_of
    tr.to_csv(out / "v10_trigger_conditions.csv", index=False)
    (out / "rates_outlook.json").write_text(json.dumps(RATES))
    (out / "data_quality.json").write_text(json.dumps({
        "missing_series": [{"series_id": "WICH620LF", "name": "metro_labor_force", "core": False, "error": "x"}],
        "fred_observations": {"MORTGAGE30US": "2026-10-08", "ATNHPIUS48620Q": "2026-04-01"},
        "fred_freshness": [{"source": "FRED MORTGAGE30US", "latest_observation": "2026-10-08", "age_days": 1, "warn_days": 14, "max_days": 35, "level": "OK"}],
        "rate_features_as_of": {"mortgage_30yr": {"date": as_of, "value": rate}},
        "warnings": ["MISSING_INPUT_SERIES: WICH620LF (metro_labor_force)"]}))
    return out


def test_v11_1_contract_reports_rates_ages_and_no_timing_advice(tmp_path):
    from publication.build_contract import build_contract
    from publication.validate_contract import ContractError, validate_contract
    c = build_contract(_v11_1_outputs(tmp_path), source_commit="abc", run_id="9", generated_at="2026-11-20T00:00:00+00:00")
    validate_contract(c)
    assert c["model_version"] == "V11.1" and c["contract_version"] == "1.3.0"
    assert c["data_freshness"]["FRED MORTGAGE30US"] == "2026-10-08" and c["latest_input_observation"] == "2026-10-08"
    assert "MISSING_INPUT_SERIES: WICH620LF (metro_labor_force)" in c["warnings"]
    assert any(w.startswith("STALE_INPUT: Zillow ZHVI") for w in c["warnings"])     # 112 days old on 2026-11-20
    assert {r["source"] for r in c["data_ages"]} >= {"Zillow ZHVI", "FRED MORTGAGE30US"}
    for m in c["markets"]:
        assert m["best_window"] is None and m["simulated_score_peak"]["timing_advice"] is False
        assert m["mortgage_30yr"] == 7.40 and m["rate_features_as_of"] == "2026-10-08" and m["trigger"]["mortgage_rate_now"] == 7.40
    for change, message in [(lambda b: b["markets"][0].update(best_window={"months": 36}), "best_window"),
                            (lambda b: b["markets"][0].update(mortgage_30yr=6.415), "differs"),
                            (lambda b: b.pop("rate_features_as_of"), "rate_features_as_of")]:
        bad = copy.deepcopy(c)
        change(bad)
        with pytest.raises(ContractError, match=message):
            validate_contract(bad)


def test_a_scored_rate_that_disagrees_with_the_outlook_is_refused(tmp_path):
    from publication.build_contract import build_contract
    from publication.validate_contract import ContractError, validate_contract
    c = build_contract(_v11_1_outputs(tmp_path, rate=6.415, as_of="2026-10-08"), source_commit="abc", generated_at="2026-10-09T00:00:00+00:00")
    with pytest.raises(ContractError, match="disagrees with the rates outlook"):
        validate_contract(c)


def test_v11_1_refuses_to_run_without_the_rates_outlook(tmp_path, monkeypatch):
    import run_forecast
    monkeypatch.setenv("HOUSING_RATES_OUTLOOK", str(tmp_path / "missing.json"))
    with pytest.raises(RuntimeError, match="rates.outlook"):
        run_forecast.load_rates_outlook()
