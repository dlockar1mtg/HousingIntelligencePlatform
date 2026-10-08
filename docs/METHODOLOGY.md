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
