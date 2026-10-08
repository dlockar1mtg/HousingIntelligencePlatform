from __future__ import annotations

import numpy as np
import pandas as pd

def mortgage_payment(principal: pd.Series, annual_rate_pct: pd.Series, years: int = 30) -> pd.Series:
    monthly_rate = annual_rate_pct / 100 / 12
    n = years * 12
    payment = principal * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)
    return payment.where(monthly_rate != 0, principal / n)

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["hpi_qoq"] = df["hpi"].pct_change()
    df["hpi_yoy"] = df["hpi"].pct_change(4)
    df["hpi_3yr_growth"] = df["hpi"].pct_change(12)
    df["hpi_5yr_growth"] = df["hpi"].pct_change(20)
    df["hpi_volatility_2yr"] = df["hpi_qoq"].rolling(8).std()
    df["hpi_momentum_4q"] = df["hpi_qoq"].rolling(4).mean()

    df["mortgage_spread"] = df["mortgage_30yr"] - df["ten_year"]
    df["yield_curve"] = df["ten_year"] - df["fed_funds"]
    df["mortgage_change_1q"] = df["mortgage_30yr"].diff()
    df["mortgage_change_4q"] = df["mortgage_30yr"].diff(4)
    df["ten_year_change_4q"] = df["ten_year"].diff(4)

    df["inflation_yoy"] = df["cpi"].pct_change(4)
    df["inflation_trend"] = df["inflation_yoy"].diff(2)
    df["national_payroll_growth_yoy"] = df["national_payrolls"].pct_change(4)
    df["national_unemployment_change_1yr"] = df["national_unemployment"].diff(4)

    if "metro_unemployment" in df.columns:
        df["metro_unemployment_change_1yr"] = df["metro_unemployment"].diff(4)
    if "metro_payrolls" in df.columns:
        df["metro_payroll_growth_yoy"] = df["metro_payrolls"].pct_change(4)
    if "metro_labor_force" in df.columns:
        df["metro_labor_force_growth_yoy"] = df["metro_labor_force"].pct_change(4)
    if "metro_building_permits" in df.columns:
        df["metro_permits_growth_yoy"] = df["metro_building_permits"].pct_change(4)

    if "composite_county_hpi_norm" in df.columns:
        df["composite_county_hpi_yoy"] = df["composite_county_hpi_norm"].pct_change(4)
    if "composite_county_active_listings" in df.columns:
        df["composite_active_listings_yoy"] = df["composite_county_active_listings"].pct_change(4)
    if "composite_county_median_listing_price" in df.columns:
        df["composite_listing_price_yoy"] = df["composite_county_median_listing_price"].pct_change(4)
    if "composite_county_permits" in df.columns:
        df["composite_county_permits_yoy"] = df["composite_county_permits"].pct_change(4)

    df["starts_growth_yoy"] = df["housing_starts"].pct_change(4)
    df["permits_growth_yoy"] = df["building_permits"].pct_change(4)
    df["months_supply_change_1yr"] = df["months_supply"].diff(4)
    df["new_home_sales_yoy"] = df["new_home_sales"].pct_change(4)
    df["consumer_sentiment_change"] = df["consumer_sentiment"].diff(4)

    if "zillow_zhvi" in df.columns:
        df["zillow_zhvi_yoy"] = df["zillow_zhvi"].pct_change(4)
        df["zillow_zhvi_3yr_growth"] = df["zillow_zhvi"].pct_change(12)
    if "zillow_zori" in df.columns:
        df["zillow_zori_yoy"] = df["zillow_zori"].pct_change(4)
    if "zillow_zhvi" in df.columns and "zillow_zori" in df.columns:
        df["rent_to_price_ratio"] = (df["zillow_zori"] * 12) / df["zillow_zhvi"]
        df["rent_to_price_ratio_change_1yr"] = df["rent_to_price_ratio"].diff(4)

    if "realtor_active_listings" in df.columns:
        df["realtor_active_listings_yoy"] = df["realtor_active_listings"].pct_change(4)
    if "realtor_new_listings" in df.columns:
        df["realtor_new_listings_yoy"] = df["realtor_new_listings"].pct_change(4)
    if "realtor_median_listing_price" in df.columns:
        df["realtor_listing_price_yoy"] = df["realtor_median_listing_price"].pct_change(4)
    if "realtor_median_days_on_market" in df.columns:
        df["realtor_dom_change_1yr"] = df["realtor_median_days_on_market"].diff(4)
    if "realtor_price_reduction_share" in df.columns:
        df["realtor_price_reduction_change_1yr"] = df["realtor_price_reduction_share"].diff(4)

    if "zillow_zhvi" in df.columns:
        df["estimated_home_price"] = df["zillow_zhvi"]
    elif "realtor_median_listing_price" in df.columns:
        df["estimated_home_price"] = df["realtor_median_listing_price"]
    elif "composite_county_median_listing_price" in df.columns:
        df["estimated_home_price"] = df["composite_county_median_listing_price"]
    else:
        df["estimated_home_price"] = np.nan

    if "estimated_home_price" in df.columns:
        principal = df["estimated_home_price"] * 0.80
        df["estimated_monthly_pi_payment"] = mortgage_payment(principal, df["mortgage_30yr"])

    if "median_household_income" in df.columns and "estimated_monthly_pi_payment" in df.columns:
        monthly_income = df["median_household_income"] / 12
        df["payment_to_income_ratio"] = df["estimated_monthly_pi_payment"] / monthly_income
        df["payment_to_income_change_1yr"] = df["payment_to_income_ratio"].diff(4)

    df["target_4q_growth"] = df["hpi"].shift(-4) / df["hpi"] - 1
    return df

def get_features(df: pd.DataFrame) -> list[str]:
    candidates = [
        "hpi_qoq", "hpi_yoy", "hpi_3yr_growth", "hpi_5yr_growth",
        "hpi_volatility_2yr", "hpi_momentum_4q",
        "mortgage_30yr", "mortgage_spread", "yield_curve",
        "mortgage_change_1q", "mortgage_change_4q", "ten_year", "ten_year_change_4q", "fed_funds",
        "inflation_yoy", "inflation_trend", "national_unemployment", "national_unemployment_change_1yr",
        "national_payroll_growth_yoy", "consumer_sentiment", "consumer_sentiment_change",
        "housing_starts", "starts_growth_yoy", "building_permits", "permits_growth_yoy",
        "months_supply", "months_supply_change_1yr", "new_home_sales_yoy",
        "metro_unemployment", "metro_unemployment_change_1yr",
        "metro_payroll_growth_yoy", "metro_labor_force_growth_yoy",
        "metro_building_permits", "metro_permits_growth_yoy",
        "composite_county_hpi_norm", "composite_county_hpi_yoy",
        "composite_county_active_listings", "composite_active_listings_yoy",
        "composite_county_median_listing_price", "composite_listing_price_yoy",
        "composite_county_permits", "composite_county_permits_yoy",
        "zillow_zhvi", "zillow_zhvi_yoy", "zillow_zhvi_3yr_growth",
        "zillow_zori", "zillow_zori_yoy", "rent_to_price_ratio", "rent_to_price_ratio_change_1yr",
        "realtor_active_listings", "realtor_active_listings_yoy",
        "realtor_new_listings", "realtor_new_listings_yoy",
        "realtor_median_listing_price", "realtor_listing_price_yoy",
        "realtor_median_days_on_market", "realtor_dom_change_1yr",
        "realtor_price_reduction_share", "realtor_price_reduction_change_1yr",
        "estimated_home_price", "estimated_monthly_pi_payment",
        "median_household_income", "payment_to_income_ratio", "payment_to_income_change_1yr",
    ]
    return [c for c in candidates if c in df.columns and df[c].isna().mean() <= 0.40]