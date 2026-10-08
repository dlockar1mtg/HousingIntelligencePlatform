# HousingPredictor V10 Optimization Update

Copy these files into your existing project and replace files when prompted.

Included:
- run_forecast.py
- decision/purchase_optimizer.py
- validation/historical_calibration.py
- exports/csv_export.py

V10 adds:
- Market ranking
- Personal readiness + market score combination
- Financing optimizer for 15/30-year terms and 3/5/10/20% down
- Alert engine
- Historical calibration of entry-score signals

Requires:
- Existing V9 files
- inputs/personal_profile.json for personalized outputs

Run:
```cmd
python run_forecast.py
```
