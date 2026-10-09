"""Validate housing_uip_contract.json and its manifest before anything is published."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SIGNALS = {"Strong Buy", "Buy", "Slight Buy", "Neutral / Fair Value", "Slight Wait", "Wait", "Strong Wait / High Risk"}
REQUIRED_MARKETS = {"Wichita Composite", "DFW Composite"}


class ContractError(ValueError):
    pass


def validate_contract(contract: dict) -> None:
    if contract.get("contract_version", "").split(".")[0] != "1":
        raise ContractError("unsupported contract_version")
    if contract.get("domain") != "housing":
        raise ContractError("domain must be housing")
    if contract.get("automatic_execution_authorized") is not False:
        raise ContractError("automatic execution must be false")
    if contract.get("household") is not None:
        raise ContractError("household figures are not published in the housing contract")
    if contract.get("model_version") not in ("V10", "V11", "V11.1"):
        raise ContractError("unknown model_version")
    amended = contract["model_version"] == "V11.1"
    if amended:
        _validate_v11_1(contract)
    rates = contract.get("rates_outlook")
    if rates is not None:
        for row in rates.get("horizons") or []:
            if not 0 < float(row["center"]) < 25:
                raise ContractError("rates_outlook center out of range")
            if "p10" in row and not row["p10"] <= row["p50"] <= row["p90"]:
                raise ContractError("rates_outlook band is not ordered")
            if row.get("status") not in ("TESTED", "TOO_NARROW", "TOO_WIDE", "TOO_FEW_TESTS", "UNTESTED"):
                raise ContractError("rates_outlook status is unknown")
    markets = {m.get("market"): m for m in contract.get("markets") or []}
    missing = REQUIRED_MARKETS - set(markets)
    if missing:
        raise ContractError(f"missing market: {sorted(missing)[0]}")
    for name, m in markets.items():
        if not 0 <= float(m["entry_score"]) <= 100:
            raise ContractError(f"{name}: entry_score out of range")
        if m["signal"] not in SIGNALS:
            raise ContractError(f"{name}: unknown signal {m['signal']}")
        if not m.get("market_state_as_of"):
            raise ContractError(f"{name}: market_state_as_of is required")
        if (m.get("calibration") or {}).get("status") not in ("PASS", "FAIL"):
            raise ContractError(f"{name}: calibration status is required")
        if contract["model_version"] in ("V11", "V11.1") and (m.get("calibration") or {}).get("in_sample") is not False:
            raise ContractError(f"{name}: V11 publishes only the out-of-sample calibration")
        if not -0.5 < float(m["predicted_12m_growth"]) < 0.5:
            raise ContractError(f"{name}: predicted growth out of range")


def _validate_v11_1(contract: dict) -> None:
    """V11.1 (2026-10-09 audit): the scored rate is today's rate and agrees with the published outlook;
    no timing advice is published; the data ages are listed."""
    rf = (contract.get("rate_features_as_of") or {}).get("mortgage_30yr") or {}
    if not rf.get("date") or rf.get("value") is None:
        raise ContractError("V11.1 requires rate_features_as_of.mortgage_30yr")
    if not isinstance(contract.get("data_ages"), list):
        raise ContractError("V11.1 requires data_ages")
    weekly = ((contract.get("rates_outlook") or {}).get("mortgage_30yr_latest_weekly") or {})
    for m in contract.get("markets") or []:
        name = m.get("market")
        if m.get("best_window") is not None:
            raise ContractError(f"{name}: V11.1 publishes no best_window timing advice")
        rate = m.get("mortgage_30yr")
        if rate is None or abs(float(rate) - float(rf["value"])) > 0.001:
            raise ContractError(f"{name}: scored mortgage rate differs from rate_features_as_of")
        if weekly.get("rate") is not None:
            tolerance = 0.01 if weekly.get("date") == rf["date"] else 0.5
            if abs(float(rate) - float(weekly["rate"])) > tolerance:
                raise ContractError(f"{name}: scored mortgage rate {rate} disagrees with the rates outlook's {weekly['rate']}")
        tr = m.get("trigger") or {}
        if tr and tr.get("mortgage_rate_now") is not None and abs(float(tr["mortgage_rate_now"]) - float(rate)) > 0.001:
            raise ContractError(f"{name}: trigger is measured from a different mortgage rate")


def validate_package(directory: Path) -> dict:
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for f in manifest["files"]:
        data = (directory / f["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise ContractError(f"digest mismatch for {f['path']}")
    contract = json.loads((directory / "housing_uip_contract.json").read_text(encoding="utf-8"))
    validate_contract(contract)
    return contract
