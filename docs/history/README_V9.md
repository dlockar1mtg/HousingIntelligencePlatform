# HousingPredictor V9 Decision Engine Update

Copy these files into your existing `HousingPredictorV6` folder and replace files when prompted.

Files included:
- `run_forecast.py`
- `decision/decision_tools.py`
- `decision/__init__.py`
- `exports/csv_export.py`

V9 adds:
- First meaningful entry window detection
- Sensitivity analysis
- Trigger conditions
- Monitoring snapshots across runs

New outputs:
- `outputs/v9_first_meaningful_entry_windows.csv`
- `outputs/v9_sensitivity_analysis.csv`
- `outputs/v9_trigger_conditions.csv`
- `outputs/v9_monitoring_comparison.csv`
- `outputs/v9_monitoring_current_snapshot.csv`
- `outputs/v9_monitoring_history.csv`

Run:
```cmd
python run_forecast.py
```
