from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from config.utils import load_settings
from scoring.entry_score import signal_strength, signal_rank

TARGET = "target_4q_growth"

# These are the core variables V7 tries to forecast recursively.
# If a variable is not present in the dataset, it is skipped safely.
RECURSIVE_TARGETS = [
    "hpi",
    "mortgage_30yr",
    "ten_year",
    "fed_funds",
    "inflation_yoy",
    "metro_unemployment",
    "metro_payroll_growth_yoy",
    "metro_labor_force_growth_yoy",
    "months_supply",
    "realtor_active_listings",
    "realtor_median_listing_price",
    "realtor_median_days_on_market",
    "realtor_price_reduction_share",
    "zillow_zhvi",
    "zillow_zori",
    "median_household_income",
]

def create_recursive_model() -> RandomForestRegressor:
    settings = load_settings().get("model", {})
    return RandomForestRegressor(
        n_estimators=settings.get("n_estimators", 900),
        max_depth=settings.get("max_depth", 7),
        min_samples_leaf=settings.get("min_samples_leaf", 3),
        random_state=settings.get("random_state", 42),
    )

def _safe_num(value, default=np.nan):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default

def _trend(series: pd.Series, periods: int = 4, default: float = 0.0) -> float:
    s = series.dropna()
    if len(s) <= periods:
        return default
    return (s.iloc[-1] - s.iloc[-periods-1]) / periods

def build_recursive_features(df: pd.DataFrame) -> list[str]:
    candidates = [
        "hpi_qoq", "hpi_yoy", "hpi_3yr_growth", "hpi_5yr_growth",
        "mortgage_30yr", "mortgage_spread", "yield_curve",
        "mortgage_change_1q", "mortgage_change_4q",
        "ten_year", "ten_year_change_4q", "fed_funds",
        "inflation_yoy", "inflation_trend",
        "national_unemployment", "national_payroll_growth_yoy",
        "consumer_sentiment", "consumer_sentiment_change",
        "housing_starts", "starts_growth_yoy",
        "building_permits", "permits_growth_yoy",
        "months_supply", "months_supply_change_1yr",
        "metro_unemployment", "metro_unemployment_change_1yr",
        "metro_payroll_growth_yoy", "metro_labor_force_growth_yoy",
        "composite_county_hpi_yoy", "composite_active_listings_yoy",
        "composite_listing_price_yoy", "composite_county_permits_yoy",
        "zillow_zhvi_yoy", "zillow_zori_yoy",
        "rent_to_price_ratio", "rent_to_price_ratio_change_1yr",
        "realtor_active_listings_yoy", "realtor_new_listings_yoy",
        "realtor_listing_price_yoy", "realtor_dom_change_1yr",
        "realtor_price_reduction_change_1yr",
        "estimated_monthly_pi_payment",
        "payment_to_income_ratio", "payment_to_income_change_1yr",
        "entry_score",
    ]
    return [c for c in candidates if c in df.columns and df[c].isna().mean() <= 0.40]

def train_variable_models(model_data: pd.DataFrame, features: list[str]) -> dict:
    """
    Trains one model per recursive target.

    Each target predicts the 2-quarter-ahead value because the timeline advances
    in six-month increments.
    """
    models = {}

    for target in RECURSIVE_TARGETS:
        if target not in model_data.columns:
            continue

        target_future = f"future_{target}_2q"
        temp = model_data.copy()
        temp[target_future] = temp.groupby("market")[target].shift(-2)

        train = temp.dropna(subset=features + [target_future])
        if len(train) < 40:
            continue

        model = create_recursive_model()
        model.fit(train[features], train[target_future])

        # Historical residuals give us a rough uncertainty estimate.
        pred = model.predict(train[features])
        residuals = train[target_future].values - pred
        mae = np.mean(np.abs(residuals)) if len(residuals) else np.nan
        std = np.std(residuals) if len(residuals) else np.nan

        models[target] = {
            "model": model,
            "mae": mae,
            "std": std,
            "training_rows": len(train),
        }

    return models

def recompute_projected_features(state: pd.Series, previous_state: pd.Series | None = None) -> pd.Series:
    """
    Recomputes derived features from projected raw variables.
    This intentionally focuses on features used by entry scoring and readability.
    """
    s = state.copy()

    hpi = _safe_num(s.get("hpi"))
    prev_hpi = _safe_num(previous_state.get("hpi")) if previous_state is not None else np.nan

    if not np.isnan(hpi) and not np.isnan(prev_hpi) and prev_hpi != 0:
        s["hpi_qoq"] = hpi / prev_hpi - 1

    if "hpi" in s.index:
        # Keep prior YoY as a fallback; true recursive YoY is handled below from state history in the main loop.
        pass

    mortgage = _safe_num(s.get("mortgage_30yr"))
    ten_year = _safe_num(s.get("ten_year"))
    fed_funds = _safe_num(s.get("fed_funds"))

    if not np.isnan(mortgage) and not np.isnan(ten_year):
        s["mortgage_spread"] = mortgage - ten_year
    if not np.isnan(ten_year) and not np.isnan(fed_funds):
        s["yield_curve"] = ten_year - fed_funds

    if "zillow_zhvi" in s.index and "zillow_zori" in s.index:
        zhvi = _safe_num(s.get("zillow_zhvi"))
        zori = _safe_num(s.get("zillow_zori"))
        if not np.isnan(zhvi) and zhvi > 0 and not np.isnan(zori):
            s["rent_to_price_ratio"] = (zori * 12) / zhvi

    if "estimated_home_price" in s.index and "mortgage_30yr" in s.index:
        # Use existing estimated monthly payment if present; actual payment recomputation is handled by feature module in core model,
        # but for projection purposes this approximation keeps affordability moving.
        home_price = _safe_num(s.get("zillow_zhvi", s.get("estimated_home_price", np.nan)))
        if not np.isnan(home_price):
            s["estimated_home_price"] = home_price

    return s

def _historical_percentile(projected_value: float, hist: pd.Series, higher_is_better: bool) -> float:
    h = hist.dropna()
    if len(h) == 0 or pd.isna(projected_value):
        return 50.0
    percentile = (h <= projected_value).mean() * 100
    return percentile if higher_is_better else 100 - percentile

def compute_projected_entry_score(projected: pd.Series, history: pd.DataFrame, predicted_growth: float) -> dict:
    """
    Computes the seven-component entry score for a projected state using historical percentiles.
    """
    def score(col, higher=True):
        if col not in history.columns:
            return 50.0
        return _historical_percentile(_safe_num(projected.get(col)), history[col], higher)

    price_momentum_score = _historical_percentile(predicted_growth, history.get("predicted_12m_growth", pd.Series(dtype=float)), True)

    valuation_score = (
        score("hpi_yoy", False) * 0.20
        + score("hpi_5yr_growth", False) * 0.20
        + score("composite_listing_price_yoy", False) * 0.20
        + score("zillow_zhvi_yoy", False) * 0.20
        + score("realtor_listing_price_yoy", False) * 0.20
    )

    supply_score = (
        score("months_supply", True) * 0.20
        + score("composite_active_listings_yoy", True) * 0.25
        + score("realtor_active_listings_yoy", True) * 0.25
        + score("realtor_dom_change_1yr", True) * 0.15
        + score("composite_county_permits_yoy", True) * 0.15
    )

    economy_score = (
        score("metro_unemployment", False) * 0.35
        + score("metro_payroll_growth_yoy", True) * 0.35
        + score("metro_labor_force_growth_yoy", True) * 0.30
    )

    mortgage_score = (
        score("mortgage_30yr", False) * 0.45
        + score("mortgage_change_4q", False) * 0.35
        + score("mortgage_spread", False) * 0.20
    )

    affordability_score = (
        score("payment_to_income_ratio", False) * 0.70
        + score("payment_to_income_change_1yr", False) * 0.30
    )

    risk_score = (
        score("hpi_volatility_2yr", False) * 0.40
        + score("metro_unemployment_change_1yr", False) * 0.30
        + score("realtor_price_reduction_change_1yr", False) * 0.30
    )

    entry_score = (
        valuation_score * 0.20
        + supply_score * 0.18
        + price_momentum_score * 0.18
        + affordability_score * 0.16
        + economy_score * 0.12
        + mortgage_score * 0.10
        + risk_score * 0.06
    )

    entry_score = max(0, min(100, entry_score))

    return {
        "projected_entry_score": entry_score,
        "valuation_score": valuation_score,
        "supply_score": supply_score,
        "price_momentum_score": price_momentum_score,
        "affordability_score": affordability_score,
        "economy_score": economy_score,
        "mortgage_score": mortgage_score,
        "risk_score": risk_score,
        "signal_strength": signal_strength(entry_score),
        "signal_rank": signal_rank(signal_strength(entry_score)),
    }

def build_recursive_forecast(
    model_data: pd.DataFrame,
    features: list[str],
    base_prediction_model,
    min_confidence: float = 55.0,
    max_months: int = 36,
    step_months: int = 6,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Recursive multi-horizon projection engine.

    For each market:
      1. Start from latest observed state.
      2. Predict key market variables two quarters forward.
      3. Recompute derived metrics.
      4. Predict 12-month appreciation from the projected state.
      5. Recompute entry score and signal strength.
      6. Repeat every six months until confidence falls below threshold.

    Confidence is a practical confidence score:
      - Starts from the latest model confidence if available.
      - Decays by horizon.
      - Penalizes variable models with high residual uncertainty.
    """
    recursive_features = build_recursive_features(model_data)
    # Use only features that are also available to the base prediction model where possible.
    forecast_features = [f for f in features if f in model_data.columns]

    variable_models = train_variable_models(model_data, recursive_features)

    rows = []
    component_rows = []
    best_rows = []

    for market in model_data["market"].unique():
        hist = model_data[model_data["market"] == market].sort_index().copy()
        latest = hist.tail(1).iloc[0].copy()

        current_confidence = _safe_num(latest.get("forecast_confidence_score"), 75)
        if np.isnan(current_confidence) or current_confidence == 75:
            current_confidence = 75

        # Use model residual uncertainty to set a component penalty.
        model_uncertainties = [v.get("std", np.nan) for v in variable_models.values()]
        model_uncertainties = [x for x in model_uncertainties if pd.notna(x)]
        uncertainty_penalty = min(15, np.mean(model_uncertainties) * 10) if model_uncertainties else 6

        state_history = list(hist.tail(20).to_dict("records"))
        current_state = latest.copy()
        previous_state = None

        market_rows = []

        for months in range(0, max_months + step_months, step_months):
            if months == 0:
                projected_state = current_state.copy()
            else:
                # Predict raw variables two quarters forward.
                projected_state = current_state.copy()

                # Build current feature frame.
                current_feature_row = pd.DataFrame([projected_state])
                for f in recursive_features:
                    if f not in current_feature_row.columns:
                        current_feature_row[f] = np.nan

                # Fill missing current features from latest historical values.
                for f in recursive_features:
                    if pd.isna(current_feature_row.iloc[0][f]) and f in hist.columns:
                        fallback = hist[f].dropna()
                        if not fallback.empty:
                            current_feature_row.loc[current_feature_row.index[0], f] = fallback.iloc[-1]

                for target, bundle in variable_models.items():
                    model = bundle["model"]
                    try:
                        pred_value = model.predict(current_feature_row[recursive_features])[0]
                        projected_state[target] = pred_value

                        component_rows.append({
                            "market": market,
                            "horizon_months": months,
                            "component": target,
                            "projected_value": pred_value,
                            "component_mae": bundle.get("mae"),
                            "component_std": bundle.get("std"),
                            "training_rows": bundle.get("training_rows"),
                        })
                    except Exception:
                        # If a component prediction fails, carry forward the previous value.
                        pass

                projected_state = recompute_projected_features(projected_state, previous_state=current_state)

                # Update derived YoY-type fields from projected state history.
                state_history.append(projected_state.to_dict())
                sh = pd.DataFrame(state_history)

                for col in ["hpi", "zillow_zhvi", "zillow_zori", "realtor_active_listings", "realtor_median_listing_price"]:
                    if col in sh.columns and len(sh) >= 5:
                        current_val = sh[col].iloc[-1]
                        lag_val = sh[col].iloc[-5]
                        if pd.notna(current_val) and pd.notna(lag_val) and lag_val != 0:
                            if col == "hpi":
                                projected_state["hpi_yoy"] = current_val / lag_val - 1
                            elif col == "zillow_zhvi":
                                projected_state["zillow_zhvi_yoy"] = current_val / lag_val - 1
                            elif col == "zillow_zori":
                                projected_state["zillow_zori_yoy"] = current_val / lag_val - 1
                            elif col == "realtor_active_listings":
                                projected_state["realtor_active_listings_yoy"] = current_val / lag_val - 1
                            elif col == "realtor_median_listing_price":
                                projected_state["realtor_listing_price_yoy"] = current_val / lag_val - 1

                if "realtor_median_days_on_market" in sh.columns and len(sh) >= 5:
                    projected_state["realtor_dom_change_1yr"] = sh["realtor_median_days_on_market"].iloc[-1] - sh["realtor_median_days_on_market"].iloc[-5]

            # Predict next 12m appreciation from projected state.
            pred_frame = pd.DataFrame([projected_state])
            for f in forecast_features:
                if f not in pred_frame.columns:
                    pred_frame[f] = np.nan
                if pd.isna(pred_frame.iloc[0][f]) and f in hist.columns:
                    fallback = hist[f].dropna()
                    if not fallback.empty:
                        pred_frame.loc[pred_frame.index[0], f] = fallback.iloc[-1]

            try:
                predicted_growth = base_prediction_model.predict(pred_frame[forecast_features])[0]
            except Exception:
                predicted_growth = _safe_num(projected_state.get("predicted_12m_growth"), 0)

            projected_state["predicted_12m_growth"] = predicted_growth
            if "hpi" in projected_state.index and pd.notna(projected_state["hpi"]):
                projected_state["projected_hpi_12m"] = projected_state["hpi"] * (1 + predicted_growth)

            score_bundle = compute_projected_entry_score(projected_state, hist, predicted_growth)

            # Horizon confidence.
            confidence = current_confidence - (months / 6) * 5.0 - uncertainty_penalty * (months / max(step_months, 1)) * 0.15
            confidence = max(0, min(100, confidence))

            if months > 0 and confidence < min_confidence:
                break

            row = {
                "market": market,
                "horizon_months": months,
                "horizon_label": "Today" if months == 0 else f"{months} months",
                "forecast_confidence_score": confidence,
                "minimum_confidence_threshold": min_confidence,
                "projected_hpi": _safe_num(projected_state.get("hpi")),
                "projected_12m_growth_pct": predicted_growth * 100,
                "projected_hpi_12m": _safe_num(projected_state.get("projected_hpi_12m")),
                "projected_mortgage_30yr": _safe_num(projected_state.get("mortgage_30yr")),
                "projected_ten_year": _safe_num(projected_state.get("ten_year")),
                "projected_fed_funds": _safe_num(projected_state.get("fed_funds")),
                "projected_inflation_yoy_pct": _safe_num(projected_state.get("inflation_yoy")) * 100,
                "projected_metro_unemployment": _safe_num(projected_state.get("metro_unemployment")),
                "projected_zillow_zhvi": _safe_num(projected_state.get("zillow_zhvi")),
                "projected_zillow_zori": _safe_num(projected_state.get("zillow_zori")),
                "projected_realtor_active_listings": _safe_num(projected_state.get("realtor_active_listings")),
                "projected_realtor_median_listing_price": _safe_num(projected_state.get("realtor_median_listing_price")),
                "recursive_models_used": len(variable_models),
            }
            row.update(score_bundle)
            rows.append(row)
            market_rows.append(row)

            previous_state = current_state
            current_state = projected_state.copy()

        if market_rows:
            group = pd.DataFrame(market_rows)
            best = group.sort_values(["signal_rank", "projected_entry_score", "forecast_confidence_score"], ascending=False).iloc[0]
            current = group[group["horizon_months"] == 0].iloc[0]
            best_rows.append({
                "market": market,
                "current_signal_strength": current["signal_strength"],
                "current_entry_score": current["projected_entry_score"],
                "best_projected_signal_strength": best["signal_strength"],
                "best_projected_entry_score": best["projected_entry_score"],
                "best_entry_window_months": int(best["horizon_months"]),
                "best_entry_window_label": best["horizon_label"],
                "best_window_confidence": best["forecast_confidence_score"],
                "improvement_from_today": best["projected_entry_score"] - current["projected_entry_score"],
                "interpretation": (
                    f"Modeled conditions improve to {best['signal_strength']} in about {int(best['horizon_months'])} months."
                    if best["signal_rank"] > current["signal_rank"]
                    else f"No stronger opportunity appears before confidence falls below threshold; best modeled window is {int(best['horizon_months'])} months."
                ),
            })

    timeline = pd.DataFrame(rows)
    components = pd.DataFrame(component_rows)
    best_entry = pd.DataFrame(best_rows)
    return timeline, components, best_entry