# Mortgage-rate outlook: plan (registered before results, 2026-10-08)

Owner request (Devon, 2026-10-08): project interest rates, since they are among the largest drivers of
housing affordability and supply (owners locked into 2–3% loans do not sell to borrow at 7%).

## What is projected
The Freddie Mac 30-year fixed rate (FRED `MORTGAGE30US`) h months ahead, for h = 6, 12, …, 60. Monthly
averages throughout. Everything is point-in-time: a forecast made at month t uses only data through t.

## Inputs (FRED, free)
- Treasury constant-maturity yields `DGS1`, `DGS2`, `DGS3`, `DGS5`, `DGS7`, `DGS10`, `DGS20`, `DGS30`.
- `MORTGAGE30US`.
- Context only, not used in any forecast: the FOMC Summary of Economic Projections medians for the fed funds
  rate (`FEDTARMD` by year, `FEDTARMDLR` longer run). These are the committee members' own projections,
  not market odds. Market odds (fed funds futures) are not freely available.

## Centers (candidate rules)
1. **NO_CHANGE**: today's mortgage rate.
2. **CURVE_FORWARD**: the market-implied 10-year Treasury yield h months ahead, plus today's mortgage
   spread over the 10-year (its 3-month average). The forward rate comes from the yield curve, treating
   par yields as zero rates: f = ((1+y(h+10))^(h+10) / (1+y(h))^h)^(1/10) − 1. Maturities between
   published points are interpolated linearly. Where the 20-year is missing (1987–1993), the 10- and
   30-year are used.
3. **CURVE_FORWARD_LONG_SPREAD**: the same forward 10-year, plus the median spread of all history up to t.

The published center is chosen walk-forward. At each origin, the rule with the lowest median absolute
error among errors already realized by then (at least 60 of them) is used. Until then it is NO_CHANGE.

## Range
The center plus the chosen rule's own past errors at that horizon (realized by t; at least 60). The
published band is the 10th–90th percentile of those errors; the 25th and 75th are shown too.

## Test (36-month horizon is the headline; every horizon is reported)
- Monthly origins from 1985-01 to the last one whose outcome is known.
- For each rule, report the mean and median absolute error, and the share of outcomes inside the published
  10–90 band. Results are also split by decade, because forwards are known to have run high when rates
  were falling.
- **Status of the band:** TESTED if 70–90% of outcomes land inside it; TOO_NARROW below 70%; TOO_WIDE above
  90%; TOO_FEW_TESTS under 120 origins. Overlapping monthly origins make neighbouring errors related, so
  the effective number of independent tests is about the count divided by h. It is reported.
- **Does the market's curve beat "no change"?** Answered by the MAE comparison, whatever it shows. If it
  does not, the chosen rule will be NO_CHANGE, and the outlook says so.

## Publication
`outputs/rates_outlook.json`, and a `rates_outlook` block in the housing contract (1.2.0, backward
compatible). It carries today's rate, the 10-year, the spread, every horizon's center and band, both
candidate centers, the test results with status, and the SEP context. The UIP uses the band at the target
month for the mortgage payment range. Nothing here changes the V11 model or the Entry Score.

## Not in this step
The lock-in gap (the average rate on outstanding mortgages against today's rate). No free FRED series was
found; FHFA's National Mortgage Database publishes it, and it can be added later as a registered change.
