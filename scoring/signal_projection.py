from __future__ import annotations
import numpy as np
import pandas as pd
from scoring.entry_score import signal_strength, signal_rank

def _safe_float(value, default=0.0):
    try:
        if pd.isna(value): return default
        return float(value)
    except Exception:
        return default

def _interpret_best_window(current_signal: str, best: dict) -> str:
    best_signal = best["signal_strength"]
    months = int(best["horizon_months"])
    if months == 0:
        return f"Best modeled opportunity is today with a {best_signal} signal."
    if signal_rank(best_signal) > signal_rank(current_signal):
        return f"Modeled conditions improve to {best_signal} in about {months} months."
    return f"No stronger opportunity appears before confidence falls below threshold; best modeled window is {months} months."

def build_signal_projection(model_data: pd.DataFrame, latest: pd.DataFrame, min_confidence: float = 55.0, max_months: int = 36, step_months: int = 6):
    rows = []
    for _, row in latest.iterrows():
        market = row["market"]
        m = model_data[model_data["market"] == market].sort_index().copy()
        current_score = _safe_float(row.get("entry_score"), 50)
        current_confidence = _safe_float(row.get("forecast_confidence_score"), 70)
        current_hpi = _safe_float(row.get("hpi"), np.nan)
        annual_growth = _safe_float(row.get("predicted_12m_growth"), 0)
        current_signal = signal_strength(current_score)

        score_trend_per_quarter = 0.0
        if "entry_score" in m.columns and len(m.dropna(subset=["entry_score"])) >= 5:
            last_scores = m["entry_score"].dropna().tail(5)
            score_trend_per_quarter = (last_scores.iloc[-1] - last_scores.iloc[0]) / max(1, len(last_scores) - 1)

        mortgage_change_4q = _safe_float(row.get("mortgage_change_4q"), 0)
        mortgage_adjustment_per_6m = -2.0 * mortgage_change_4q
        growth_adjustment_per_6m = annual_growth * 100 * 0.30

        for months in range(0, max_months + step_months, step_months):
            if months == 0:
                confidence = current_confidence
                projected_score = current_score
            else:
                confidence = current_confidence - (months / 6) * 4.5
                if confidence < min_confidence:
                    break
                quarters = months / 3
                projected_score = current_score + score_trend_per_quarter * quarters * 0.65 + mortgage_adjustment_per_6m * (months / 6) + growth_adjustment_per_6m * (months / 6)

            projected_score = max(0, min(100, projected_score))
            projected_signal = signal_strength(projected_score)
            projected_hpi = np.nan if np.isnan(current_hpi) else current_hpi * ((1 + annual_growth) ** (months / 12))

            rows.append({
                "market": market,
                "horizon_months": months,
                "horizon_label": "Today" if months == 0 else f"{months} months",
                "projected_hpi": projected_hpi,
                "projected_annual_growth_pct": annual_growth * 100,
                "projected_entry_score": projected_score,
                "signal_strength": projected_signal,
                "signal_rank": signal_rank(projected_signal),
                "forecast_confidence_score": confidence,
                "minimum_confidence_threshold": min_confidence,
                "current_entry_score": current_score,
                "current_signal_strength": current_signal,
                "score_trend_per_quarter": score_trend_per_quarter,
                "mortgage_adjustment_per_6m": mortgage_adjustment_per_6m,
                "growth_adjustment_per_6m": growth_adjustment_per_6m,
            })

    timeline = pd.DataFrame(rows)
    best_rows = []
    if not timeline.empty:
        for market, group in timeline.groupby("market"):
            group = group.sort_values(["signal_rank", "projected_entry_score", "forecast_confidence_score"], ascending=False)
            best = group.iloc[0].to_dict()
            current = timeline[(timeline["market"] == market) & (timeline["horizon_months"] == 0)]
            current_signal = current["signal_strength"].iloc[0] if not current.empty else None
            current_score = current["projected_entry_score"].iloc[0] if not current.empty else np.nan
            best_rows.append({
                "market": market,
                "current_signal_strength": current_signal,
                "current_entry_score": current_score,
                "best_projected_signal_strength": best["signal_strength"],
                "best_projected_entry_score": best["projected_entry_score"],
                "best_entry_window_months": best["horizon_months"],
                "best_entry_window_label": best["horizon_label"],
                "best_window_confidence": best["forecast_confidence_score"],
                "improvement_from_today": best["projected_entry_score"] - current_score,
                "interpretation": _interpret_best_window(current_signal, best),
            })
    return timeline, pd.DataFrame(best_rows)