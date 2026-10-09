# Methodology (V10)

1. Download FRED national series (mortgage rate, 10-year, fed funds, CPI, unemployment, payrolls,
   sentiment, starts, permits, months supply, new-home sales) and each market's HPI, metro labour and
   county series (`data_sources/fred_loader.py`).
2. Load Zillow ZHVI/ZORI, Realtor.com inventory and Census income (`data_sources/local_files.py`).
3. Build quarterly market datasets and features (`features/`).
4. Walk-forward validation and a random forest (900 trees, depth 7) predicting 4-quarter HPI growth.
5. Entry Score: valuation 20%, supply 18%, momentum 18%, affordability 16%, economy 12%, mortgage 10%,
   risk 6%, each a within-market percentile; mapped to seven signals (85/72/60/48/36/24).
6. Monte Carlo: 2,000 scenario paths per market, 6-month steps to 36 months.
7. Decision tools: meaningful window, sensitivity, triggers, monitoring, ranking, financing, readiness,
   alerts, historical calibration (`decision/`, `validation/`).

See `MODEL_LIMITATIONS.md` before relying on any output.

## V11.1 amendments from the 2026-10-09 system audit (2026-10-09)

These are **amendments made after results were seen** (the audit read the published V11 run). They are not
part of the pre-registered V11 plan, and the V11 pass marks are unchanged. `config/settings.json` runs
`V11.1`; `HOUSING_MODEL_VERSION=V11` still runs V11 as published and `V10` still reproduces the 2026-09-13
baseline. Measured effects are in `V11_RESULTS.md`, section "V11.1 amendments".

1. **Today's rates in the scored quarter.** FHFA's HPI ends at the newest published quarter (2026-06-30 on
   2026-10-09), so every FRED input was cut there and the score used the Q2 average mortgage rate. For that
   one scoring row (never history or training rows) the rate-family features are replaced by the newest
   observations: 30-year mortgage (latest weekly), 10-year Treasury (7-day average of daily), fed funds
   (latest monthly), the spread and yield curve, the 1- and 4-quarter rate changes (against the same series
   91 / 365 days earlier), and the payment and payment-to-income figures derived from them. The dates are
   published as `rate_features_as_of`; triggers and alerts use the same rate.
2. **Release lags.** Annual county HPI and permits (dated 1 January of year Y, published about May of Y+1)
   are shifted five quarters; ACS 5-year income (dated 31 December of Y, released about December of Y+1) is
   shifted four quarters. Each value enters the features when it was available.
3. **Monte Carlo rates from the published outlook.** Each path draws one quantile u and takes the mortgage
   rate at that quantile of the rates outlook's band at every horizon (linear between p10 and p90, normal
   tails beyond). The 10-year follows at the current spread plus a spread change; the scenario follows u
   (lowest 25% of rates = Bull, highest 25% = Bear). Every other random walk now scales its dispersion with
   the square root of time instead of linearly. The highest-scoring simulated horizon is no longer published
   as a "best window": it is `simulated_score_peak`, labelled as not timing advice.
4. **Missing data is reported or fails.** Core FRED series (mortgage, 10-year, fed funds, CPI, each market's
   target HPI and DFW's two components) fail the run when missing; any other missing series, and any Entry
   Score input that falls back to a neutral 50 in the scored quarter, is listed in the contract's warnings.
   A Census refresh with a county missing in any year is refused.
5. **Data ages.** Each source has a warning age and a limit (`validation/freshness.py`). Past the warning
   age: `::warning` and a `STALE_INPUT` contract warning; past the limit: `::error` and production stops.
   Every FRED series' newest observation date is in `data_freshness`.
6. **Publication.** The contract is validated before any file is written, in a temporary directory moved
   into place only on success; workflow steps run under explicit `bash` (pipefail), so a failing command
   piped into `tee` fails its step. The monitoring history records `model_version`, and changes are
   compared only between runs of the same version.
