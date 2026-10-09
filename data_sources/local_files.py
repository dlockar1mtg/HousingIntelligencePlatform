from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path

from config.markets import MARKETS
from config.utils import INPUT_DIR, clean_name, is_v11, is_v11_1, log

# V11.1 (audit finding 4): an ACS 5-year estimate is dated 31 December of its last year but released about
# twelve months later (ACS 2024 5-year: December 2025). Date each value when it became available.
ACS_RELEASE_LAG_MONTHS = 12

def detect_date_column(df: pd.DataFrame):
    candidates = ["date", "Date", "period", "Period", "month", "Month", "quarter", "Quarter", "time", "Time", "observation_date"]
    for c in candidates:
        if c in df.columns:
            return c
    for c in df.columns:
        if any(k in c.lower() for k in ["date", "period", "month"]):
            return c
    return None

def parse_date_series(series: pd.Series) -> pd.Series:
    as_str = series.astype(str).str.strip()
    yyyymm = pd.to_datetime(as_str, format="%Y%m", errors="coerce")
    regular = pd.to_datetime(series, errors="coerce")
    return yyyymm.fillna(regular)

def infer_market_column(df: pd.DataFrame):
    likely = [
        "market", "Market", "RegionName", "region_name", "region", "Region",
        "CountyName", "county_name", "County", "Metro", "metro", "msa", "MSA",
        "cbsa_title", "CBSA_TITLE", "cbsa", "CBSA", "Name", "name",
    ]
    for c in likely:
        if c in df.columns:
            return c
    for c in df.columns:
        cl = c.lower()
        if any(k in cl for k in ["market", "region", "county", "metro", "msa", "cbsa", "name", "title"]):
            return c
    return None

def market_from_text(value) -> str | None:
    cleaned = clean_name(value)
    for market, config in MARKETS.items():
        for alias in [clean_name(a) for a in config.get("aliases", [])]:
            if alias and alias in cleaned:
                return market
    return None

def market_from_metro_name(value) -> str | None:
    """V11: a metro-level file row belongs to a market only if its name is one of the market's metro names."""
    if not is_v11():
        return market_from_text(value)
    cleaned = clean_name(value)
    for market, config in MARKETS.items():
        if cleaned in config.get("metro_names", []):
            return market
    return None

def find_input_files(keywords: list[str]) -> list[Path]:
    return [p for p in INPUT_DIR.glob("*.csv") if any(k.lower() in p.name.lower() for k in keywords)]

def load_wide_zillow_file(path: Path, value_name: str) -> pd.DataFrame:
    try:
        raw = pd.read_csv(path)
    except Exception as exc:
        log(f"Could not read Zillow file {path.name}: {exc}")
        return pd.DataFrame()

    market_col = infer_market_column(raw)
    if market_col is None:
        log(f"Skipping {path.name}: could not infer market column.")
        return pd.DataFrame()

    raw["market"] = raw[market_col].apply(market_from_metro_name)
    raw = raw.dropna(subset=["market"])
    if raw.empty:
        return pd.DataFrame()

    metadata_cols = {"RegionID", "SizeRank", "RegionName", "RegionType", "StateName", "State", "Metro", "CountyName", "market"}
    date_cols = []
    for col in raw.columns:
        if col in metadata_cols:
            continue
        if pd.notna(pd.to_datetime(str(col), errors="coerce")):
            date_cols.append(col)

    if not date_cols:
        log(f"Skipping {path.name}: no date columns found.")
        return pd.DataFrame()

    melted = raw[["market"] + date_cols].melt(id_vars=["market"], var_name="date", value_name=value_name)
    melted["date"] = pd.to_datetime(melted["date"], errors="coerce")
    melted[value_name] = pd.to_numeric(melted[value_name], errors="coerce")
    melted = melted.dropna(subset=["date", value_name])

    q = melted.set_index("date").groupby("market")[value_name].resample("QE").mean().reset_index()
    return q

def load_zillow_layer() -> pd.DataFrame:
    frames = []

    for path in find_input_files(["zhvi"]):
        log(f"Loading optional Zillow ZHVI file: {path.name}")
        df = load_wide_zillow_file(path, "zillow_zhvi")
        if not df.empty:
            frames.append(df)

    for path in find_input_files(["zori"]):
        log(f"Loading optional Zillow ZORI file: {path.name}")
        df = load_wide_zillow_file(path, "zillow_zori")
        if not df.empty:
            frames.append(df)

    if not frames:
        log("No optional Zillow input files found.")
        return pd.DataFrame()

    combined = None
    for frame in frames:
        combined = frame if combined is None else combined.merge(frame, on=["date", "market"], how="outer")

    outputs = []
    for market in combined["market"].dropna().unique():
        m = combined[combined["market"] == market].set_index("date").sort_index()
        q = m.select_dtypes(include=[np.number]).resample("QE").mean().ffill()
        q["market"] = market
        outputs.append(q)

    return pd.concat(outputs) if outputs else pd.DataFrame()

def standardize_realtor_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {}
    for col in df.columns:
        cl = col.lower().strip()

        if cl in ["active_listing_count", "active_listings", "inventory", "total_listing_count"]:
            mapping[col] = "realtor_active_listings"
        elif "active" in cl and "listing" in cl and "yy" not in cl and "mm" not in cl:
            mapping[col] = "realtor_active_listings"

        elif cl in ["new_listing_count", "new_listings"]:
            mapping[col] = "realtor_new_listings"
        elif "new" in cl and "listing" in cl and "yy" not in cl and "mm" not in cl:
            mapping[col] = "realtor_new_listings"

        elif cl in ["median_listing_price", "median_list_price"]:
            mapping[col] = "realtor_median_listing_price"
        elif "median" in cl and "list" in cl and "price" in cl and "yy" not in cl and "mm" not in cl:
            mapping[col] = "realtor_median_listing_price"

        elif "median_days_on_market" in cl or "days_on_market" in cl or "median_dom" in cl:
            if "yy" not in cl and "mm" not in cl:
                mapping[col] = "realtor_median_days_on_market"

        elif "price_reduced" in cl or "price_reduction" in cl or "price_cut" in cl:
            if "yy" not in cl and "mm" not in cl:
                mapping[col] = "realtor_price_reduction_share"

    return df.rename(columns=mapping)

def load_realtor_layer() -> pd.DataFrame:
    files = find_input_files(["realtor", "rdc", "market_hotness", "inventory"])
    frames = []

    for path in files:
        log(f"Loading optional Realtor file: {path.name}")
        try:
            raw = pd.read_csv(path)
        except Exception as exc:
            log(f"Could not read Realtor file {path.name}: {exc}")
            continue

        raw = standardize_realtor_columns(raw)
        date_col = detect_date_column(raw)
        market_col = infer_market_column(raw)

        if date_col is None or market_col is None:
            log(f"Skipping {path.name}: could not detect date or market column.")
            log(f"Available columns: {list(raw.columns)}")
            continue

        raw["date"] = parse_date_series(raw[date_col])
        raw["market"] = raw[market_col].apply(market_from_metro_name)
        raw = raw.dropna(subset=["date", "market"])

        metrics = [
            "realtor_active_listings", "realtor_new_listings",
            "realtor_median_listing_price", "realtor_median_days_on_market",
            "realtor_price_reduction_share",
        ]
        existing = [c for c in metrics if c in raw.columns]
        if not existing:
            log(f"Skipping {path.name}: no recognized Realtor metrics found.")
            continue

        frame = raw[["market", "date"] + existing].copy()

        deduped = [frame[["market", "date"]]]
        for metric in existing:
            selected = frame.loc[:, frame.columns == metric]
            if isinstance(selected, pd.DataFrame) and selected.shape[1] > 1:
                converted = selected.apply(lambda s: pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False), errors="coerce"))
                series = converted.bfill(axis=1).iloc[:, 0]
            else:
                series = frame[metric]
                if isinstance(series, pd.DataFrame):
                    series = series.iloc[:, 0]
                series = pd.to_numeric(series.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False), errors="coerce")
            deduped.append(pd.DataFrame({metric: series}, index=frame.index))

        frames.append(pd.concat(deduped, axis=1))

    if not frames:
        log("No optional Realtor input files found.")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    outputs = []
    for market in combined["market"].dropna().unique():
        m = combined[combined["market"] == market].set_index("date").sort_index()
        q = m.select_dtypes(include=[np.number]).resample("QE").mean().ffill()
        q["market"] = market
        outputs.append(q)

    return pd.concat(outputs) if outputs else pd.DataFrame()

def load_affordability_layer() -> pd.DataFrame:
    files = find_input_files(["income", "affordability", "census"])
    frames = []

    for path in files:
        log(f"Loading optional affordability/Census file: {path.name}")
        try:
            raw = pd.read_csv(path)
        except Exception as exc:
            log(f"Could not read affordability file {path.name}: {exc}")
            continue

        if "county" in raw.columns and path.name.lower() != "census_income.csv":
            log(f"Skipping {path.name}: county detail file, not market-level affordability file.")
            continue

        date_col = detect_date_column(raw)
        market_col = infer_market_column(raw)

        if date_col is None or market_col is None:
            log(f"Skipping {path.name}: missing date or market column.")
            log(f"Available columns: {list(raw.columns)}")
            continue

        raw["date"] = parse_date_series(raw[date_col])
        raw["market"] = raw[market_col] if market_col.lower() == "market" else raw[market_col].apply(market_from_text)

        rename = {}
        for col in raw.columns:
            if col.lower() in ["median_household_income", "household_income", "median_income", "income"]:
                rename[col] = "median_household_income"
        raw = raw.rename(columns=rename)

        if "median_household_income" not in raw.columns:
            log(f"Skipping {path.name}: no income column detected.")
            continue

        raw["median_household_income"] = pd.to_numeric(raw["median_household_income"].astype(str).str.replace(",", "", regex=False), errors="coerce")
        raw = raw.dropna(subset=["date", "market", "median_household_income"])
        raw = raw[raw["market"].isin(MARKETS.keys())]
        if is_v11_1():
            raw["date"] = raw["date"] + pd.DateOffset(months=ACS_RELEASE_LAG_MONTHS)

        if raw.empty:
            log(f"Skipping {path.name}: no rows matched configured market names.")
            continue

        frames.append(raw[["date", "market", "median_household_income"]])

    if not frames:
        log("No optional affordability/Census input files found.")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    outputs = []
    for market in combined["market"].unique():
        m = combined[combined["market"] == market].set_index("date").sort_index()
        q = m[["median_household_income"]].resample("QE").mean().ffill()
        if not is_v11():
            q = q.bfill()
        q["market"] = market
        outputs.append(q)

    return pd.concat(outputs)

def merge_optional_layer(base: pd.DataFrame, market_name: str, optional: pd.DataFrame) -> pd.DataFrame:
    if optional.empty or "market" not in optional.columns:
        return base
    m = optional[optional["market"] == market_name].drop(columns=["market"], errors="ignore").sort_index()
    if m.empty:
        return base

    # V6 fix: align annual/irregular optional data to the full quarterly model index.
    # This prevents Census income from disappearing because it only has one annual row.
    m = m[~m.index.duplicated(keep="last")]
    if is_v11():                                   # V11: carry values forward only; nothing before a source starts
        m = m.reindex(base.index.union(m.index)).sort_index().ffill()
        m = m.reindex(base.index).ffill()
    else:
        m = m.reindex(base.index.union(m.index)).sort_index().ffill().bfill()
        m = m.reindex(base.index).ffill().bfill()

    return base.join(m, how="left")