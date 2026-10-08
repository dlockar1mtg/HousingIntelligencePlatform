from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from pandas_datareader import data as web

from config.markets import NATIONAL_SERIES
from config.utils import log, load_settings

START_DATE = load_settings().get("start_date", "2000-01-01")

SNAPSHOT_DIR = os.environ.get("HOUSING_FRED_SNAPSHOT", "").strip()   # read raw series from here (reproducible runs)
SAVE_DIR = os.environ.get("HOUSING_FRED_SAVE", "").strip()           # save each raw series here after downloading


def _raw_series(series_id: str) -> pd.DataFrame:
    if SNAPSHOT_DIR:
        path = Path(SNAPSHOT_DIR) / f"{series_id}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{series_id} is not in the FRED snapshot")
        return pd.read_csv(path, index_col=0, parse_dates=True)
    df = web.DataReader(series_id, "fred", START_DATE)
    if SAVE_DIR:
        Path(SAVE_DIR).mkdir(parents=True, exist_ok=True)
        df.to_csv(Path(SAVE_DIR) / f"{series_id}.csv")
    return df


def fred(series_id: str, name: str, freq: str = "QE") -> pd.DataFrame | None:
    try:
        log(f"{'Reading' if SNAPSHOT_DIR else 'Downloading'} {name}: {series_id}")
        df = _raw_series(series_id)
        df = df.resample(freq).mean()
        df.columns = [name]
        return df
    except Exception as exc:
        log(f"Could not download {name} ({series_id}): {exc}")
        return None

def download_national() -> pd.DataFrame:
    frames = []
    for name, sid in NATIONAL_SERIES.items():
        df = fred(sid, name)
        if df is not None:
            frames.append(df)
    if not frames:
        raise RuntimeError("No national FRED series downloaded.")
    return pd.concat(frames, axis=1).ffill()

def download_target_hpi(config: dict) -> pd.DataFrame:
    if config.get("hpi_target_series"):
        return fred(config["hpi_target_series"], "hpi")

    frames = []
    for component_name, sid in config["target_components"].items():
        df = fred(sid, component_name)
        if df is not None:
            frames.append(df)

    if not frames:
        raise RuntimeError("No target HPI component series downloaded.")

    raw = pd.concat(frames, axis=1).ffill()
    weights = config["target_component_weights"]
    available = [c for c in raw.columns if c in weights]
    raw["hpi"] = sum(raw[c] * weights[c] for c in available) / sum(weights[c] for c in available)
    return raw[["hpi"]]

def county_series_ids(fips: str, use_listing_data: bool = True) -> dict:
    ids = {
        "county_hpi": f"ATNHPIUS{fips}A",
        "county_permits": f"BPPRIV0{fips}",
    }
    if use_listing_data:
        ids["county_active_listings"] = f"ACTLISCOU{fips}"
        ids["county_median_listing_price"] = f"MELIPRCOUNTY{fips}"
    return ids

def download_county_layer(market_name: str, counties: dict):
    import numpy as np

    county_frames = []
    drilldown_frames = []

    for county_name, county_config in counties.items():
        fips = county_config["fips"]
        use_listing_data = county_config.get("use_listing_data", True)

        pieces = []
        for metric, sid in county_series_ids(fips, use_listing_data).items():
            df = fred(sid, f"{county_name}_{metric}")
            if df is not None:
                df.columns = [metric]
                pieces.append(df)

        if not pieces:
            continue

        county = pd.concat(pieces, axis=1).ffill()
        county["county"] = county_name
        county["fips"] = fips
        county["market"] = market_name

        if "county_hpi" in county.columns:
            first_valid = county["county_hpi"].dropna()
            if not first_valid.empty:
                county["county_hpi_norm"] = county["county_hpi"] / first_valid.iloc[0] * 100
                county["county_hpi_yoy"] = county["county_hpi"].pct_change(4)

        if "county_active_listings" in county.columns:
            county["county_active_listings_yoy"] = county["county_active_listings"].pct_change(4)
        if "county_median_listing_price" in county.columns:
            county["county_listing_price_yoy"] = county["county_median_listing_price"].pct_change(4)
        if "county_permits" in county.columns:
            county["county_permits_yoy"] = county["county_permits"].pct_change(4)

        drilldown_frames.append(county.copy())
        numeric_cols = county.select_dtypes(include=[np.number]).columns.tolist()
        county_frames.append(county[numeric_cols].copy())

    if not county_frames:
        return pd.DataFrame(), pd.DataFrame()

    composite = pd.concat(county_frames).groupby(level=0).mean()
    composite.columns = [f"composite_{c}" for c in composite.columns]
    drilldown = pd.concat(drilldown_frames).reset_index().rename(columns={"index": "date"})
    return composite, drilldown

def download_market_metro_series(config: dict) -> pd.DataFrame:
    frames = []
    for key in ["metro_unemployment", "metro_payrolls", "metro_labor_force", "metro_building_permits"]:
        if key in config:
            df = fred(config[key], key)
            if df is not None:
                frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=1).ffill()