from __future__ import annotations

import pandas as pd

from config.markets import MARKETS
from config.utils import is_v11, is_v11_1, log
from data_sources.fred_loader import (
    download_national, download_target_hpi, download_market_metro_series,
    download_county_layer, latest_rate_features
)
from data_sources.local_files import (
    load_zillow_layer, load_realtor_layer, load_affordability_layer,
    merge_optional_layer
)
from features.build_features import add_features, apply_current_rates

def build_dataset() -> tuple[pd.DataFrame, pd.DataFrame]:
    national = download_national()
    rates = latest_rate_features() if is_v11_1() else None

    log("\nLoading optional local input layers...")
    zillow = load_zillow_layer()
    realtor = load_realtor_layer()
    affordability = load_affordability_layer()

    all_markets = []
    all_drilldowns = []

    for market_name, config in MARKETS.items():
        log(f"\nBuilding {market_name}")

        target = download_target_hpi(config)
        metro = download_market_metro_series(config)
        county_composite, county_drilldown = download_county_layer(market_name, config["counties"])

        df = target.join(national, how="left")
        if not metro.empty:
            df = df.join(metro, how="left")
        if not county_composite.empty:
            df = df.join(county_composite, how="left")

        df = merge_optional_layer(df, market_name, zillow)
        df = merge_optional_layer(df, market_name, realtor)
        df = merge_optional_layer(df, market_name, affordability)

        df = df.ffill() if is_v11() else df.ffill().bfill()
        df["market"] = market_name
        df = add_features(df)

        # V11 keeps the newest quarters, whose 4-quarter target is not realized yet: they are what gets scored.
        required = ["hpi", "mortgage_30yr", "ten_year", "fed_funds", "cpi"] + ([] if is_v11() else ["target_4q_growth"])
        df = df.dropna(subset=required)
        if rates is not None:
            df = apply_current_rates(df, rates)      # the scoring quarter only (V11.1, audit finding 2)

        log(f"{market_name}: {df.shape[0]} usable rows")
        all_markets.append(df)

        if not county_drilldown.empty:
            all_drilldowns.append(county_drilldown)

    data = pd.concat(all_markets)
    drilldown = pd.concat(all_drilldowns) if all_drilldowns else pd.DataFrame()
    return data, drilldown