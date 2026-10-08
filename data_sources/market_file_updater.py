from __future__ import annotations

import csv
import shutil
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config.utils import INPUT_DIR, OUTPUT_DIR, log


DATASETS = {
    "Zillow ZHVI": {
        "url": "https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
        "filename": "zhvi_metro.csv",
        "kind": "zillow",
    },
    "Zillow ZORI": {
        "url": "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_month.csv",
        "filename": "zori_metro.csv",
        "kind": "zillow",
    },
    "Realtor Inventory": {
        "url": "https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_Metro_History.csv",
        "filename": "realtor_inventory.csv",
        "kind": "realtor",
    },
}

USER_AGENT = "Mozilla/5.0 HousingPredictor/10.1"


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        if getattr(response, "status", 200) >= 400:
            raise RuntimeError(f"HTTP {response.status}")
        with destination.open("wb") as f:
            shutil.copyfileobj(response, f)


def _latest_zillow_date(df: pd.DataFrame) -> str:
    date_cols = []
    for c in df.columns:
        text = str(c)
        try:
            parsed = pd.to_datetime(text, format="%Y-%m-%d", errors="raise")
            date_cols.append(parsed)
        except Exception:
            continue
    if not date_cols:
        raise ValueError("No YYYY-MM-DD Zillow monthly columns were found.")
    return max(date_cols).strftime("%Y-%m-%d")


def _latest_realtor_date(df: pd.DataFrame) -> str:
    candidates = [
        "month_date_yyyymm",
        "month_date",
        "month",
    ]
    col = next((c for c in candidates if c in df.columns), None)
    if col is None:
        raise ValueError("Could not find a Realtor month column.")

    s = df[col].astype(str).str.strip()
    # Common Realtor history format: YYYYMM
    parsed = pd.to_datetime(s, format="%Y%m", errors="coerce")
    if parsed.isna().all():
        parsed = pd.to_datetime(s, errors="coerce")
    if parsed.isna().all():
        raise ValueError(f"Could not parse dates from Realtor column {col}.")
    return parsed.max().strftime("%Y-%m-%d")


def _validate_zillow(path: Path) -> dict:
    df = pd.read_csv(path)
    if len(df) < 50:
        raise ValueError(f"Zillow file has unexpectedly few rows ({len(df)}).")

    market_col = next(
        (c for c in ["RegionName", "region_name", "Region"] if c in df.columns),
        None,
    )
    if market_col is None:
        raise ValueError("Zillow RegionName column not found.")

    names = df[market_col].astype(str)
    has_wichita = names.str.contains("Wichita", case=False, na=False).any()
    has_dfw = names.str.contains(
        "Dallas-Fort Worth|Dallas.*Fort Worth|Dallas", case=False, regex=True, na=False
    ).any()

    if not has_wichita:
        raise ValueError("Wichita metro was not found in Zillow file.")
    if not has_dfw:
        raise ValueError("Dallas/DFW metro was not found in Zillow file.")

    return {
        "rows": len(df),
        "latest_observation": _latest_zillow_date(df),
        "wichita_coverage": "PASS",
        "dfw_coverage": "PASS",
    }


def _validate_realtor(path: Path) -> dict:
    df = pd.read_csv(path)
    if len(df) < 100:
        raise ValueError(f"Realtor file has unexpectedly few rows ({len(df)}).")

    market_col = next(
        (c for c in ["cbsa_title", "cbsa_name", "metro", "metro_name"] if c in df.columns),
        None,
    )
    if market_col is None:
        raise ValueError("Realtor metro/CBSA column not found.")

    names = df[market_col].astype(str)
    has_wichita = names.str.contains("Wichita", case=False, na=False).any()
    has_dfw = names.str.contains(
        "Dallas-Fort Worth|Dallas.*Fort Worth|Dallas", case=False, regex=True, na=False
    ).any()

    if not has_wichita:
        raise ValueError("Wichita metro was not found in Realtor file.")
    if not has_dfw:
        raise ValueError("Dallas/DFW metro was not found in Realtor file.")

    return {
        "rows": len(df),
        "latest_observation": _latest_realtor_date(df),
        "wichita_coverage": "PASS",
        "dfw_coverage": "PASS",
    }


def _validate(path: Path, kind: str) -> dict:
    if kind == "zillow":
        return _validate_zillow(path)
    if kind == "realtor":
        return _validate_realtor(path)
    raise ValueError(f"Unsupported dataset kind: {kind}")


def _backup_existing(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup_dir = INPUT_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = backup_dir / f"{path.stem}_{stamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def refresh_market_files() -> pd.DataFrame:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = []

    for dataset_name, cfg in DATASETS.items():
        final_path = INPUT_DIR / cfg["filename"]
        log(f"\nChecking {dataset_name}...")

        old_info = None
        if final_path.exists():
            try:
                old_info = _validate(final_path, cfg["kind"])
                log(
                    f"  Existing file valid; latest observation: "
                    f"{old_info['latest_observation']}"
                )
            except Exception as exc:
                log(f"  Existing file validation warning: {exc}")

        temp_path = Path(tempfile.gettempdir()) / (
            f"housingpredictor_{Path(cfg['filename']).stem}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.csv"
        )

        status = "UNCHANGED"
        action = "kept existing file"
        backup_path = None
        new_info = None
        error = ""

        try:
            log("  Downloading current official historical dataset...")
            _download(cfg["url"], temp_path)
            new_info = _validate(temp_path, cfg["kind"])
            log(
                f"  Download valid; latest observation: "
                f"{new_info['latest_observation']}"
            )

            old_date = (
                pd.to_datetime(old_info["latest_observation"])
                if old_info else pd.Timestamp.min
            )
            new_date = pd.to_datetime(new_info["latest_observation"])

            # Realtor and Zillow can revise historical observations even when the
            # latest month is unchanged. Always accept a valid official full-history
            # file when it is at least as current as the installed copy.
            if new_date >= old_date:
                backup_path = _backup_existing(final_path)
                shutil.move(str(temp_path), str(final_path))
                status = "UPDATED" if new_date > old_date else "REFRESHED"
                action = "installed validated official full-history file"
            else:
                status = "SKIPPED"
                action = "download was older than installed file; existing file preserved"

        except Exception as exc:
            error = str(exc)
            status = "FAILED-SAFE"
            action = "download/validation failed; existing file preserved"
            log(f"  WARNING: {dataset_name} refresh failed safely: {exc}")
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

        installed_info = None
        if final_path.exists():
            try:
                installed_info = _validate(final_path, cfg["kind"])
            except Exception as exc:
                error = f"{error}; installed validation: {exc}".strip("; ")

        results.append({
            "dataset": dataset_name,
            "file": cfg["filename"],
            "status": status,
            "action": action,
            "latest_observation": (
                installed_info["latest_observation"] if installed_info else None
            ),
            "rows": installed_info["rows"] if installed_info else None,
            "wichita_coverage": (
                installed_info["wichita_coverage"] if installed_info else "FAIL"
            ),
            "dfw_coverage": (
                installed_info["dfw_coverage"] if installed_info else "FAIL"
            ),
            "backup_created": str(backup_path) if backup_path else "",
            "source_url": cfg["url"],
            "error": error,
            "checked_utc": datetime.now(timezone.utc).isoformat(),
        })

    report = pd.DataFrame(results)
    report_path = OUTPUT_DIR / "v10_data_freshness_report.csv"
    report.to_csv(report_path, index=False)

    log("\nMarket data freshness report")
    cols = [
        "dataset", "status", "latest_observation",
        "wichita_coverage", "dfw_coverage"
    ]
    log(report[cols].to_string(index=False))

    safe = (
        report["wichita_coverage"].eq("PASS").all()
        and report["dfw_coverage"].eq("PASS").all()
        and ~report["status"].eq("FAILED-SAFE").all()
    )
    log(f"\nSAFE TO RUN FORECAST: {'YES' if safe else 'REVIEW REPORT'}")
    log(f"Freshness report: {report_path}")

    return report