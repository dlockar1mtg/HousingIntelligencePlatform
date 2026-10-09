from __future__ import annotations
import numpy as np
import pandas as pd

from config.utils import is_v11

def percentile_score(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    pct = series.rank(pct=True) * 100
    return pct if higher_is_better else 100 - pct

def point_in_time_percentile(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """V11: each quarter's percentile among the market's quarters up to and including it."""
    pct = series.expanding().rank(pct=True) * 100
    return pct if higher_is_better else 100 - pct

def safe_score(data: pd.DataFrame, col: str, higher_is_better: bool = True, point_in_time: bool | None = None) -> pd.Series:
    if col not in data.columns:
        return pd.Series(50, index=data.index)
    if (is_v11() if point_in_time is None else point_in_time):
        return data.groupby("market")[col].transform(lambda x: point_in_time_percentile(x.sort_index(), higher_is_better).reindex(x.index)).fillna(50)
    return data.groupby("market")[col].transform(lambda x: percentile_score(x, higher_is_better)).fillna(50)

def add_entry_scores(data: pd.DataFrame, point_in_time: bool | None = None) -> pd.DataFrame:
    data = data.copy()
    _score = safe_score
    safe_score_ = lambda d, c, h=True: _score(d, c, h, point_in_time)  # noqa: E731
    data["price_momentum_score"] = safe_score_(data, "predicted_12m_growth", True)

    data["valuation_score"] = (
        safe_score_(data, "hpi_yoy", False) * 0.20
        + safe_score_(data, "hpi_5yr_growth", False) * 0.20
        + safe_score_(data, "composite_listing_price_yoy", False) * 0.20
        + safe_score_(data, "zillow_zhvi_yoy", False) * 0.20
        + safe_score_(data, "realtor_listing_price_yoy", False) * 0.20
    )

    data["supply_score"] = (
        safe_score_(data, "months_supply", True) * 0.20
        + safe_score_(data, "composite_active_listings_yoy", True) * 0.25
        + safe_score_(data, "realtor_active_listings_yoy", True) * 0.25
        + safe_score_(data, "realtor_dom_change_1yr", True) * 0.15
        + safe_score_(data, "composite_county_permits_yoy", True) * 0.15
    )

    data["economy_score"] = (
        safe_score_(data, "metro_unemployment", False) * 0.35
        + safe_score_(data, "metro_payroll_growth_yoy", True) * 0.35
        + safe_score_(data, "metro_labor_force_growth_yoy", True) * 0.30
    )

    data["mortgage_score"] = (
        safe_score_(data, "mortgage_30yr", False) * 0.45
        + safe_score_(data, "mortgage_change_4q", False) * 0.35
        + safe_score_(data, "mortgage_spread", False) * 0.20
    )

    data["affordability_score"] = (
        safe_score_(data, "payment_to_income_ratio", False) * 0.70
        + safe_score_(data, "payment_to_income_change_1yr", False) * 0.30
    )

    data["risk_score"] = (
        safe_score_(data, "hpi_volatility_2yr", False) * 0.40
        + safe_score_(data, "metro_unemployment_change_1yr", False) * 0.30
        + safe_score_(data, "realtor_price_reduction_change_1yr", False) * 0.30
    )

    data["entry_score"] = (
        data["valuation_score"] * 0.20
        + data["supply_score"] * 0.18
        + data["price_momentum_score"] * 0.18
        + data["affordability_score"] * 0.16
        + data["economy_score"] * 0.12
        + data["mortgage_score"] * 0.10
        + data["risk_score"] * 0.06
    ).clip(0, 100)

    return data

SCORE_INPUTS = (
    "predicted_12m_growth", "hpi_yoy", "hpi_5yr_growth", "composite_listing_price_yoy", "zillow_zhvi_yoy",
    "realtor_listing_price_yoy", "months_supply", "composite_active_listings_yoy", "realtor_active_listings_yoy",
    "realtor_dom_change_1yr", "composite_county_permits_yoy", "metro_unemployment", "metro_payroll_growth_yoy",
    "metro_labor_force_growth_yoy", "mortgage_30yr", "mortgage_change_4q", "mortgage_spread",
    "payment_to_income_ratio", "payment_to_income_change_1yr", "hpi_volatility_2yr",
    "metro_unemployment_change_1yr", "realtor_price_reduction_change_1yr",
)


def neutral_inputs(latest: pd.DataFrame) -> dict[str, list[str]]:
    """Audit finding 5: Entry Score inputs that were absent or missing in each market's scored quarter and so
    scored a neutral 50. Published in the contract's warnings instead of passing silently."""
    out = {}
    for _, row in latest.iterrows():
        missing = [c for c in SCORE_INPUTS if c not in row.index or pd.isna(row[c])]
        if missing:
            out[str(row["market"])] = missing
    return out


def signal_strength(score: float) -> str:
    if score >= 85: return "Strong Buy"
    if score >= 72: return "Buy"
    if score >= 60: return "Slight Buy"
    if score >= 48: return "Neutral / Fair Value"
    if score >= 36: return "Slight Wait"
    if score >= 24: return "Wait"
    return "Strong Wait / High Risk"

def signal_rank(signal: str) -> int:
    return {
        "Strong Wait / High Risk": 1,
        "Wait": 2,
        "Slight Wait": 3,
        "Neutral / Fair Value": 4,
        "Slight Buy": 5,
        "Buy": 6,
        "Strong Buy": 7,
    }.get(signal, 0)

def entry_signal(score: float) -> str:
    return signal_strength(score)

def classify_market_regime(row: pd.Series) -> str:
    hpi_yoy = row.get("hpi_yoy", np.nan)
    inv_yoy = row.get("realtor_active_listings_yoy", row.get("composite_active_listings_yoy", np.nan))
    dom_change = row.get("realtor_dom_change_1yr", np.nan)
    unemployment_change = row.get("metro_unemployment_change_1yr", np.nan)
    mortgage_change = row.get("mortgage_change_4q", np.nan)

    if pd.notna(hpi_yoy) and hpi_yoy < -0.02:
        return "Correction"
    if pd.notna(hpi_yoy) and hpi_yoy > 0.08 and pd.notna(mortgage_change) and mortgage_change > 0.5:
        return "Overheated / Rate Pressure"
    if pd.notna(inv_yoy) and inv_yoy > 0.25 and pd.notna(dom_change) and dom_change > 10:
        return "Buyer Leverage Improving"
    if pd.notna(unemployment_change) and unemployment_change > 0.75:
        return "Economic Softening"
    if pd.notna(hpi_yoy) and hpi_yoy > 0.03:
        return "Expansion"
    return "Neutral / Transition"