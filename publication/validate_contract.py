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
    if contract.get("model_version") not in ("V10", "V11"):
        raise ContractError("unknown model_version")
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
        if contract["model_version"] == "V11" and (m.get("calibration") or {}).get("in_sample") is not False:
            raise ContractError(f"{name}: V11 publishes only the out-of-sample calibration")
        if not -0.5 < float(m["predicted_12m_growth"]) < 0.5:
            raise ContractError(f"{name}: predicted growth out of range")


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
