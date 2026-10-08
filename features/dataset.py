from __future__ import annotations

import pandas as pd

from config.markets import MARKETS
from config.utils import log
from data_sources.fred_loader import (
    download_national, download_target_hpi, download_market_metro_series,
    download_county_layer
)
from data_sources.local_files import (
    load_zillow_layer, load_realtor_layer, load_affordability_layer,
    merge_optional_layer
)
from features.build_features import add_features

def build_dataset() -> tuple[pd.DataFrame, pd.DataFrame]:
    national = download_national()

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

        df = df.ffill().bfill()
        df["market"] = market_name
        df = add_features(df)

        required = ["hpi", "target_4q_growth", "mortgage_30yr", "ten_year", "fed_funds", "cpi"]
        df = df.dropna(subset=required)

        log(f"{market_name}: {df.shape[0]} usable rows")
        all_markets.append(df)

        if not county_drilldown.empty:
            all_drilldowns.append(county_drilldown)

    data = pd.concat(all_markets)
    drilldown = pd.concat(all_drilldowns) if all_drilldowns else pd.DataFrame()
    return data, drilldown