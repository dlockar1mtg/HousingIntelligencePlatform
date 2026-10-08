"""V10 vs V11 on identical inputs (docs/V11_PLAN.md). Writes docs/V11_RESULTS.json; prints a summary.

Usage: HOUSING_FRED_SNAPSHOT=data/snapshot/fred python scripts/compare_versions.py
Inputs: the FRED snapshot plus the market files already in inputs/ (the reproduce workflow and the tests
use the baseline files). The Monte Carlo is not run here; it does not affect these measures.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TARGET = "target_4q_growth"
MIN_OOS_QUARTERS = 40


def _f(x, places=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), places)


def wf_metrics(backtest: pd.DataFrame) -> dict:
    out = {}
    for market, g in backtest.groupby("market"):
        out[market] = {"quarters": len(g), "mae": _f(g["absolute_error"].mean()), "direction_accuracy": _f(g["direction_correct"].mean(), 3)}
    return out


def oos_calibration(frame: pd.DataFrame) -> dict:
    """Registered test: point-in-time scores with walk-forward momentum vs realized next-12-month growth."""
    out = {}
    for market, g in frame.dropna(subset=["entry_score", TARGET]).groupby("market"):
        g = g[g["prediction_basis"] == "WALK_FORWARD"]
        lo, hi = g[g["entry_score"] < 48], g[g["entry_score"] >= 48]
        rank = g["entry_score"].rank().corr(g[TARGET].rank()) if len(g) > 2 else float("nan")
        enough = len(g) >= MIN_OOS_QUARTERS
        passes = bool(enough and rank >= 0.10 and not lo.empty and not hi.empty and hi[TARGET].mean() >= lo[TARGET].mean())
        out[market] = {"quarters": len(g), "rank_correlation": _f(rank, 3), "correlation": _f(g["entry_score"].corr(g[TARGET]), 3),
                       "mean_growth_neutral_or_better": _f(hi[TARGET].mean()) if not hi.empty else None,
                       "mean_growth_below_neutral": _f(lo[TARGET].mean()) if not lo.empty else None,
                       "quarters_neutral_or_better": len(hi), "status": "PASS" if passes else "FAIL"}
    return out


def prepare_inputs(version: str) -> None:
    """Same market files for both versions (the baseline's); Census income as each version reads it."""
    import gzip, shutil
    base = ROOT / "baseline" / "v10-2026-09-13" / "inputs"
    inputs = ROOT / "inputs"
    for name in ("zhvi_metro", "zori_metro", "realtor_inventory"):
        with gzip.open(base / f"{name}.csv.gz", "rb") as src, open(inputs / f"{name}.csv", "wb") as dst:
            shutil.copyfileobj(src, dst)
    if version == "V11":
        from data_sources.census_loader import market_income_rows
        hist = pd.read_csv(ROOT / "data" / "snapshot" / "census_income_county_history.csv")
        market_income_rows(hist).to_csv(inputs / "census_income.csv", index=False)
    else:
        shutil.copy(base / "census_income.csv", inputs / "census_income.csv")


def evaluate(version: str) -> dict:
    os.environ["HOUSING_MODEL_VERSION"] = version
    prepare_inputs(version)
    from features.build_features import get_features
    from features.dataset import build_dataset
    from models.housing_model import create_model, walk_forward_validation
    from scoring.entry_score import add_entry_scores, entry_signal

    data, _ = build_dataset()
    features = get_features(data)
    if version == "V11":
        train = data.dropna(subset=[TARGET]).copy()
        scored = data.copy()
    else:
        train = data.dropna(subset=features + [TARGET]).copy()
        scored = train.copy()
    honest = walk_forward_validation(train, features, TARGET, gap=3)
    result = {"version": version, "rows": int(len(scored)), "train_rows": int(len(train)), "features": len(features),
              "walk_forward_honest": wf_metrics(honest)}
    if version == "V10":
        result["walk_forward_as_published"] = wf_metrics(walk_forward_validation(train, features, TARGET, gap=0))
    model = create_model()
    model.fit(train[features], train[TARGET])
    scored["predicted_12m_growth"] = model.predict(scored[features])
    # Published-style latest state.
    published = add_entry_scores(scored, point_in_time=(version == "V11"))
    latest = published.groupby("market").tail(1)
    result["latest"] = {r["market"]: {"quarter": idx.date().isoformat(), "entry_score": _f(r["entry_score"], 2),
                                      "signal": entry_signal(r["entry_score"]), "predicted_12m_growth": _f(r["predicted_12m_growth"]),
                                      "mortgage_30yr": _f(r.get("mortgage_30yr"), 3), "zillow_zhvi": _f(r.get("zillow_zhvi"), 0),
                                      "payment_to_income_ratio": _f(r.get("payment_to_income_ratio"))}
                        for idx, r in latest.iterrows()}
    # The registered out-of-sample calibration, same method for both versions.
    oos = honest.set_index(["market", "date"])["walk_forward_predicted_12m_growth"]
    hist = scored.copy()
    keys = list(zip(hist["market"], hist.index))
    hist["predicted_12m_growth"] = [oos.get(k, np.nan) for k in keys]
    hist["prediction_basis"] = ["WALK_FORWARD" if k in oos.index else "NONE" for k in keys]
    result["calibration_out_of_sample"] = oos_calibration(add_entry_scores(hist, point_in_time=True))
    return result


def main() -> int:
    if not os.environ.get("HOUSING_FRED_SNAPSHOT"):
        sys.exit("set HOUSING_FRED_SNAPSHOT to the FRED snapshot directory")
    kept = {n: (ROOT / "inputs" / n).read_bytes() for n in ("census_income.csv", "census_income_county_detail.csv")}
    results = {"plan": "docs/V11_PLAN.md", "inputs": {"fred_snapshot": os.environ["HOUSING_FRED_SNAPSHOT"],
               "taken_at": (Path(os.environ["HOUSING_FRED_SNAPSHOT"]).parent / "TAKEN_AT").read_text().strip()
               if (Path(os.environ["HOUSING_FRED_SNAPSHOT"]).parent / "TAKEN_AT").exists() else None},
               "V10": evaluate("V10"), "V11": evaluate("V11")}
    for n, data in kept.items():                      # leave the tracked inputs as they were
        (ROOT / "inputs" / n).write_bytes(data)
    out = ROOT / "docs" / "V11_RESULTS.json"
    out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({v: {k: results[v][k] for k in ("latest", "walk_forward_honest", "calibration_out_of_sample")} for v in ("V10", "V11")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
