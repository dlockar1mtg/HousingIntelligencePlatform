"""housing_uip_contract.json: built from the V10 baseline run, validated, and refusing bad packages."""
import copy
import json
from pathlib import Path

import pytest

from publication.build_contract import build_contract, write_package
from publication.validate_contract import ContractError, validate_contract, validate_package

BASE = Path(__file__).resolve().parents[1] / "baseline" / "v10-2026-09-13" / "outputs"


@pytest.fixture
def contract():
    return build_contract(BASE, source_commit="abc123", run_id="1", generated_at="2026-10-07T00:00:00+00:00")


def test_baseline_contract_carries_both_markets_honestly(contract):
    m = {x["market"]: x for x in contract["markets"]}
    assert m["Wichita Composite"]["signal"] == "Neutral / Fair Value" and m["DFW Composite"]["signal"] == "Slight Wait"
    assert m["Wichita Composite"]["entry_score"] == pytest.approx(49.882, abs=0.001)
    assert m["Wichita Composite"]["market_state_as_of"] == "2025-06-30"
    assert m["Wichita Composite"]["months_behind_latest_input"] == 14          # inputs run to 2026-08-01
    assert m["Wichita Composite"]["calibration"]["status"] == "FAIL" and m["DFW Composite"]["calibration"]["status"] == "PASS"
    assert m["Wichita Composite"]["calibration"]["in_sample"] is True
    assert m["Wichita Composite"]["realized_growth_for_that_period"] == pytest.approx(0.0454, abs=0.0001)
    assert [o["months"] for o in m["DFW Composite"]["outlook"]] == [0, 6, 12, 18, 24, 30, 36]
    assert any(w.startswith("MARKET_STATE_OLDER_THAN_6_MONTHS") for w in contract["warnings"])
    assert contract["household"] is None and contract["automatic_execution_authorized"] is False
    json.dumps(contract)                                                      # strict JSON (no NaN)


def test_package_round_trip_and_tamper_detection(contract, tmp_path):
    write_package(tmp_path, contract)
    assert validate_package(tmp_path)["contract_version"] == "1.0.0"
    path = tmp_path / "housing_uip_contract.json"
    path.write_text(path.read_text().replace("Slight Wait", "Buy"))
    with pytest.raises(ContractError, match="digest"):
        validate_package(tmp_path)


@pytest.mark.parametrize("change,message", [
    (lambda c: c.update(automatic_execution_authorized=True), "automatic"),
    (lambda c: c.update(household={"income": 1}), "household"),
    (lambda c: c["markets"].pop(), "missing market"),
    (lambda c: c["markets"][0].update(signal="Moon"), "unknown signal"),
    (lambda c: c["markets"][0].update(entry_score=140), "out of range"),
])
def test_bad_contracts_are_refused(contract, change, message):
    bad = copy.deepcopy(contract)
    change(bad)
    with pytest.raises(ContractError, match=message):
        validate_contract(bad)
