from __future__ import annotations
from config.utils import OUTPUT_DIR, log

def export_v10(
    model_data, latest, backtest, importances, county_drilldown, features,
    simulations, simulation_summary, signal_probabilities, best_windows,
    meaningful_windows, sensitivity, triggers, monitoring,
    market_ranking, financing, combined, alerts, calibration, calibration_diagnostics
):
    paths={
        "full_history":OUTPUT_DIR/"v10_full_history.csv",
        "latest":OUTPUT_DIR/"v10_latest_forecast.csv",
        "backtest":OUTPUT_DIR/"v10_walk_forward_backtest.csv",
        "importance":OUTPUT_DIR/"v10_feature_importance.csv",
        "county":OUTPUT_DIR/"v10_county_drilldown.csv",
        "simulations":OUTPUT_DIR/"v10_monte_carlo_simulations.csv",
        "simulation_summary":OUTPUT_DIR/"v10_monte_carlo_summary.csv",
        "signal_probabilities":OUTPUT_DIR/"v10_signal_probability_summary.csv",
        "best_windows":OUTPUT_DIR/"v10_best_entry_windows.csv",
        "meaningful_windows":OUTPUT_DIR/"v10_first_meaningful_entry_windows.csv",
        "sensitivity":OUTPUT_DIR/"v10_sensitivity_analysis.csv",
        "triggers":OUTPUT_DIR/"v10_trigger_conditions.csv",
        "monitoring":OUTPUT_DIR/"v10_monitoring_comparison.csv",
        "market_ranking":OUTPUT_DIR/"v10_market_ranking.csv",
        "financing":OUTPUT_DIR/"v10_financing_optimizer.csv",
        "combined":OUTPUT_DIR/"v10_combined_purchase_readiness.csv",
        "alerts":OUTPUT_DIR/"v10_alerts.csv",
        "calibration":OUTPUT_DIR/"v10_historical_signal_calibration.csv",
        "calibration_diagnostics":OUTPUT_DIR/"v10_calibration_diagnostics.csv",
    }
    model_data.to_csv(paths["full_history"])
    latest.to_csv(paths["latest"],index=False)
    backtest.to_csv(paths["backtest"],index=False)
    importances.to_csv(paths["importance"],index=False)
    optional={
        "county":county_drilldown,"simulations":simulations,"simulation_summary":simulation_summary,
        "signal_probabilities":signal_probabilities,"best_windows":best_windows,
        "meaningful_windows":meaningful_windows,"sensitivity":sensitivity,"triggers":triggers,
        "monitoring":monitoring,"market_ranking":market_ranking,"financing":financing,
        "combined":combined,"alerts":alerts,"calibration":calibration,
        "calibration_diagnostics":calibration_diagnostics,
    }
    for key,df in optional.items():
        if df is not None and not df.empty:
            df.to_csv(paths[key],index=False)
    log("\nFiles created:")
    for p in paths.values():
        if p.exists(): log(f"- {p}")