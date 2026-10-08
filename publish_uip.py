"""Build and validate the UIP package from outputs/. Usage: python publish_uip.py [--outputs outputs] [--package uip-package]"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from publication.build_contract import build_contract, write_package
from publication.validate_contract import validate_package

ROOT = Path(__file__).resolve().parent


def commit() -> str:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "0000000"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs", type=Path, default=ROOT / "outputs")
    parser.add_argument("--package", type=Path, default=ROOT / "uip-package")
    args = parser.parse_args(argv)
    contract = build_contract(args.outputs, source_commit=commit(), run_id=os.environ.get("GITHUB_RUN_ID"))
    manifest = write_package(args.package, contract)
    validate_package(args.package)
    print(json.dumps({"package_id": manifest["package_id"], "markets": [(m["market"], m["entry_score"], m["signal"], m["market_state_as_of"]) for m in contract["markets"]],
                      "warnings": contract["warnings"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
