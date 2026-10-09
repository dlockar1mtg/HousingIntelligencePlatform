from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from pandas_datareader import data as web

from config.markets import NATIONAL_SERIES
from config.utils import is_v11_1, log, load_settings

START_DATE = load_settings().get("start_date", "2000-01-01")

SNAPSHOT_DIR = os.environ.get("HOUSING_FRED_SNAPSHOT", "").strip()   # read raw series from here (reproducible runs)
SAVE_DIR = os.environ.get("HOUSING_FRED_SAVE", "").strip()           # save each raw series here after downloading


# Series the model cannot run without: a run fails when one is missing (V11.1 audit amendment, finding 5).
CORE_SERIES = {"MORTGAGE30US", "DGS10", "FEDFUNDS", "CPIAUCSL"}      # plus each market's target HPI series

# Release lags in quarters (V11.1 audit amendment, finding 4). FRED dates an annual county observation on
# 1 January of its year, but FHFA's annual county HPI and Census's annual county permits for year Y appear
# around May of Y+1: a value dated Q1 Y is first usable in Q2 Y+1, five quarters later.
COUNTY_RELEASE_LAG_QUARTERS = {"county_hpi": 5, "county_permits": 5}

MISSING: list[dict] = []          # every series that could not be read this run: {series_id, name, core, error}
OBSERVED: dict[str, str] = {}     # series_id -> date of its newest raw observation
_RAW: dict[str, pd.DataFrame] = {}


class MissingSeriesError(RuntimeError):
    pass


def reset_run_state() -> None:
    MISSING.clear()
    OBSERVED.clear()
    _RAW.clear()


def _raw_series(series_id: str) -> pd.DataFrame:
    if series_id in _RAW:
        return _RAW[series_id]
    df = _read_raw(series_id)
    _RAW[series_id] = df
    s = pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna() if len(df.columns) else pd.Series(dtype=float)
    if len(s):
        OBSERVED[series_id] = pd.Timestamp(s.index.max()).date().isoformat()
    return df


def _read_raw(series_id: str) -> pd.DataFrame:
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


def fred(series_id: str, name: str, freq: str = "QE", core: bool | None = None, lag_quarters: int = 0) -> pd.DataFrame | None:
    """One FRED series as quarterly means. A failure is recorded in MISSING (published in the contract's
    warnings); a core series raises MissingSeriesError instead of being dropped."""
    core = series_id in CORE_SERIES if core is None else core
    try:
        log(f"{'Reading' if SNAPSHOT_DIR else 'Downloading'} {name}: {series_id}")
        df = _raw_series(series_id)
        df = df.resample(freq).mean()
        df.columns = [name]
        if lag_quarters:
            df = df.shift(lag_quarters, freq=freq)   # dated when it was published, not the period it describes
        return df
    except Exception as exc:
        log(f"Could not download {name} ({series_id}): {exc}")
        MISSING.append({"series_id": series_id, "name": name, "core": bool(core), "error": str(exc)[:200]})
        if core:
            raise MissingSeriesError(f"core series {series_id} ({name}) is missing: {exc}") from exc
        return None


def _value_on_or_before(s: pd.Series, when: pd.Timestamp) -> float | None:
    earlier = s.loc[:when]
    return float(earlier.iloc[-1]) if len(earlier) else None


def latest_rate_features() -> dict:
    """V11.1 (finding 2): today's rate-family inputs for the scoring quarter, from the newest weekly / daily /
    monthly observations, with their changes over the preceding quarter and year on the same basis."""
    out = {}
    for name, sid, window_days in (("mortgage_30yr", "MORTGAGE30US", 0), ("ten_year", "DGS10", 7), ("fed_funds", "FEDFUNDS", 0)):
        raw = _raw_series(sid)
        s = pd.to_numeric(raw.iloc[:, 0], errors="coerce").dropna().sort_index()
        if s.empty:
            raise MissingSeriesError(f"core series {sid} has no observations")
        last = pd.Timestamp(s.index[-1])
        # The 10-year is daily: use its average over the last week, the same span as the weekly mortgage survey.
        series = s.rolling(f"{window_days}D").mean() if window_days else s
        value = float(series.iloc[-1])
        out[name] = {"series_id": sid, "date": last.date().isoformat(), "value": round(value, 4),
                     "basis": "7-day average of daily observations" if window_days else "latest observation",
                     "value_1q_earlier": _value_on_or_before(series, last - pd.Timedelta(days=91)),
                     "value_4q_earlier": _value_on_or_before(series, last - pd.Timedelta(days=365))}
    return out

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
        return fred(config["hpi_target_series"], "hpi", core=True)

    frames = []
    for component_name, sid in config["target_components"].items():
        df = fred(sid, component_name, core=True)   # a missing component would silently re-weight the target
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
            lag = COUNTY_RELEASE_LAG_QUARTERS.get(metric, 0) if is_v11_1() else 0
            df = fred(sid, f"{county_name}_{metric}", lag_quarters=lag)
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