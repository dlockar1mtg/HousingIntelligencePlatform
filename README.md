# Housing Intelligence Platform

A governed housing-market forecasting and home-purchase decision system. It combines macroeconomic,
local housing, affordability, simulation and household financial data to estimate market opportunity,
purchase readiness, financing trade-offs and future entry conditions for the **Wichita** and
**Dallas–Fort Worth** composites. It publishes a small, versioned contract to the Universal Investment
Platform (UIP), where the Homestead page combines housing with the rest of the household plan.

Migrated from the local `HousingPredictorv6` project (V10) on 2026-10-07. See `docs/HANDOFF_2026-10-07.md`.

## Status

| Phase | What | State |
|---|---|---|
| 0–1 | Freeze V10 and import it unchanged | this repo |
| 2 | Reproduce the V10 run of 2026-09-13 | offline test passes; online workflow `Reproduce the V10 baseline` |
| 3 | Tests and CI | `Tests` workflow |
| 4 | `housing_uip_contract.json` (`publication/`, `publish_uip.py`) and the weekly `Housing production` workflow | built |
| 5 | UIP consumer (Homestead) | in the UIP repo |
| V11 | Fix the issues in `docs/MODEL_LIMITATIONS.md` | done (`docs/V11_RESULTS.md`) |
| V11.1 | Amendments from the 2026-10-09 system audit | production (`docs/V11_RESULTS.md`, "V11.1 amendments") |

## Running

```bash
pip install -r requirements-dev.txt
python update_data.py      # Zillow, Realtor.com and Census refresh (needs CENSUS_API_KEY)
python -m rates.outlook --out outputs/rates_outlook.json   # V11.1's Monte Carlo draws rates from it
python run_forecast.py     # config/settings.json model_version (V11.1); HOUSING_MODEL_VERSION=V10 / V11 for the older versions
python publish_uip.py      # build and validate uip-package/ (contract + manifest)
python -m pytest -q
```

`CENSUS_API_KEY` comes from the environment (a GitHub Actions secret in CI). `config/settings.json`
holds only model settings. A personal profile, if used locally, goes in `inputs/personal_profile.json`,
which is ignored by git; `inputs/personal_profile_template.json` shows its shape with made-up values.
Long term the household side comes from the UIP instead.

## Layout

The V10 module layout is kept as it was (`config/`, `data_sources/`, `features/`, `models/`, `scoring/`,
`decision/`, `validation/`, `exports/`, `run_forecast.py`, `update_data.py`). `baseline/v10-2026-09-13/`
holds the run used for the reproduction gate: market-side outputs and the input files filtered to the rows
V10 actually reads (verified to give identical data layers). Household outputs are not committed.
