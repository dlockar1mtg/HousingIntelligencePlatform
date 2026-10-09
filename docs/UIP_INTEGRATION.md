# UIP integration

`HousingIntelligencePlatform` → `housing_uip_contract.json` (versioned, validated) → UIP publication cycle
(optional source, never blocks the certified domains) → Homestead page.

The housing repo owns the housing facts: market state, Entry Score and signal with calibration status,
forecasts with ranges, triggers, financing scenarios. The UIP owns the cross-domain decision: what the plan
can afford when, how much stays invested, and the house's effect on net worth.

The household side comes from the UIP's household plan (versioned profile contract) instead of a separate
`personal_profile.json`.

Planned Homestead uses: home price at the target date (today's target price grown by the market forecast),
a live mortgage rate instead of the 6.5% placeholder, Wichita and DFW market cards, and triggers.

## Contract versions
- **1.0.0** (V10, 2026-10-07): one record per market; calibration in-sample; `known_issues` lists the five
  review findings.
- **1.1.0** (V11, 2026-10-08), backward compatible: `model_version` is V11 and `market_state_as_of` is the newest
  quarter. New fields: `prediction_basis` (`FINAL_MODEL`) and `walk_forward` {quarters, gap_quarters 3, mae,
  direction_accuracy}. `calibration` carries `in_sample: false`, the method, `quarters`, both growth means
  and the registered `pass_marks`. The validator refuses a V11 contract with an in-sample calibration. The
  UIP accepts any 1.x contract.
- **1.3.0** (V11.1, 2026-10-09), backward compatible. `model_version` is `V11.1` (the amendments from the
  2026-10-09 system audit, `docs/V11_RESULTS.md`). New: top-level `rate_features_as_of` (the mortgage, 10-year
  and fed funds observations the scored quarter uses, with dates) and `data_ages` (each source's newest
  observation, age in days, warning age and limit); `data_freshness` also lists every FRED series as
  `"FRED <id>": date`. Per market: `rate_features_as_of`, `trigger.mortgage_rate_now` / `mortgage_rate_as_of`,
  outlook rows gain `growth_median` and `mortgage_p10/p50/p90`. **`best_window` is `null`**: the Entry Score
  failed its timing test, so no "best window" is published as advice. The highest simulated score horizon is
  in `simulated_score_peak` with `timing_advice: false` and a note. `warnings` now carries missing input series
  (`MISSING_INPUT_SERIES`), score inputs that fell back to a neutral 50 (`NEUTRAL_50_SCORE_INPUTS`) and stale
  sources (`STALE_INPUT`). The validator refuses a V11.1 contract whose scored mortgage rate differs from
  `rate_features_as_of` or from the rates outlook's latest weekly rate, or that carries a `best_window`.
  The UIP importer reads none of the removed values (its Best window tile shows "—" when the field is null).
