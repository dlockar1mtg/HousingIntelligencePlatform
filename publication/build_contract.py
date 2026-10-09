"""Build housing_uip_contract.json from a V10 or V11 run's outputs: the small, versioned file the UIP reads.

Only market-side facts are published. Household figures (financing scenarios, readiness) stay out:
the UIP owns the household plan and will supply it through a profile contract instead.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

CONTRACT_VERSION = "1.3.0"          # 1.1: V11, out-of-sample calibration, walk_forward; 1.2: rates_outlook;
                                    # 1.3: V11.1 audit amendments (rate_features_as_of, data_ages, no timing advice)
STALE_AFTER_MONTHS = 6
KNOWN_ISSUES = {
    "V10": [
        "MARKET_STATE_IS_LAST_QUARTER_WITH_A_REALIZED_TARGET",
        "ALIAS_MATCHING_INCLUDES_UNRELATED_METROS",
        "WALK_FORWARD_VALIDATION_OVERLAPS_TARGETS",
        "CALIBRATION_IS_IN_SAMPLE",
        "OPTIONAL_LAYERS_BACKFILLED",
    ],
    # V11 fixes the five review findings (docs/V11_RESULTS.md); what remains is stated, not fixed.
    "V11": [
        "ENTRY_SCORE_IS_NOT_A_VALIDATED_TIMING_SIGNAL",
        "SHORT_HISTORY_LAYERS_LEFT_OUT_OF_THE_MODEL",
    ],
    # V11.1 fixes the 2026-10-09 audit findings (docs/V11_RESULTS.md, "V11.1 amendments"); V11's stated issues remain.
    "V11.1": [
        "ENTRY_SCORE_IS_NOT_A_VALIDATED_TIMING_SIGNAL",
        "SHORT_HISTORY_LAYERS_LEFT_OUT_OF_THE_MODEL",
    ],
}
WALK_FORWARD_GAP_QUARTERS = {"V10": 0, "V11": 3, "V11.1": 3}
NO_TIMING_ADVICE_VERSIONS = {"V11.1"}


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "item"):
        return _clean(value.item())
    return value


def _read(outputs: Path, name: str) -> pd.DataFrame:
    path = outputs / name
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _months_between(a: str, b: str) -> int:
    da, db = date.fromisoformat(a[:10]), date.fromisoformat(b[:10])
    return (db.year - da.year) * 12 + db.month - da.month


def _calibration(cal) -> dict | None:
    if cal is None:
        return None
    out = {"status": "PASS" if bool(cal["calibration_pass"]) else "FAIL",
           "correlation": _clean(round(float(cal["entry_score_future_growth_correlation"]), 3)),
           "rank_correlation": _clean(round(float(cal["entry_score_future_growth_rank_correlation"]), 3)),
           "in_sample": bool(cal["in_sample"]) if "in_sample" in cal and cal["in_sample"] == cal["in_sample"] else True}
    if not out["in_sample"]:
        out.update(method=str(cal.get("method") or "OUT_OF_SAMPLE"), quarters=int(cal["observations"]),
                   mean_growth_neutral_or_better=_clean(round(float(cal["mean_growth_neutral_or_better"]), 4)),
                   mean_growth_below_neutral=_clean(round(float(cal["mean_growth_below_neutral"]), 4)),
                   pass_marks={"min_quarters": 40, "min_rank_correlation": 0.10, "neutral_or_better_grows_at_least_as_fast": True})
    return out


def build_contract(outputs: Path, *, source_commit: str, run_id: str | None = None, generated_at: str | None = None,
                   model_version: str | None = None) -> dict:
    if model_version is None:
        from config.utils import model_version as configured
        model_version = configured()
    outputs = Path(outputs)
    latest = _read(outputs, "v10_latest_forecast.csv").set_index("market")
    history = pd.read_csv(outputs / "v10_full_history.csv", index_col=0, parse_dates=True)
    ranking = _read(outputs, "v10_market_ranking.csv").set_index("market")
    triggers = _read(outputs, "v10_trigger_conditions.csv")
    best = _read(outputs, "v10_best_entry_windows.csv")
    calib = _read(outputs, "v10_calibration_diagnostics.csv")
    summary = _read(outputs, "v10_monte_carlo_summary.csv")
    alerts = _read(outputs, "v10_alerts.csv")
    freshness = _read(outputs, "v10_data_freshness_report.csv")
    backtest = _read(outputs, "v10_walk_forward_backtest.csv")
    quality_path = outputs / "data_quality.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
    amended = model_version in NO_TIMING_ADVICE_VERSIONS

    data_dates = {str(r["dataset"]): _clean(r.get("latest_observation")) for _, r in freshness.iterrows()} if not freshness.empty else {}
    market_file_dates = dict(data_dates)
    if amended:
        from validation.freshness import assess, census_latest, warnings_for
        census = census_latest(outputs.parent / "inputs" / "census_income.csv") if (outputs.parent / "inputs").exists() else None
        if census:
            market_file_dates["Census ACS income"] = census
        data_dates = {**market_file_dates, **{f"FRED {k}": v for k, v in (quality.get("fred_observations") or {}).items()}}
        run_day = date.fromisoformat((generated_at or datetime.now(timezone.utc).isoformat())[:10])
        file_ages = assess(market_file_dates, run_day)
        data_ages = file_ages + [r for r in quality.get("fred_freshness") or []]
        stale_files = warnings_for(file_ages)
    else:
        data_ages, stale_files = None, []
    latest_input = max((d for d in data_dates.values() if d), default=None)
    markets = []
    for market in latest.index:
        row = latest.loc[market]
        hist = history[history["market"] == market]
        as_of = hist.index.max().date().isoformat()
        rk = ranking.loc[market] if market in ranking.index else pd.Series(dtype=object)
        cal = calib[calib["market"] == market].iloc[0] if not calib.empty and (calib["market"] == market).any() else None
        tr = triggers[triggers["market"] == market].iloc[0] if not triggers.empty and (triggers["market"] == market).any() else None
        bw = best[best["market"] == market].iloc[0] if not best.empty and (best["market"] == market).any() else None
        bt = backtest[backtest["market"] == market] if not backtest.empty else pd.DataFrame()
        path = summary[summary["market"] == market].sort_values("horizon_months") if not summary.empty else pd.DataFrame()
        markets.append({
            "market": market,
            "market_state_as_of": as_of,
            "months_behind_latest_input": _months_between(as_of, latest_input) if latest_input else None,
            "market_regime": _clean(row.get("market_regime")),
            "entry_score": round(float(row["entry_score"]), 3),
            "signal": str(row["entry_signal"]),
            "market_rank": _clean(int(rk["market_rank"])) if "market_rank" in rk else None,
            "market_ranking_score": _clean(round(float(rk["market_ranking_score"]), 3)) if "market_ranking_score" in rk else None,
            "hpi": _clean(float(row["hpi"])), "hpi_yoy": _clean(float(row["hpi_yoy_pct"]) / 100),
            "predicted_12m_growth": round(float(row["predicted_12m_growth_pct"]) / 100, 5),
            "prediction_basis": str(hist["prediction_basis"].iloc[-1]) if "prediction_basis" in hist and len(hist) else "FINAL_MODEL_IN_SAMPLE",
            "realized_growth_for_that_period": _clean(float(hist["target_4q_growth"].iloc[-1])) if len(hist) else None,
            "forecast_confidence": _clean(round(float(row["forecast_confidence_score"]), 2)),
            "walk_forward_mae": _clean(round(float(bt["absolute_error"].mean()), 4)) if len(bt) else None,
            "walk_forward": {"quarters": len(bt), "gap_quarters": WALK_FORWARD_GAP_QUARTERS.get(model_version, 0),
                             "mae": _clean(round(float(bt["absolute_error"].mean()), 4)),
                             "direction_accuracy": _clean(round(float(bt["direction_correct"].mean()), 3)) if "direction_correct" in bt else None}
                            if len(bt) else None,
            "mortgage_30yr": _clean(round(float(row["mortgage_30yr"]), 3)),
            **({"rate_features_as_of": _clean(row.get("rate_features_as_of"))} if amended else {}),
            "zillow_zhvi": _clean(round(float(row["zillow_zhvi"]), 0)) if "zillow_zhvi" in row else None,
            "payment_to_income_ratio": _clean(round(float(row["payment_to_income_ratio"]), 4)) if "payment_to_income_ratio" in row else None,
            "calibration": _calibration(cal),
            # V11.1: no timing advice. The UIP shows best_window as "Best window"; it is null, and the
            # simulated peak is published under a name and note that say what it is.
            **({"simulated_score_peak": None if bw is None else {
                "months": int(bw["best_entry_window_months"]), "expected_entry_score": round(float(bw["best_expected_entry_score"]), 3),
                "prob_neutral_or_better": float(bw["prob_neutral_or_better"]), "timing_advice": False,
                "note": "Scenario output, not timing advice: the Entry Score failed its out-of-sample timing test."}}
               if amended else {}),
            "best_window": None if (bw is None or amended) else {"months": int(bw["best_entry_window_months"]),
                                                    "expected_entry_score": round(float(bw["best_expected_entry_score"]), 3),
                                                    "prob_neutral_or_better": float(bw["prob_neutral_or_better"]),
                                                    "prob_slight_buy_or_better": float(bw["prob_slight_buy_or_better"])},
            "outlook": [{"months": int(r["horizon_months"]), "entry_score_median": round(float(r["entry_score_median"]), 2),
                         "entry_score_p10": round(float(r["entry_score_p10"]), 2), "entry_score_p90": round(float(r["entry_score_p90"]), 2),
                         "growth_p10": round(float(r["growth_p10_pct"]) / 100, 5), "growth_mean": round(float(r["growth_mean_pct"]) / 100, 5),
                         "growth_p90": round(float(r["growth_p90_pct"]) / 100, 5), "mortgage_mean": round(float(r["mortgage_mean"]), 3),
                         **({"growth_median": round(float(r["growth_median_pct"]) / 100, 5),
                             "mortgage_p10": round(float(r["mortgage_p10"]), 3), "mortgage_p50": round(float(r["mortgage_p50"]), 3),
                             "mortgage_p90": round(float(r["mortgage_p90"]), 3)} if amended and "mortgage_p50" in r else {}),
                         "prob_neutral_or_better": float(r["prob_neutral_or_better"])} for _, r in path.iterrows()],
            "trigger": None if tr is None else {"next_signal": str(tr["next_signal_target"]), "points_needed": round(float(tr["points_needed"]), 2),
                                                "mortgage_rate_drop_needed": round(float(tr["mortgage_rate_drop_needed_estimate"]), 2),
                                                **({"mortgage_rate_now": _clean(round(float(tr["mortgage_rate_now"]), 3)),
                                                    "mortgage_rate_as_of": _clean(tr.get("mortgage_rate_as_of"))}
                                                   if amended and "mortgage_rate_now" in tr else {}),
                                                "plain_english": str(tr["plain_english"]), "heuristic": True},
            "alerts": [{"severity": str(a["severity"]), "type": str(a["alert_type"]), "message": str(a["message"])}
                       for _, a in alerts[alerts["market"] == market].iterrows()] if not alerts.empty else [],
        })
    stale = [m["market"] for m in markets if (m["months_behind_latest_input"] or 0) > STALE_AFTER_MONTHS]
    return {
        "contract_version": CONTRACT_VERSION,
        "domain": "housing",
        "model_version": model_version,
        "generated_at_utc": generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_repository": "dlockar1mtg/HousingIntelligencePlatform",
        "source_commit": source_commit,
        "source_run_id": run_id,
        "certification_status": "PROVISIONAL",
        "data_freshness": data_dates,
        "latest_input_observation": latest_input,
        "markets": markets,
        "known_issues": KNOWN_ISSUES.get(model_version, KNOWN_ISSUES["V10"]),
        "warnings": ([f"MARKET_STATE_OLDER_THAN_{STALE_AFTER_MONTHS}_MONTHS: {', '.join(stale)}"] if stale else [])
                    + (list(quality.get("warnings") or []) + stale_files if amended else []),
        **({"data_ages": data_ages, "rate_features_as_of": quality.get("rate_features_as_of")} if amended else {}),
        "rates_outlook": _rates(outputs),
        "household": None,
        "automatic_execution_authorized": False,
    }


def _rates(outputs: Path) -> dict | None:
    """The mortgage-rate outlook (docs/RATES_PLAN.md), when the run produced one."""
    path = Path(outputs) / "rates_outlook.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    test = doc.get("test") or {}
    return {**doc["outlook"], "method": doc.get("method"), "generated_at_utc": doc.get("generated_at_utc"),
            "test": {h: {k: v for k, v in t.items() if k in ("origins_tested", "effective_independent_tests", "first_origin",
                                                               "last_origin", "rules", "published_mae", "rule_chosen_share",
                                                               "band_coverage_10_90", "status", "mae_by_period")}
                     for h, t in test.items()},
            "fomc_sep_context": doc.get("fomc_sep_context")}


def write_package(directory: Path, contract: dict) -> dict:
    """The contract plus a manifest with its digest, the shape the UIP's other domain packages use.

    Audit finding 1: the manifest says validation_status PASS, so nothing is written until the contract has
    passed validation. The package is built in a temporary directory beside the target, validated again as
    a package, and only then moved into place. An invalid contract raises ContractError and leaves no package.
    """
    import shutil
    import tempfile
    from publication.validate_contract import validate_contract, validate_package

    directory = Path(directory)
    validate_contract(contract)
    directory.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{directory.name}.", dir=directory.parent))
    try:
        manifest = _write_files(tmp, contract)
        validate_package(tmp)
        if directory.exists():
            shutil.rmtree(directory)
        tmp.replace(directory)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return manifest


def _write_files(directory: Path, contract: dict) -> dict:
    text = json.dumps(contract, indent=1, sort_keys=False, allow_nan=False) + "\n"
    (directory / "housing_uip_contract.json").write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = {"package_id": f"housing-{contract['generated_at_utc'][:10]}-{digest[:12]}", "domain": "housing",
                "contract_version": contract["contract_version"], "generated_at_utc": contract["generated_at_utc"],
                "repository_commit": contract["source_commit"],
                "files": [{"path": "housing_uip_contract.json", "sha256": digest, "row_count": len(contract["markets"])}],
                "validation_status": "PASS", "certification_status": contract["certification_status"],
                "automatic_execution_authorized": False}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest
