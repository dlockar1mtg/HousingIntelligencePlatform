# V11 results: V10 and V11 on the same inputs (2026-10-08)

Registered beforehand in `docs/V11_PLAN.md`. Both versions ran on the same frozen inputs: the FRED snapshot
taken 2026-10-08 13:18 UTC (`data/snapshot/`), the baseline Zillow/Realtor.com files, and Census income as
each version reads it (V10 uses one ACS year; V11 uses the yearly ACS 5-year series from 2009). The numbers
come from `scripts/compare_versions.py`, and the full output is in `V11_RESULTS.json`.

## Verdict

- **V11 is adopted.** Changes 1–5 are implemented as written and the tests pass. Production now runs V11
  (`config/settings.json` `model_version`). V10 still reproduces the 2026-09-13 baseline exactly when
  `HOUSING_MODEL_VERSION=V10` is set; the reproduce-baseline workflow and the baseline tests pin it.
- **Calibration FAILS out of sample in both markets, and failed under V10 too.** The Entry Score is not a
  validated timing signal. The contract publishes this result in place of V10's in-sample one.

## The current state each version reports

| | V10 | V11 |
|---|---|---|
| Quarter described | 2025-06-30 (15 months old) | **2026-06-30** (newest quarter with data) |
| Wichita | 49.9 Neutral / Fair Value, +3.0% next 12 months | **42.5 Slight Wait, +1.4%** |
| DFW | 45.8 Slight Wait, +0.7% | **41.1 Slight Wait, +0.6%** |
| Wichita typical home value (Zillow) | $197,479 | **$226,015** |
| DFW typical home value (Zillow) | $280,794 | **$366,794** |
| DFW payment-to-income | 0.191 | **0.240** |

`compare_versions.py` scores the latest quarter against a history of final-model predictions. Production
(`run_forecast.py`) uses walk-forward predictions for the history behind each percentile, as change 4 specifies.
So the published V11 scores differ slightly. The PR's live-FRED V11 check gave **Wichita 44.6 and DFW 42.0**,
both still Slight Wait, with the same forecasts, errors and calibration.

The home values show the alias problem directly. V10's "Wichita" averaged Wichita, KS with Wichita Falls, TX,
and its "DFW" mixed Dallas with Huntsville, Fort Collins, Johnson City, Parkersburg and others. V11 reads only
the real metros. The 2025-06-30 forecast that V10 published on 2026-09-13 can now be checked against what actually happened
over those 12 months: Wichita +4.5% actual vs +2.9% predicted, DFW +0.6% actual vs +0.7% predicted.

## Accuracy of the 12-month forecast (walk-forward, 4-quarter gap; reported, not gated)

| | V10 as published (gap 0) | V10 honest (gap 3) | V11 (gap 3) |
|---|---|---|---|
| Wichita: quarters / mean abs error / direction | 42 / 2.2% / 100% | 42 / 3.3% / 100% | 62 / **2.7%** / 81% |
| DFW | 42 / 2.9% / 98% | 42 / 4.9% / 98% | 62 / **4.3%** / 85% |

V10's published error was optimistic: the same model scored with the gap is about 50–70% worse. V11 tests 20
more quarters per market, reaching back into 2010–2014 when prices fell or stalled, because it no longer drops
quarters that lack the late-starting optional layers. Direction accuracy is lower there for that reason: V10's
test window was almost all rising prices.

## Out-of-sample calibration (the registered test)

The test uses point-in-time Entry Scores with walk-forward momentum against the realized next-12-month HPI
growth. PASS needs ≥ 40 quarters, rank correlation ≥ 0.10, and growth at Neutral-or-better ≥ growth below.

| | Quarters | Rank correlation | Growth after Neutral-or-better | Growth after lower scores | Status |
|---|---|---|---|---|---|
| V10 Wichita | 42 | −0.38 | 5.4% | 7.2% | FAIL |
| V10 DFW | 42 | +0.03 | 8.4% | 7.3% | FAIL |
| **V11 Wichita** | 62 | **−0.43** | 3.6% | 7.9% | **FAIL** |
| **V11 DFW** | 62 | **−0.12** | 5.3% | 9.3% | **FAIL** |

So higher Entry Scores were followed by *slower* price growth, not faster. V10's in-sample calibration PASS for DFW
does not survive an honest test.

### Why (after-results diagnostic, no change made)

This diagnostic was run after seeing the results, to understand them. It does not change the model. It gives
the rank correlation of each V11 component (point in time, out of sample) with the next 12 months' growth:

| Component (weight) | Wichita | DFW |
|---|---|---|
| Price momentum: the model's forecast (.18) | **+0.33** | **+0.58** |
| Economy (.12) | +0.47 | +0.28 |
| Valuation: slower recent price growth scores higher (.20) | **−0.75** | **−0.69** |
| Supply: more listings scores higher (.18) | −0.04 | −0.64 |
| Affordability (.16) | −0.51 | −0.18 |
| Mortgage (.10) | −0.30 | +0.28 |
| Risk (.06) | −0.30 | +0.57 |

The random forest's own forecast ranks future growth well out of sample. The Entry Score dilutes it with
components that describe buyer conditions: cooling prices, more supply, better affordability. Those conditions
come before *slower* appreciation, because house prices have momentum. The score therefore describes a buyer's
market well, but it does not tell you when prices are about to rise. A possible V12 could separate the two
questions ("how good are conditions for a buyer" and "how fast will prices move"). That would be a new
registered change, not something adopted here.

### Other consequence (observed, kept)

V10's rule keeps a feature only if ≤ 40% of its rows are missing. With no back-filling, the layers that start
late fail that rule: Realtor.com (2016), county listings (2016) and some ZORI rows. V11 trains on 43 features
instead of 62. Those layers still feed the Entry Score components where they exist. They are listed in the
contract as `SHORT_HISTORY_LAYERS_LEFT_OUT_OF_THE_MODEL`.

## What the contract (1.1.0) now says

- `model_version` V11, and `market_state_as_of` is the newest quarter. `prediction_basis` is `FINAL_MODEL`:
  the model was trained on every realized quarter, and this quarter's outcome is not known yet.
- `calibration`: `in_sample: false`, the method, the quarter count, both growth means and the pass marks.
  The validator refuses a V11 contract carrying an in-sample calibration.
- `walk_forward`: quarters, `gap_quarters: 3`, mean absolute error and direction accuracy.
- `known_issues`: `ENTRY_SCORE_IS_NOT_A_VALIDATED_TIMING_SIGNAL` and `SHORT_HISTORY_LAYERS_LEFT_OUT_OF_THE_MODEL`.
  The five V10 findings are fixed.
