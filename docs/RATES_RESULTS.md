# Mortgage-rate outlook: results (2026-10-08)

Registered in `docs/RATES_PLAN.md` before these numbers existed. The inputs are the FRED snapshot of
2026-10-08 (`data/snapshot/rates/`), and the full output is in `RATES_RESULTS.json`. Production recomputes
all of this weekly on live FRED.

## Today
- 30-year fixed: **7.40%** (week of Oct 8); October so far averages 7.34%. 10-year Treasury 5.28%.
- Mortgage spread over the 10-year: **1.97 points** (3-month average), against a long-run median of 1.68.
- **The market's curve** implies a 10-year of 5.53% in three years. With today's spread that is a 30-year
  near **7.5%** in October 2029: the curve expects slightly higher rates, not lower.
- **FOMC projections (context, not a forecast here):** a fed funds median of 4.1% for 2026 and 3.2% in the
  longer run (SEP of Sep 16, 2026). These are the members' own projections, not market odds, and they
  describe the overnight rate, not the 10-year that mortgages follow.

## The test (monthly origins 1985–2023, 466 at 36 months)

| Horizon | No change (MAE) | Curve forward | Curve forward, long-run spread | 10–90 band held | Status |
|---|---|---|---|---|---|
| 12 months | **0.71** | 0.78 | 0.83 | 93% | TOO_WIDE |
| 24 months | **0.95** | 1.07 | 1.08 | 88% | TESTED |
| 36 months | **1.12** | 1.30 | 1.29 | 89% | TESTED |
| 48 months | **1.24** | 1.54 | 1.50 | 89% | TESTED |
| 60 months | **1.39** | 1.79 | 1.69 | 92% | TOO_WIDE |

MAE is in percentage points of mortgage rate.

- **The market's curve did not beat "no change"** at any horizon over the whole test. By period, at 36
  months, it won only for 2020–2023 origins (2.15 against 2.39). Through 1985–2019 the curve ran high,
  because rates kept falling. So the published center is mostly "no change". The walk-forward choice
  picked the long-run-spread curve at times, but it never did better than no change overall.
- **The bands held their stated odds at 24–54 months.** At 6–18 and 60 months they were a little too wide
  (90–93% inside). There are about 13 independent 36-month tests in the history (466 overlapping
  origins / 36), so read this as reasonable, not proven.

## What it says for a purchase in late 2029 (36 months ahead)
**Typical 7.1%, with an 80% range of 5.0% to 10.1%.** Half the range lies within 6.0–8.0% (25th–75th).
Nobody, the market included, has had a reliable edge on where mortgage rates will be in three years.
The honest answer is today's rate, give or take about a point in a typical case, and more in a bad one.

## What changes
- **Production:** the weekly run computes the outlook on live FRED (`python -m rates.outlook`).
- **Contract 1.2.0:** a `rates_outlook` block carrying today's rate, every horizon's center and band, both
  curve-implied centers, the test and the SEP context.
- **Homestead (UIP):** it reads the band at the target month for the mortgage payment range. The 6.5% placeholder
  becomes the plan's assumption, with a one-click "use the outlook".

## Not done
The lock-in gap (the average rate on outstanding mortgages against today's). No free FRED series was
found; FHFA's National Mortgage Database publishes it. When rates fall, locked-in owners like a 2% borrower
begin to sell, which adds supply and can slow price gains. Adding this is a registered follow-up.
