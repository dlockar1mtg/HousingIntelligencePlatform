from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime

import pandas as pd

from config.markets import MARKETS
from config.utils import INPUT_DIR, OUTPUT_DIR, get_census_api_key, log

CURRENT_YEAR = datetime.now().year
ACS_YEARS_TO_TRY = list(range(CURRENT_YEAR - 1, 2015, -1))

def split_fips(fips: str):
    return fips[:2], fips[2:]

def census_api_url(year: int, state: str, county: str, api_key: str) -> str:
    params = {
        "get": "NAME,B19013_001E,B01003_001E",
        "for": f"county:{county}",
        "in": f"state:{state}",
        "key": api_key,
    }
    return f"https://api.census.gov/data/{year}/acs/acs5?{urllib.parse.urlencode(params)}"

def fetch_census_county(year: int, fips: str, api_key: str):
    state, county = split_fips(fips)
    url = census_api_url(year, state, county, api_key)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace").strip()

        if not raw.startswith("["):
            return None

        data = json.loads(raw)
        if len(data) < 2:
            return None

        row = dict(zip(data[0], data[1]))
        income = pd.to_numeric(row.get("B19013_001E"), errors="coerce")
        population = pd.to_numeric(row.get("B01003_001E"), errors="coerce")

        if pd.isna(income) or income <= 0 or pd.isna(population) or population <= 0:
            return None

        return {
            "year": year,
            "date": f"{year}-12-31",
            "fips": fips,
            "name": row.get("NAME"),
            "median_household_income": float(income),
            "population": float(population),
            "source": f"ACS {year} 5-year",
        }
    except Exception:
        return None

def market_income_rows(county_df: pd.DataFrame) -> pd.DataFrame:
    """Population-weighted market income, one row per market and ACS year."""
    rows = []
    for (market_name, year), group in county_df.groupby(["market", "year"]):
        valid = group.dropna(subset=["median_household_income", "population"])
        if valid.empty:
            continue
        weighted = (valid["median_household_income"] * valid["population"]).sum() / valid["population"].sum()
        rows.append({"date": f"{int(year)}-12-31", "market": market_name, "median_household_income": round(weighted, 2),
                     "population_weighted": True, "counties": len(valid),
                     "source": f"ACS {int(year)} 5-year county-weighted composite"})
    return pd.DataFrame(rows)


class CensusCoverageError(RuntimeError):
    pass


def check_county_coverage(county_df: pd.DataFrame) -> None:
    """Audit finding 5: a market's income is a population-weighted average of its counties, so a year with
    some counties missing would silently describe a different area. Every configured county must be present
    in every ACS year that was downloaded; a year missing for all counties is allowed only at the newest end
    (a release not out yet). Raises CensusCoverageError otherwise."""
    if county_df.empty:
        raise CensusCoverageError("no Census county rows")
    years = sorted(int(y) for y in county_df["year"].unique())
    for market_name, market_config in MARKETS.items():
        expected = {c["fips"] for c in market_config["counties"].values()}
        got = county_df[county_df["market"] == market_name]
        for year in range(years[0], years[-1] + 1):
            have = set(got.loc[got["year"].astype(int) == year, "fips"].astype(str).str.zfill(5))
            if have != expected:
                short = sorted(expected - have)
                raise CensusCoverageError(f"{market_name} ACS {year}: {len(have)} of {len(expected)} counties"
                                          + (f" (missing {', '.join(short)})" if short else ""))


def download_census_income_history(first_year: int = 2009) -> pd.DataFrame:
    """V11: every ACS 5-year release from first_year, so affordability has real history."""
    api_key = get_census_api_key()
    if not api_key:
        raise RuntimeError("Census API key missing. Set CENSUS_API_KEY.")
    rows = []
    for market_name, market_config in MARKETS.items():
        for county_name, county_config in market_config["counties"].items():
            for year in range(first_year, CURRENT_YEAR):
                row = fetch_census_county(year, county_config["fips"], api_key)
                if row is not None:
                    rows.append({**row, "market": market_name, "county": county_name})
                time.sleep(0.05)
    if not rows:
        raise RuntimeError("No Census income rows downloaded.")
    county_df = pd.DataFrame(rows)
    check_county_coverage(county_df)          # before anything is written: a short year fails the refresh
    county_df.to_csv(INPUT_DIR / "census_income_county_detail.csv", index=False)
    market_df = market_income_rows(county_df)
    market_df.to_csv(INPUT_DIR / "census_income.csv", index=False)
    log(f"Census income history: {len(county_df)} county-years, {market_df['date'].min()} to {market_df['date'].max()}")
    return market_df


def download_census_income() -> pd.DataFrame:
    from config.utils import is_v11
    if is_v11():
        return download_census_income_history()
    api_key = get_census_api_key()
    if not api_key:
        raise RuntimeError(
            "Census API key missing. Add it to config/settings.json or set CENSUS_API_KEY."
        )

    log("\nDownloading Census ACS income data...")
    county_rows = []

    for market_name, market_config in MARKETS.items():
        for county_name, county_config in market_config["counties"].items():
            fips = county_config["fips"]
            found = False

            for year in ACS_YEARS_TO_TRY:
                row = fetch_census_county(year, fips, api_key)
                if row is not None:
                    row["market"] = market_name
                    row["county"] = county_name
                    county_rows.append(row)
                    log(f"  {market_name} | {county_name}: ACS {year}")
                    found = True
                    time.sleep(0.10)
                    break
                time.sleep(0.03)

            if not found:
                log(f"  WARNING: no Census row found for {market_name} | {county_name} | {fips}")

    if not county_rows:
        raise RuntimeError("No Census income rows downloaded.")

    county_df = pd.DataFrame(county_rows)
    county_path = INPUT_DIR / "census_income_county_detail.csv"
    county_df.to_csv(county_path, index=False)

    market_rows = []
    for market_name, group in county_df.groupby("market"):
        valid = group.dropna(subset=["median_household_income", "population"]).copy()
        weighted_income = (valid["median_household_income"] * valid["population"]).sum() / valid["population"].sum()
        latest_year = int(valid["year"].max())
        market_rows.append({
            "date": f"{latest_year}-12-31",
            "market": market_name,
            "median_household_income": round(weighted_income, 2),
            "population_weighted": True,
            "source": f"ACS {latest_year} 5-year county-weighted composite",
        })

    market_df = pd.DataFrame(market_rows)
    income_path = INPUT_DIR / "census_income.csv"
    market_df.to_csv(income_path, index=False)

    log(f"Created: {income_path}")
    log(f"Created: {county_path}")
    return market_df

def validate_inputs() -> pd.DataFrame:
    rows = []
    for name in ["zhvi_metro.csv", "zori_metro.csv", "realtor_inventory.csv", "census_income.csv", "census_income_county_detail.csv"]:
        path = INPUT_DIR / name
        status = "missing"
        columns = None
        rows_preview = None
        if path.exists():
            try:
                df = pd.read_csv(path, nrows=1000)
                status = "ok"
                columns = list(df.columns)
                rows_preview = "1000+" if len(df) == 1000 else len(df)
            except Exception as exc:
                status = f"error: {exc}"
        rows.append({"file": str(path), "status": status, "rows_preview": rows_preview, "columns": columns})

    validation = pd.DataFrame(rows)
    out = OUTPUT_DIR / "v6_data_update_validation.csv"
    validation.to_csv(out, index=False)
    log(f"Created: {out}")
    return validation