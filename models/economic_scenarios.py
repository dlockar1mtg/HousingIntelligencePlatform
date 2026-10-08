from __future__ import annotations

import numpy as np
import pandas as pd

from scoring.entry_score import signal_strength, signal_rank

SCENARIOS = {
    "Bull": {
        "description": "Rates ease, affordability improves, inventory rises, economy remains stable.",
        "mortgage_rate_shift_per_6m": -0.35,
        "ten_year_shift_per_6m": -0.25,
        "fed_funds_shift_per_6m": -0.30,
        "inventory_growth_boost": 0.08,
        "listing_price_growth_shift": -0.01,
        "unemployment_shift_per_6m": 0.05,
        "confidence_penalty": 3.5,
    },
    "Base": {
        "description": "Continuation of recent trends with gradual normalization.",
        "mortgage_rate_shift_per_6m": -0.10,
        "ten_year_shift_per_6m": -0.05,
        "fed_funds_shift_per_6m": -0.10,
        "inventory_growth_boost": 0.03,
        "listing_price_growth_shift": 0.00,
        "unemployment_shift_per_6m": 0.05,
        "confidence_penalty": 4.5,
    },
    "Bear": {
        "description": "Rates remain elevated, affordability stays strained, inventory improvement is limited.",
        "mortgage_rate_shift_per_6m": 0.10,
        "ten_year_shift_per_6m": 0.08,
        "fed_funds_shift_per_6m": 0.00,
        "inventory_growth_boost": -0.02,
        "listing_price_growth_shift": 0.015,
        "unemployment_shift_per_6m": 0.15,
        "confidence_penalty": 5.5,
    },
}

def _num(value, default=np.nan):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default

def _hist_percentile(value: float, hist: pd.Series, higher_is_better: bool = True) -> float:
    h = hist.dropna()
    if len(h) == 0 or pd.isna(value):
        return 50.0
    pct = (h <= value).mean() * 100
    return pct if higher_is_better else 100 - pct

def _growth(series: pd.Series, periods: int = 4, fallback: float = 0.0) -> float:
    s = series.dropna()
    if len(s) <= periods:
        return fallback
    old = s.iloc[-periods-1]
    new = s.iloc[-1]
    if old == 0 or pd.isna(old) or pd.isna(new):
        return fallback
    return new / old - 1

def _diff(series: pd.Series, periods: int = 4, fallback: float = 0.0) -> float:
    s = series.dropna()
    if len(s) <= periods:
        return fallback
    return s.iloc[-1] - s.iloc[-periods-1]

def mortgage_payment(principal: float, annual_rate_pct: float, years: int = 30) -> float:
    monthly_rate = annual_rate_pct / 100 / 12
    n = years * 12
    if principal <= 0:
        return 0
    if monthly_rate == 0:
        return principal / n
    return principal * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)

def project_state_from_scenario(
    latest: pd.Series,
    hist: pd.DataFrame,
    scenario_name: str,
    horizon_months: int,
) -> pd.Series:
    scenario = SCENARIOS[scenario_name]
    steps = horizon_months / 6

    s = latest.copy()

    # Rate path
    for col, shift_key in [
        ("mortgage_30yr", "mortgage_rate_shift_per_6m"),
        ("ten_year", "ten_year_shift_per_6m"),
        ("fed_funds", "fed_funds_shift_per_6m"),
    ]:
        if col in s.index:
            s[col] = max(0, _num(s[col], 0) + scenario[shift_key] * steps)

    if "mortgage_30yr" in s.index and "ten_year" in s.index:
        s["mortgage_spread"] = s["mortgage_30yr"] - s["ten_year"]
    if "ten_year" in s.index and "fed_funds" in s.index:
        s["yield_curve"] = s["ten_year"] - s["fed_funds"]

    # Mortgage change from current baseline
    latest_mortgage = _num(latest.get("mortgage_30yr"), 0)
    s["mortgage_change_4q"] = s.get("mortgage_30yr", latest_mortgage) - latest_mortgage
    s["mortgage_change_1q"] = s["mortgage_change_4q"] / 4

    # Inflation path: gently normalizes in bull/base; sticky in bear
    if "inflation_yoy" in s.index:
        current_infl = _num(s["inflation_yoy"], 0.025)
        target = 0.022 if scenario_name == "Bull" else 0.024 if scenario_name == "Base" else 0.030
        s["inflation_yoy"] = current_infl + (target - current_infl) * min(1, steps / 4)
        s["inflation_trend"] = s["inflation_yoy"] - current_infl

    # Local unemployment path
    if "metro_unemployment" in s.index:
        s["metro_unemployment"] = max(0, _num(s["metro_unemployment"], 4) + scenario["unemployment_shift_per_6m"] * steps)
        s["metro_unemployment_change_1yr"] = scenario["unemployment_shift_per_6m"] * 2

    # Payroll growth softens/slightly strengthens by scenario
    if "metro_payroll_growth_yoy" in s.index:
        current = _num(s["metro_payroll_growth_yoy"], 0.01)
        adjust = 0.006 if scenario_name == "Bull" else 0.000 if scenario_name == "Base" else -0.008
        s["metro_payroll_growth_yoy"] = current + adjust * min(1, steps / 2)

    if "metro_labor_force_growth_yoy" in s.index:
        current = _num(s["metro_labor_force_growth_yoy"], 0.005)
        adjust = 0.004 if scenario_name == "Bull" else 0.000 if scenario_name == "Base" else -0.004
        s["metro_labor_force_growth_yoy"] = current + adjust * min(1, steps / 2)

    # Inventory and listing market path
    if "realtor_active_listings" in s.index:
        current = _num(s["realtor_active_listings"], np.nan)
        hist_growth = _growth(hist.get("realtor_active_listings", pd.Series(dtype=float)), 4, 0.0)
        projected_growth = hist_growth + scenario["inventory_growth_boost"] * steps
        if not np.isnan(current):
            s["realtor_active_listings"] = current * max(0.15, 1 + projected_growth)
            s["realtor_active_listings_yoy"] = projected_growth

    if "composite_active_listings_yoy" in s.index:
        s["composite_active_listings_yoy"] = _num(s.get("composite_active_listings_yoy"), 0) + scenario["inventory_growth_boost"] * steps

    if "realtor_median_listing_price" in s.index:
        current = _num(s["realtor_median_listing_price"], np.nan)
        hist_growth = _growth(hist.get("realtor_median_listing_price", pd.Series(dtype=float)), 4, 0.0)
        projected_growth = hist_growth + scenario["listing_price_growth_shift"] * steps
        if not np.isnan(current):
            s["realtor_median_listing_price"] = current * max(0.2, 1 + projected_growth)
            s["realtor_listing_price_yoy"] = projected_growth

    if "zillow_zhvi" in s.index:
        current = _num(s["zillow_zhvi"], np.nan)
        hist_growth = _growth(hist.get("zillow_zhvi", pd.Series(dtype=float)), 4, 0.0)
        # High rates dampen value growth; bull slightly supports demand despite more inventory.
        rate_effect = -0.006 * (s.get("mortgage_30yr", latest.get("mortgage_30yr", 6.5)) - latest.get("mortgage_30yr", 6.5))
        scenario_adjust = 0.004 if scenario_name == "Bull" else 0.0 if scenario_name == "Base" else -0.006
        projected_growth = hist_growth + rate_effect + scenario_adjust
        if not np.isnan(current):
            s["zillow_zhvi"] = current * ((1 + projected_growth) ** (horizon_months / 12))
            s["zillow_zhvi_yoy"] = projected_growth

    if "zillow_zori" in s.index:
        current = _num(s["zillow_zori"], np.nan)
        hist_growth = _growth(hist.get("zillow_zori", pd.Series(dtype=float)), 4, 0.0)
        rent_adjust = 0.002 if scenario_name == "Bear" else 0.0
        projected_growth = hist_growth + rent_adjust
        if not np.isnan(current):
            s["zillow_zori"] = current * ((1 + projected_growth) ** (horizon_months / 12))
            s["zillow_zori_yoy"] = projected_growth

    if "zillow_zhvi" in s.index and "zillow_zori" in s.index:
        zhvi = _num(s["zillow_zhvi"], np.nan)
        zori = _num(s["zillow_zori"], np.nan)
        if not np.isnan(zhvi) and zhvi > 0 and not np.isnan(zori):
            s["rent_to_price_ratio"] = (zori * 12) / zhvi

    # Days on market and price reductions
    if "realtor_median_days_on_market" in s.index:
        current = _num(s["realtor_median_days_on_market"], 30)
        dom_change = 6 if scenario_name == "Bull" else 3 if scenario_name == "Base" else -1
        s["realtor_median_days_on_market"] = max(0, current + dom_change * steps)
        s["realtor_dom_change_1yr"] = dom_change * 2

    if "realtor_price_reduction_share" in s.index:
        current = _num(s["realtor_price_reduction_share"], 0.0)
        shift = 0.015 if scenario_name == "Bull" else 0.005 if scenario_name == "Base" else -0.002
        s["realtor_price_reduction_share"] = max(0, min(1, current + shift * steps))
        s["realtor_price_reduction_change_1yr"] = shift * 2

    # Income and affordability
    if "median_household_income" in s.index:
        current = _num(s["median_household_income"], np.nan)
        income_growth = 0.025 if scenario_name == "Bull" else 0.020 if scenario_name == "Base" else 0.012
        if not np.isnan(current):
            s["median_household_income"] = current * ((1 + income_growth) ** (horizon_months / 12))

    # Estimated home price = Zillow if available
    if "zillow_zhvi" in s.index:
        s["estimated_home_price"] = s["zillow_zhvi"]
    elif "realtor_median_listing_price" in s.index:
        s["estimated_home_price"] = s["realtor_median_listing_price"]

    if "estimated_home_price" in s.index and "mortgage_30yr" in s.index:
        price = _num(s["estimated_home_price"], np.nan)
        rate = _num(s["mortgage_30yr"], 6.5)
        if not np.isnan(price):
            s["estimated_monthly_pi_payment"] = mortgage_payment(price * 0.80, rate)

    if "median_household_income" in s.index and "estimated_monthly_pi_payment" in s.index:
        income = _num(s["median_household_income"], np.nan)
        payment = _num(s["estimated_monthly_pi_payment"], np.nan)
        if not np.isnan(income) and income > 0 and not np.isnan(payment):
            s["payment_to_income_ratio"] = payment / (income / 12)

    # Months supply
    if "months_supply" in s.index:
        current = _num(s["months_supply"], np.nan)
        shift = 0.20 if scenario_name == "Bull" else 0.05 if scenario_name == "Base" else -0.05
        if not np.isnan(current):
            s["months_supply"] = max(0.5, current + shift * steps)
            s["months_supply_change_1yr"] = shift * 2

    return s

def compute_entry_score(projected: pd.Series, hist: pd.DataFrame, predicted_growth: float) -> dict:
    def score(col, higher=True):
        if col not in hist.columns:
            return 50.0
        return _hist_percentile(_num(projected.get(col)), hist[col], higher)

    price_momentum_score = _hist_percentile(predicted_growth, hist.get("predicted_12m_growth", pd.Series(dtype=float)), True)

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
    signal = signal_strength(entry_score)

    return {
        "projected_entry_score": entry_score,
        "signal_strength": signal,
        "signal_rank": signal_rank(signal),
        "valuation_score": valuation_score,
        "supply_score": supply_score,
        "price_momentum_score": price_momentum_score,
        "affordability_score": affordability_score,
        "economy_score": economy_score,
        "mortgage_score": mortgage_score,
        "risk_score": risk_score,
    }

def build_hybrid_scenario_forecast(
    model_data: pd.DataFrame,
    features: list[str],
    base_prediction_model,
    min_confidence: float = 55.0,
    max_months: int = 36,
    step_months: int = 6,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    component_rows = []

    for market in model_data["market"].unique():
        hist = model_data[model_data["market"] == market].sort_index().copy()
        latest = hist.tail(1).iloc[0].copy()

        # Conservative fallback confidence
        current_confidence = _num(latest.get("forecast_confidence_score"), 75)
        if pd.isna(current_confidence):
            current_confidence = 75

        for scenario_name, scenario in SCENARIOS.items():
            for months in range(0, max_months + step_months, step_months):
                confidence = current_confidence - (months / 6) * scenario["confidence_penalty"]
                if months > 0 and confidence < min_confidence:
                    break

                projected = project_state_from_scenario(latest, hist, scenario_name, months)

                pred_frame = pd.DataFrame([projected])
                for f in features:
                    if f not in pred_frame.columns:
                        pred_frame[f] = np.nan
                    if pd.isna(pred_frame.iloc[0][f]) and f in hist.columns:
                        fallback = hist[f].dropna()
                        if not fallback.empty:
                            pred_frame.loc[pred_frame.index[0], f] = fallback.iloc[-1]

                try:
                    predicted_growth = base_prediction_model.predict(pred_frame[features])[0]
                except Exception:
                    predicted_growth = _num(latest.get("predicted_12m_growth"), 0)

                projected["predicted_12m_growth"] = predicted_growth
                hpi = _num(projected.get("hpi"), _num(latest.get("hpi"), np.nan))
                if not np.isnan(hpi):
                    projected["projected_hpi_12m"] = hpi * (1 + predicted_growth)

                score_bundle = compute_entry_score(projected, hist, predicted_growth)

                row = {
                    "market": market,
                    "scenario": scenario_name,
                    "scenario_description": scenario["description"],
                    "horizon_months": months,
                    "horizon_label": "Today" if months == 0 else f"{months} months",
                    "forecast_confidence_score": max(0, min(100, confidence)),
                    "minimum_confidence_threshold": min_confidence,
                    "projected_hpi": hpi,
                    "projected_12m_growth_pct": predicted_growth * 100,
                    "projected_hpi_12m": _num(projected.get("projected_hpi_12m")),
                    "projected_mortgage_30yr": _num(projected.get("mortgage_30yr")),
                    "projected_ten_year": _num(projected.get("ten_year")),
                    "projected_fed_funds": _num(projected.get("fed_funds")),
                    "projected_inflation_yoy_pct": _num(projected.get("inflation_yoy")) * 100,
                    "projected_metro_unemployment": _num(projected.get("metro_unemployment")),
                    "projected_zillow_zhvi": _num(projected.get("zillow_zhvi")),
                    "projected_zillow_zori": _num(projected.get("zillow_zori")),
                    "projected_realtor_active_listings": _num(projected.get("realtor_active_listings")),
                    "projected_realtor_median_listing_price": _num(projected.get("realtor_median_listing_price")),
                    "projected_payment_to_income_ratio": _num(projected.get("payment_to_income_ratio")),
                    "projected_months_supply": _num(projected.get("months_supply")),
                }
                row.update(score_bundle)
                rows.append(row)

                for component in [
                    "mortgage_30yr", "ten_year", "fed_funds", "inflation_yoy",
                    "metro_unemployment", "realtor_active_listings",
                    "realtor_median_listing_price", "zillow_zhvi", "zillow_zori",
                    "payment_to_income_ratio", "months_supply"
                ]:
                    if component in projected.index:
                        component_rows.append({
                            "market": market,
                            "scenario": scenario_name,
                            "horizon_months": months,
                            "component": component,
                            "projected_value": _num(projected.get(component)),
                        })

    timeline = pd.DataFrame(rows)
    components = pd.DataFrame(component_rows)

    best_rows = []
    if not timeline.empty:
        for market, group in timeline.groupby("market"):
            # Base scenario current is the reference
            current = group[(group["scenario"] == "Base") & (group["horizon_months"] == 0)]
            if current.empty:
                current = group[group["horizon_months"] == 0]
            current_row = current.iloc[0]

            eligible = group[group["forecast_confidence_score"] >= min_confidence].copy()
            best = eligible.sort_values(
                ["signal_rank", "projected_entry_score", "forecast_confidence_score"],
                ascending=False
            ).iloc[0]

            best_rows.append({
                "market": market,
                "current_signal_strength": current_row["signal_strength"],
                "current_entry_score": current_row["projected_entry_score"],
                "best_scenario": best["scenario"],
                "best_projected_signal_strength": best["signal_strength"],
                "best_projected_entry_score": best["projected_entry_score"],
                "best_entry_window_months": int(best["horizon_months"]),
                "best_entry_window_label": best["horizon_label"],
                "best_window_confidence": best["forecast_confidence_score"],
                "improvement_from_today": best["projected_entry_score"] - current_row["projected_entry_score"],
                "interpretation": (
                    f"Best modeled opportunity is {best['signal_strength']} under the {best['scenario']} scenario in about {int(best['horizon_months'])} months."
                    if int(best["horizon_months"]) > 0
                    else f"Best modeled opportunity is today under the {best['scenario']} scenario."
                ),
            })

    best_entry = pd.DataFrame(best_rows)

    # Scenario probability summary by market/horizon.
    probability_rows = []
    if not timeline.empty:
        for (market, months), group in timeline.groupby(["market", "horizon_months"]):
            total = len(group)
            for signal in [
                "Strong Buy", "Buy", "Slight Buy", "Neutral / Fair Value",
                "Slight Wait", "Wait", "Strong Wait / High Risk"
            ]:
                probability_rows.append({
                    "market": market,
                    "horizon_months": months,
                    "signal_strength": signal,
                    "scenario_share": (group["signal_strength"] == signal).sum() / total if total else 0,
                })

    probabilities = pd.DataFrame(probability_rows)

    return timeline, components, best_entry, probabilities