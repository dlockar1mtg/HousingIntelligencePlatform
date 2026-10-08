# Governance

- **Reproducibility.** A published result names its commit, input data dates, model settings, market
  configuration, and (when used) the household profile version and run time.
- **Fail-safe data.** A bad or incomplete download never replaces a known-good file (the V10 updater keeps
  the installed copy and reports FAILED-SAFE).
- **Explicit optionality.** Missing optional county series are recorded, never fabricated.
- **No silent schema drift.** Zillow, Realtor.com and Census schema changes fail validation.
- **Separation.** Market intelligence and household data stay separate until the decision layer.
- **No overstated certainty.** Forecast confidence is not certainty; Monte Carlo probabilities are model
  scenario frequencies; sensitivity coefficients are heuristic, not causal.
- **Calibration disclosure.** Each market's calibration status is published with its signal.
- **Tests first, evidence registered.** A model change ships with its test and, for any change judged on
  historical results, the pass mark is written down before the result is seen (as in the UIP's ETF and
  metals work). Changes made after seeing results are labelled as such.
- **Secrets and personal data.** No keys, no live household profile, no household outputs in git; tests use
  synthetic fixtures.
