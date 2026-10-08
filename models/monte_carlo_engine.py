from __future__ import annotations

import numpy as np
import pandas as pd

from scoring.entry_score import signal_strength, signal_rank

RANDOM_SEED = 42

SIGNAL_LEVELS = [
    "Strong Buy", "Buy", "Slight Buy", "Neutral / Fair Value",
    "Slight Wait", "Wait", "Strong Wait / High Risk",
]

SCENARIO_PARAMETERS = {
    "Bull": {
        "weight": 0.25,
        "mortgage_rate_shift_mean": -0.35,
        "mortgage_rate_shift_sd": 0.20,
        "ten_year_shift_mean": -0.25,
        "ten_year_shift_sd": 0.15,
        "fed_funds_shift_mean": -0.30,
        "fed_funds_shift_sd": 0.20,
        "inventory_growth_mean": 0.10,
        "inventory_growth_sd": 0.07,
        "listing_price_growth_shift_mean": -0.01,
        "listing_price_growth_shift_sd": 0.02,
        "unemployment_shift_mean": 0.04,
        "unemployment_shift_sd": 0.08,
        "income_growth_mean": 0.030,
        "income_growth_sd": 0.010,
    },
    "Base": {
        "weight": 0.50,
        "mortgage_rate_shift_mean": -0.10,
        "mortgage_rate_shift_sd": 0.18,
        "ten_year_shift_mean": -0.05,
        "ten_year_shift_sd": 0.14,
        "fed_funds_shift_mean": -0.10,
        "fed_funds_shift_sd": 0.18,
        "inventory_growth_mean": 0.04,
        "inventory_growth_sd": 0.06,
        "listing_price_growth_shift_mean": 0.00,
        "listing_price_growth_shift_sd": 0.02,
        "unemployment_shift_mean": 0.06,
        "unemployment_shift_sd": 0.10,
        "income_growth_mean": 0.022,
        "income_growth_sd": 0.009,
    },
    "Bear": {
        "weight": 0.25,
        "mortgage_rate_shift_mean": 0.12,
        "mortgage_rate_shift_sd": 0.22,
        "ten_year_shift_mean": 0.08,
        "ten_year_shift_sd": 0.16,
        "fed_funds_shift_mean": 0.00,
        "fed_funds_shift_sd": 0.15,
        "inventory_growth_mean": -0.02,
        "inventory_growth_sd": 0.07,
        "listing_price_growth_shift_mean": 0.015,
        "listing_price_growth_shift_sd": 0.025,
        "unemployment_shift_mean": 0.16,
        "unemployment_shift_sd": 0.14,
        "income_growth_mean": 0.014,
        "income_growth_sd": 0.010,
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
    old = s.iloc[-periods - 1]
    new = s.iloc[-1]
    if old == 0 or pd.isna(old) or pd.isna(new):
        return fallback
    return new / old - 1


def mortgage_payment(principal: float, annual_rate_pct: float, years: int = 30) -> float:
    monthly_rate = annual_rate_pct / 100 / 12
    n = years * 12
    if principal <= 0:
        return 0.0
    if monthly_rate == 0:
        return principal / n
    return principal * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)


def sample_scenario(rng: np.random.Generator) -> str:
    names = list(SCENARIO_PARAMETERS.keys())
    weights = np.array([SCENARIO_PARAMETERS[n]["weight"] for n in names], dtype=float)
    weights = weights / weights.sum()
    return rng.choice(names, p=weights)


def project_random_state(latest: pd.Series, hist: pd.DataFrame, scenario_name: str, horizon_months: int, rng: np.random.Generator) -> pd.Series:
    params = SCENARIO_PARAMETERS[scenario_name]
    steps = horizon_months / 6
    years = horizon_months / 12
    s = latest.copy()

    mortgage_shift = rng.normal(params["mortgage_rate_shift_mean"], params["mortgage_rate_shift_sd"]) * steps
    ten_year_shift = rng.normal(params["ten_year_shift_mean"], params["ten_year_shift_sd"]) * steps
    fed_shift = rng.normal(params["fed_funds_shift_mean"], params["fed_funds_shift_sd"]) * steps

    if "mortgage_30yr" in s.index:
        s["mortgage_30yr"] = max(0, _num(s["mortgage_30yr"], 0) + mortgage_shift)
    if "ten_year" in s.index:
        s["ten_year"] = max(0, _num(s["ten_year"], 0) + ten_year_shift)
    if "fed_funds" in s.index:
        s["fed_funds"] = max(0, _num(s["fed_funds"], 0) + fed_shift)

    if "mortgage_30yr" in s.index and "ten_year" in s.index:
        s["mortgage_spread"] = s["mortgage_30yr"] - s["ten_year"]
    if "ten_year" in s.index and "fed_funds" in s.index:
        s["yield_curve"] = s["ten_year"] - s["fed_funds"]

    latest_mortgage = _num(latest.get("mortgage_30yr"), 0)
    s["mortgage_change_4q"] = _num(s.get("mortgage_30yr"), latest_mortgage) - latest_mortgage
    s["mortgage_change_1q"] = s["mortgage_change_4q"] / 4

    if "inflation_yoy" in s.index:
        current_infl = _num(s["inflation_yoy"], 0.025)
        target = 0.022 if scenario_name == "Bull" else 0.024 if scenario_name == "Base" else 0.030
        s["inflation_yoy"] = current_infl + (target - current_infl) * min(1, years / 2) + rng.normal(0, 0.004)
        s["inflation_trend"] = s["inflation_yoy"] - current_infl

    unemployment_shift = rng.normal(params["unemployment_shift_mean"], params["unemployment_shift_sd"]) * steps
    if "metro_unemployment" in s.index:
        s["metro_unemployment"] = max(0, _num(s["metro_unemployment"], 4) + unemployment_shift)
        s["metro_unemployment_change_1yr"] = unemployment_shift / max(years, 0.5)

    if "metro_payroll_growth_yoy" in s.index:
        current = _num(s["metro_payroll_growth_yoy"], 0.01)
        scenario_adjust = 0.006 if scenario_name == "Bull" else 0.0 if scenario_name == "Base" else -0.008
        s["metro_payroll_growth_yoy"] = current + scenario_adjust + rng.normal(0, 0.006)

    if "metro_labor_force_growth_yoy" in s.index:
        current = _num(s["metro_labor_force_growth_yoy"], 0.005)
        scenario_adjust = 0.004 if scenario_name == "Bull" else 0.0 if scenario_name == "Base" else -0.004
        s["metro_labor_force_growth_yoy"] = current + scenario_adjust + rng.normal(0, 0.004)

    inventory_growth = rng.normal(params["inventory_growth_mean"], params["inventory_growth_sd"]) * steps
    if "realtor_active_listings" in s.index:
        current = _num(s["realtor_active_listings"], np.nan)
        hist_growth = _growth(hist.get("realtor_active_listings", pd.Series(dtype=float)), 4, 0.0)
        projected_growth = hist_growth + inventory_growth
        if not np.isnan(current):
            s["realtor_active_listings"] = current * max(0.15, 1 + projected_growth)
            s["realtor_active_listings_yoy"] = projected_growth

    if "composite_active_listings_yoy" in s.index:
        s["composite_active_listings_yoy"] = _num(s.get("composite_active_listings_yoy"), 0) + inventory_growth

    listing_shift = rng.normal(params["listing_price_growth_shift_mean"], params["listing_price_growth_shift_sd"]) * max(1, years)
    if "realtor_median_listing_price" in s.index:
        current = _num(s["realtor_median_listing_price"], np.nan)
        hist_growth = _growth(hist.get("realtor_median_listing_price", pd.Series(dtype=float)), 4, 0.0)
        projected_growth = hist_growth + listing_shift
        if not np.isnan(current):
            s["realtor_median_listing_price"] = current * max(0.2, 1 + projected_growth)
            s["realtor_listing_price_yoy"] = projected_growth

    if "zillow_zhvi" in s.index:
        current = _num(s["zillow_zhvi"], np.nan)
        hist_growth = _growth(hist.get("zillow_zhvi", pd.Series(dtype=float)), 4, 0.0)
        rate_effect = -0.008 * (_num(s.get("mortgage_30yr"), _num(latest.get("mortgage_30yr"), 6.5)) - _num(latest.get("mortgage_30yr"), 6.5))
        scenario_adjust = 0.004 if scenario_name == "Bull" else 0.0 if scenario_name == "Base" else -0.008
        projected_growth = hist_growth + rate_effect + scenario_adjust + rng.normal(0, 0.018)
        if not np.isnan(current):
            s["zillow_zhvi"] = current * ((1 + projected_growth) ** years)
            s["zillow_zhvi_yoy"] = projected_growth
            s["hpi_yoy"] = projected_growth

    if "zillow_zori" in s.index:
        current = _num(s["zillow_zori"], np.nan)
        hist_growth = _growth(hist.get("zillow_zori", pd.Series(dtype=float)), 4, 0.0)
        projected_growth = hist_growth + (0.002 if scenario_name == "Bear" else 0.0) + rng.normal(0, 0.01)
        if not np.isnan(current):
            s["zillow_zori"] = current * ((1 + projected_growth) ** years)
            s["zillow_zori_yoy"] = projected_growth

    if "zillow_zhvi" in s.index and "zillow_zori" in s.index:
        zhvi = _num(s["zillow_zhvi"], np.nan)
        zori = _num(s["zillow_zori"], np.nan)
        if not np.isnan(zhvi) and zhvi > 0 and not np.isnan(zori):
            s["rent_to_price_ratio"] = (zori * 12) / zhvi

    if "realtor_median_days_on_market" in s.index:
        current = _num(s["realtor_median_days_on_market"], 30)
        dom_change = 6 if scenario_name == "Bull" else 3 if scenario_name == "Base" else -1
        s["realtor_median_days_on_market"] = max(0, current + rng.normal(dom_change, 3) * steps)
        s["realtor_dom_change_1yr"] = (s["realtor_median_days_on_market"] - current) / max(years, 0.5)

    if "realtor_price_reduction_share" in s.index:
        current = _num(s["realtor_price_reduction_share"], 0.0)
        shift = 0.015 if scenario_name == "Bull" else 0.005 if scenario_name == "Base" else -0.002
        s["realtor_price_reduction_share"] = max(0, min(1, current + rng.normal(shift, 0.01) * steps))
        s["realtor_price_reduction_change_1yr"] = (s["realtor_price_reduction_share"] - current) / max(years, 0.5)

    if "median_household_income" in s.index:
        current = _num(s["median_household_income"], np.nan)
        income_growth = rng.normal(params["income_growth_mean"], params["income_growth_sd"])
        if not np.isnan(current):
            s["median_household_income"] = current * ((1 + income_growth) ** years)

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

    if "months_supply" in s.index:
        current = _num(s["months_supply"], np.nan)
        shift = 0.20 if scenario_name == "Bull" else 0.05 if scenario_name == "Base" else -0.05
        if not np.isnan(current):
            s["months_supply"] = max(0.5, current + rng.normal(shift, 0.10) * steps)
            s["months_supply_change_1yr"] = (s["months_supply"] - current) / max(years, 0.5)

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


def run_monte_carlo_simulation(
    model_data: pd.DataFrame,
    features: list[str],
    base_prediction_model,
    n_simulations: int = 2000,
    max_months: int = 36,
    step_months: int = 6,
    min_confidence: float = 55.0,
):
    rng = np.random.default_rng(RANDOM_SEED)
    all_rows = []
    horizons = list(range(0, max_months + step_months, step_months))

    for market in model_data["market"].unique():
        hist = model_data[model_data["market"] == market].sort_index().copy()
        latest = hist.tail(1).iloc[0].copy()

        for sim in range(1, n_simulations + 1):
            scenario = sample_scenario(rng)

            for months in horizons:
                confidence = 100 - (months / 6) * 6
                if months > 0 and confidence < min_confidence:
                    continue

                projected = project_random_state(latest, hist, scenario, months, rng)

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

                hpi = _num(projected.get("hpi"), _num(latest.get("hpi"), np.nan))
                projected_hpi_12m = hpi * (1 + predicted_growth) if not np.isnan(hpi) else np.nan
                score_bundle = compute_entry_score(projected, hist, predicted_growth)

                all_rows.append({
                    "market": market,
                    "simulation_id": sim,
                    "scenario": scenario,
                    "horizon_months": months,
                    "horizon_label": "Today" if months == 0 else f"{months} months",
                    "forecast_confidence_score": confidence,
                    "projected_hpi": hpi,
                    "projected_12m_growth_pct": predicted_growth * 100,
                    "projected_hpi_12m": projected_hpi_12m,
                    "projected_mortgage_30yr": _num(projected.get("mortgage_30yr")),
                    "projected_ten_year": _num(projected.get("ten_year")),
                    "projected_metro_unemployment": _num(projected.get("metro_unemployment")),
                    "projected_zillow_zhvi": _num(projected.get("zillow_zhvi")),
                    "projected_realtor_active_listings": _num(projected.get("realtor_active_listings")),
                    "projected_payment_to_income_ratio": _num(projected.get("payment_to_income_ratio")),
                    **score_bundle,
                })

    simulations = pd.DataFrame(all_rows)
    summary_rows = []
    probability_rows = []
    best_rows = []

    if simulations.empty:
        return simulations, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    for (market, months), group in simulations.groupby(["market", "horizon_months"]):
        summary_rows.append({
            "market": market,
            "horizon_months": months,
            "horizon_label": "Today" if months == 0 else f"{months} months",
            "simulations": len(group),
            "entry_score_mean": group["projected_entry_score"].mean(),
            "entry_score_median": group["projected_entry_score"].median(),
            "entry_score_p10": group["projected_entry_score"].quantile(0.10),
            "entry_score_p90": group["projected_entry_score"].quantile(0.90),
            "growth_mean_pct": group["projected_12m_growth_pct"].mean(),
            "growth_p10_pct": group["projected_12m_growth_pct"].quantile(0.10),
            "growth_p90_pct": group["projected_12m_growth_pct"].quantile(0.90),
            "mortgage_mean": group["projected_mortgage_30yr"].mean(),
            "payment_to_income_mean": group["projected_payment_to_income_ratio"].mean(),
            "prob_neutral_or_better": (group["signal_rank"] >= signal_rank("Neutral / Fair Value")).mean(),
            "prob_slight_buy_or_better": (group["signal_rank"] >= signal_rank("Slight Buy")).mean(),
            "prob_buy_or_better": (group["signal_rank"] >= signal_rank("Buy")).mean(),
            "prob_strong_buy": (group["signal_strength"] == "Strong Buy").mean(),
        })

        for signal in SIGNAL_LEVELS:
            probability_rows.append({
                "market": market,
                "horizon_months": months,
                "horizon_label": "Today" if months == 0 else f"{months} months",
                "signal_strength": signal,
                "probability": (group["signal_strength"] == signal).mean(),
            })

    summary = pd.DataFrame(summary_rows)
    probabilities = pd.DataFrame(probability_rows)

    for market, group in summary.groupby("market"):
        eligible = group[group["entry_score_mean"].notna()].copy()
        if eligible.empty:
            continue
        best = eligible.sort_values(["prob_slight_buy_or_better", "prob_neutral_or_better", "entry_score_mean"], ascending=False).iloc[0]
        today = eligible[eligible["horizon_months"] == 0].iloc[0] if not eligible[eligible["horizon_months"] == 0].empty else eligible.iloc[0]
        best_rows.append({
            "market": market,
            "current_expected_entry_score": today["entry_score_mean"],
            "best_expected_entry_score": best["entry_score_mean"],
            "best_entry_window_months": int(best["horizon_months"]),
            "best_entry_window_label": best["horizon_label"],
            "prob_neutral_or_better": best["prob_neutral_or_better"],
            "prob_slight_buy_or_better": best["prob_slight_buy_or_better"],
            "prob_buy_or_better": best["prob_buy_or_better"],
            "expected_score_improvement": best["entry_score_mean"] - today["entry_score_mean"],
            "interpretation": (
                f"Best simulated window is {best['horizon_label']} with "
                f"{best['prob_neutral_or_better']:.1%} probability of Neutral/Fair Value or better "
                f"and {best['prob_slight_buy_or_better']:.1%} probability of Slight Buy or better."
            ),
        })

    best_windows = pd.DataFrame(best_rows)
    return simulations, summary, probabilities, best_windows