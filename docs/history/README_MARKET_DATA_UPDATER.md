# Housing Predictor V10 - Automated Market Data Updater

Copy the contents of this ZIP into:

C:\Users\DevonLockard\HousingPredictorv6

Replace `update_data.py` when prompted. The new file
`data_sources\market_file_updater.py` will be added.

Then run:

    python update_data.py

The updater will:
- Download the official Zillow ZHVI metro history.
- Download the official Zillow ZORI metro history.
- Download the official Realtor.com metro inventory history.
- Validate Wichita and DFW coverage.
- Validate observation dates.
- Back up existing market CSVs before replacement.
- Preserve the installed file if a download or validation fails.
- Refresh Census affordability data using the existing Census loader.
- Write `outputs\v10_data_freshness_report.csv`.

After it completes successfully:

    python run_forecast.py

The forecast itself continues to retrieve its FRED series live.
