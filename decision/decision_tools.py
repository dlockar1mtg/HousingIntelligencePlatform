from __future__ import annotations

import numpy as np
import pandas as pd
from scoring.entry_score import signal_strength

def _num(value, default=np.nan):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default

def meaningful_window_summary(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if summary is None or summary.empty:
        return pd.DataFrame()

    for market, group in summary.groupby("market"):
        group = group.sort_values("horizon_months").copy()
        today = group[group["horizon_months"] == 0]
        if today.empty:
            today = group.head(1)
        today = today.iloc[0]

        candidates = group[group["horizon_months"] > 0].copy()
        if candidates.empty:
            continue

        candidates["entry_score_improvement"] = candidates["entry_score_mean"] - today["entry_score_mean"]
        candidates["neutral_prob_improvement"] = candidates["prob_neutral_or_better"] - today["prob_neutral_or_better"]
        candidates["slight_buy_prob_improvement"] = candidates["prob_slight_buy_or_better"] - today["prob_slight_buy_or_better"]

        meaningful = candidates[
            (candidates["entry_score_improvement"] >= 3)
            | (candidates["neutral_prob_improvement"] >= 0.10)
            | (candidates["slight_buy_prob_improvement"] >= 0.05)
        ]

        if not meaningful.empty:
            selected = meaningful.iloc[0]
            reason = "First meaningful improvement"
        else:
            selected = candidates.sort_values(
                ["prob_slight_buy_or_better", "prob_neutral_or_better", "entry_score_mean"],
                ascending=False
            ).iloc[0]
            reason = "No meaningful improvement found; showing best available window"

        rows.append({
            "market": market,
            "current_entry_score": today["entry_score_mean"],
            "current_signal": signal_strength(today["entry_score_mean"]),
            "current_prob_neutral_or_better": today["prob_neutral_or_better"],
            "current_prob_slight_buy_or_better": today["prob_slight_buy_or_better"],
            "first_meaningful_window_months": int(selected["horizon_months"]),
            "first_meaningful_window_label": selected["horizon_label"],
            "projected_entry_score": selected["entry_score_mean"],
            "projected_signal": signal_strength(selected["entry_score_mean"]),
            "projected_prob_neutral_or_better": selected["prob_neutral_or_better"],
            "projected_prob_slight_buy_or_better": selected["prob_slight_buy_or_better"],
            "entry_score_improvement": selected.get("entry_score_improvement", selected["entry_score_mean"] - today["entry_score_mean"]),
            "neutral_prob_improvement": selected.get("neutral_prob_improvement", selected["prob_neutral_or_better"] - today["prob_neutral_or_better"]),
            "slight_buy_prob_improvement": selected.get("slight_buy_prob_improvement", selected["prob_slight_buy_or_better"] - today["prob_slight_buy_or_better"]),
            "selection_reason": reason,
        })

    return pd.DataFrame(rows)

def estimate_score_delta(variable: str, shock: float) -> float:
    if variable == "mortgage_30yr":
        return -shock * 4.0
    if variable == "payment_to_income_ratio":
        return -shock * 120.0
    if variable == "metro_unemployment":
        return -shock * 2.5
    if variable == "realtor_active_listings_yoy":
        return shock * 12.0
    if variable == "predicted_12m_growth":
        return shock * 160.0
    return shock

def sensitivity_analysis(latest: pd.DataFrame, model_data: pd.DataFrame) -> pd.DataFrame:
    rows = []
    levers = [
        ("mortgage_30yr", -1.00, "Mortgage rate falls 1 percentage point"),
        ("mortgage_30yr", -0.50, "Mortgage rate falls 0.5 percentage points"),
        ("mortgage_30yr", 0.50, "Mortgage rate rises 0.5 percentage points"),
        ("realtor_active_listings_yoy", 0.10, "Inventory growth improves by 10 percentage points"),
        ("realtor_active_listings_yoy", 0.20, "Inventory growth improves by 20 percentage points"),
        ("payment_to_income_ratio", -0.02, "Payment-to-income ratio improves by 2 points"),
        ("payment_to_income_ratio", -0.04, "Payment-to-income ratio improves by 4 points"),
        ("metro_unemployment", 0.50, "Unemployment rises 0.5 percentage points"),
        ("metro_unemployment", -0.50, "Unemployment falls 0.5 percentage points"),
        ("predicted_12m_growth", 0.02, "Expected appreciation improves by 2 percentage points"),
        ("predicted_12m_growth", -0.02, "Expected appreciation weakens by 2 percentage points"),
    ]

    for _, row in latest.iterrows():
        market = row["market"]
        base_score = _num(row.get("entry_score"), 50)
        for variable, shock, description in levers:
            if variable not in row.index:
                continue
            delta = estimate_score_delta(variable, shock)
            new_score = max(0, min(100, base_score + delta))
            rows.append({
                "market": market,
                "variable": variable,
                "shock": shock,
                "description": description,
                "base_entry_score": base_score,
                "estimated_entry_score_after_shock": new_score,
                "estimated_score_impact": delta,
                "base_signal": signal_strength(base_score),
                "estimated_signal_after_shock": signal_strength(new_score),
            })

    return pd.DataFrame(rows).sort_values(["market", "estimated_score_impact"], ascending=[True, False])

def trigger_engine(latest: pd.DataFrame) -> pd.DataFrame:
    rows = []
    thresholds = [(85, "Strong Buy"), (72, "Buy"), (60, "Slight Buy"), (48, "Neutral / Fair Value"), (36, "Slight Wait"), (24, "Wait")]

    for _, row in latest.iterrows():
        market = row["market"]
        score = _num(row.get("entry_score"), 50)
        current_signal = signal_strength(score)

        next_threshold = 100
        next_signal = "Maximum"
        for threshold, label in sorted(thresholds, key=lambda x: x[0]):
            if score < threshold:
                next_threshold = threshold
                next_signal = label
                break

        needed = max(0, next_threshold - score)
        rate_now = _num(row.get("mortgage_30yr"))
        drop = needed / 4.0 if needed else 0
        rate_as_of = row.get("rate_features_as_of")
        rate_as_of = rate_as_of if isinstance(rate_as_of, str) and rate_as_of else None
        if rate_now == rate_now:
            rate_text = (f"a {drop:.2f} point mortgage-rate drop (from {rate_now:.2f}% "
                         f"{'on ' + rate_as_of if rate_as_of else 'in the scored quarter'} to about {max(0.0, rate_now - drop):.2f}%)")
        else:
            rate_text = f"a {drop:.2f} point mortgage-rate drop"
        rows.append({
            "market": market,
            "current_entry_score": score,
            "current_signal": current_signal,
            "next_signal_target": next_signal,
            "points_needed": needed,
            "mortgage_rate_drop_needed_estimate": drop,
            "mortgage_rate_now": rate_now,
            "mortgage_rate_as_of": rate_as_of,
            "mortgage_rate_target_estimate": max(0.0, rate_now - drop) if rate_now == rate_now else np.nan,
            "inventory_yoy_improvement_needed_estimate": needed / 12.0 if needed else 0,
            "payment_to_income_improvement_needed_estimate": needed / 120.0 if needed else 0,
            "appreciation_forecast_improvement_needed_estimate": needed / 160.0 if needed else 0,
            "plain_english": (
                f"{market} needs about {needed:.1f} more entry-score points to reach {next_signal}. "
                f"That could roughly come from {rate_text}, "
                f"a {needed/12.0:.1%} inventory-growth improvement, or a combination."
            )
        })

    return pd.DataFrame(rows)

def monitoring_snapshot(latest: pd.DataFrame, output_dir, model_version: str | None = None) -> pd.DataFrame:
    """Compare this run with the previous one. Each snapshot row carries its model_version; changes are
    computed only against a prior run of the same model version, so a model switch (V10 -> V11 -> V11.1)
    is reported as such instead of as large market moves (audit finding 7)."""
    from pathlib import Path
    output_dir = Path(output_dir)
    current_path = output_dir / "v9_monitoring_current_snapshot.csv"
    history_path = output_dir / "v9_monitoring_history.csv"

    cols = [
        "market", "hpi", "hpi_yoy_pct", "mortgage_30yr", "metro_unemployment",
        "zillow_zhvi", "realtor_active_listings", "payment_to_income_ratio",
        "predicted_12m_growth_pct", "entry_score", "entry_signal", "forecast_confidence_score",
    ]
    cols = [c for c in cols if c in latest.columns]
    snapshot = latest[cols].copy()
    snapshot["run_timestamp"] = pd.Timestamp.now()
    if model_version is not None:
        snapshot["model_version"] = model_version

    if current_path.exists():
        prior = pd.read_csv(current_path)
        if model_version is not None:
            prior_version = prior["model_version"] if "model_version" in prior.columns else pd.Series("unknown", index=prior.index)
            prior = prior.assign(model_version=prior_version.fillna("unknown").astype(str))
        compare = snapshot.merge(prior, on="market", how="left", suffixes=("", "_prior"))
        same = (compare["model_version"] == compare["model_version_prior"]) if model_version is not None else pd.Series(True, index=compare.index)
        for metric in ["entry_score", "predicted_12m_growth_pct", "mortgage_30yr", "payment_to_income_ratio"]:
            if metric in compare.columns and f"{metric}_prior" in compare.columns:
                compare[f"{metric}_change_since_last_run"] = (compare[metric] - compare[f"{metric}_prior"]).where(same)
        if model_version is not None:
            compare["comparable_with_prior_run"] = same & compare["model_version_prior"].notna()
    else:
        compare = snapshot.copy()

    snapshot.to_csv(current_path, index=False)

    if history_path.exists():
        history = pd.read_csv(history_path)
        history = pd.concat([history, snapshot], ignore_index=True)
    else:
        history = snapshot.copy()
    history.to_csv(history_path, index=False)

    return compare