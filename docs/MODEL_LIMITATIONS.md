# Model limitations

## Known from the V10 handoff
1. Only Wichita and DFW are configured.
2. Wichita's Entry Score fails the historical calibration check.
3. Calibration is a sanity check, not independent validation; a historical replay (2012, 2018, 2022) is needed.
4. The meaningful-window rule fires when any one criterion improves.
5. Trigger sensitivities are heuristic; joint scenarios are preferable.
6. Personal readiness is first-generation; PMI is approximate; "comfortable price" follows lender logic.
7. No individual-property analysis; no market-specific feature weights.

## Status (2026-10-08): fixed in V11
All five review findings below are fixed in V11, which production now runs. `docs/V11_RESULTS.md` has the
before/after numbers. V10 keeps them on purpose (`HOUSING_MODEL_VERSION=V10`), so the 2026-09-13 baseline
still reproduces. Two things remain, and the contract states both:
- **The Entry Score is not a validated timing signal.** In the out-of-sample test, higher scores came before
  *slower* price growth in both markets (rank correlation −0.43 Wichita, −0.12 DFW). The score describes buyer
  conditions; the model's own 12-month forecast is the part that ranks future growth.
- **Short-history layers are left out of the model.** Realtor.com and county listings start in 2016, and with
  no back-filling they fail V10's 40%-missing feature rule. They still feed the Entry Score where they exist.
Items 2–3 of the handoff list are superseded by the out-of-sample test.

## Found in the migration review (2026-10-07)
These were kept exactly as V10 behaves so the baseline reproduces. Each was fixed in V11 (above).

1. **The "latest" forecast is five quarters old.** `build_dataset` drops rows without a realized 4-quarter
   target, and `run_forecast` takes the last remaining row as "latest". In the 2026-09-13 run that row is
   **2025-06-30**: the Entry Scores (Wichita 49.9, DFW 45.8), the mortgage rate (6.79%, the Q2 2025 average)
   and the "next 12 months" growth (Wichita +2.9%, DFW +0.7%) all describe mid-2025, and the Monte Carlo
   starts from there. Those 12 months have already happened: Wichita's HPI actually rose 4.5% and DFW's 0.6%.
   Fix: train on rows with a realized target, then score the newest rows that have features.
2. **Alias matching pulls unrelated metros into both composites.** `market_from_text` matches aliases as
   substrings of the cleaned name, so county aliases like "hunt", "collin", "johnson", "parker" catch other
   metros. The Zillow, ZORI and Realtor.com layers for "DFW Composite" average Dallas with Huntsville AL,
   Huntington WV, Fort Collins CO, Johnson City TN, Parkersburg WV, Huntsville TX, Huntingdon PA, Huntington
   IN (and North Port–Sarasota FL in Realtor.com); "Wichita Composite" includes Wichita Falls TX. This changes
   the home values, rents, inventory and affordability the scores use (`tests/test_known_issues.py`).
3. **Walk-forward validation leaks the future.** Each test quarter trains on every earlier row, including
   the three just before it whose 4-quarter targets overlap the test window. The reported accuracy
   (MAE ~2.6%, 98.8% direction) is therefore optimistic. Fix: leave a 4-quarter gap.
4. **The calibration check is in-sample.** Entry Score components are percentile ranks over each market's
   full history (later data included), and the momentum component is the final model's in-sample
   prediction of the same target the calibration then compares against. DFW's PASS is therefore
   inflated. Fix: point-in-time scores and out-of-sample predictions, tested with a registered pass mark.
5. **Back-filling.** `df.ffill().bfill()` fills early rows with later values before features are built.
