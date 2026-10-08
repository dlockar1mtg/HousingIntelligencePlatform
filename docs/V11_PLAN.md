# V11: fixing the V10 review findings (registered before results, 2026-10-08)

V11 changes only what the migration review found wrong (`MODEL_LIMITATIONS.md`, findings 1–5). It keeps
V10's features, model settings, score weights and signal bands. Every number below is computed on the
same frozen inputs (`data/snapshot/` plus the baseline market files) for V10 and V11 side by side, and
published in `docs/V11_RESULTS.md` whatever it shows.

## Changes
1. **Score the newest quarter.** Train on rows whose 4-quarter target is realized; predict and score the
   newest row that has features. The contract's market state becomes that quarter.
2. **Exact metro matching.** Metro-level files (Zillow ZHVI/ZORI, Realtor.com) match only the configured
   metro names: Wichita, KS and Dallas, TX (Zillow); Wichita, KS and Dallas-Fort Worth-Arlington, TX
   (Realtor.com). County aliases no longer touch metro files.
3. **Walk-forward with a gap.** The model for test quarter *t* trains only on rows whose target was known
   at *t* (rows up to *t − 4*).
4. **Point-in-time scores.** Each Entry Score component is the percentile of that quarter's value among
   the market's quarters up to and including it, and the momentum component uses the walk-forward
   (out-of-sample) prediction for history. The latest quarter's score uses the final model.
5. **No invented history.** Optional layers (Zillow, Realtor.com, county listings, Census income) are
   forward-filled only; quarters before a source exists stay missing, and the random forest's native
   missing-value support handles them. Census income becomes a yearly ACS 5-year series from 2009 instead
   of one year applied to every quarter.

## Measures (both versions, same inputs)
- Walk-forward accuracy with the 4-quarter gap: mean absolute error and direction accuracy, per market.
- Out-of-sample calibration: point-in-time Entry Scores (with walk-forward momentum) against the realized
  next-12-month HPI growth, per market: rank correlation, mean growth at Neutral-or-better vs below.
- The current state each version reports, and the quarter it describes.

## Pass marks (set now)
- **Calibration PASS** for a market requires, over at least 40 out-of-sample quarters: rank correlation
  ≥ 0.10 **and** mean realized growth at Neutral-or-better ≥ mean growth below Neutral. Otherwise FAIL.
  The contract publishes the out-of-sample result in place of V10's in-sample one.
- **V11 is adopted** if changes 1–5 are implemented as written and the tests pass. Accuracy is reported,
  not gated: honest numbers are expected to look worse than V10's leaky ones.
- Any further change made after seeing these results is recorded as such.
