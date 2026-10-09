import json
import os
from datetime import date
from pathlib import Path

import pandas as pd

from config.utils import log, OUTPUT_DIR, INPUT_DIR, is_v11, is_v11_1, model_version
from data_sources import fred_loader
from features.dataset import build_dataset
from features.build_features import get_features
from models.housing_model import create_model, walk_forward_validation, prediction_interval_from_backtest
from models.monte_carlo_engine import run_monte_carlo_simulation
from scoring.entry_score import add_entry_scores, entry_signal, classify_market_regime, neutral_inputs
from decision.decision_tools import meaningful_window_summary, sensitivity_analysis, trigger_engine, monitoring_snapshot
from decision.purchase_optimizer import load_profile, build_market_ranking, build_financing_optimizer, build_combined_score, build_alerts
from validation.historical_calibration import build_historical_calibration
from exports.csv_export import export_v10
from validation import freshness

TARGET="target_4q_growth"
N_SIMULATIONS=2000
MIN_PROJECTION_CONFIDENCE=55.0
MAX_PROJECTION_MONTHS=36
PROJECTION_STEP_MONTHS=6

def load_rates_outlook() -> dict:
    """V11.1: the Monte Carlo draws mortgage rates from the published outlook (python -m rates.outlook),
    which the workflows build before the forecast. Without it the run stops rather than invent rates."""
    path=Path(os.environ.get("HOUSING_RATES_OUTLOOK") or OUTPUT_DIR/"rates_outlook.json")
    if not path.exists():
        raise RuntimeError(f"{path} is missing: run `python -m rates.outlook --out {path}` first (V11.1 Monte Carlo)")
    return json.loads(path.read_text(encoding="utf-8"))

def write_data_quality(latest, rates=None) -> dict:
    """outputs/data_quality.json: what the contract's warnings and data_freshness report about the inputs
    (audit findings 5 and 6). Fails the run when a core series is missing (fred() has already raised)."""
    obs=dict(sorted(fred_loader.OBSERVED.items()))
    rows=freshness.assess({f"FRED {k}":v for k,v in obs.items()},date.today())
    quality={"model_version":model_version(),
             "missing_series":list(fred_loader.MISSING),
             "fred_observations":obs,
             "fred_freshness":rows,
             "neutral_score_inputs":neutral_inputs(latest) if is_v11_1() else {},
             "rate_features_as_of":rates}
    warnings=[]
    if quality["missing_series"]:
        warnings.append("MISSING_INPUT_SERIES: "+", ".join(f"{m['series_id']} ({m['name']})" for m in quality["missing_series"]))
    for market,cols in quality["neutral_score_inputs"].items():
        warnings.append(f"NEUTRAL_50_SCORE_INPUTS: {market}: "+", ".join(cols))
    warnings+=freshness.warnings_for(rows)
    quality["warnings"]=warnings
    (OUTPUT_DIR/"data_quality.json").write_text(json.dumps(quality,indent=1,default=str)+"\n",encoding="utf-8")
    for w in warnings: log(f"WARNING {w}")
    return quality

def main():
    version=model_version()
    log(f"Starting Housing Predictor {version} Optimization Platform...\n")
    rates_outlook=load_rates_outlook() if is_v11_1() else None
    fred_loader.reset_run_state()
    data,county_drilldown=build_dataset()
    features=get_features(data)
    if is_v11():
        # V11: train on quarters whose 4-quarter target is realized; score every quarter, newest included.
        train=data.dropna(subset=[TARGET]).copy()
        model_data=data.copy()
    else:
        model_data=data.dropna(subset=features+[TARGET]).copy()
        train=model_data
    if train.empty: raise RuntimeError("No usable model rows were created.")

    log("\nRunning walk-forward validation...")
    backtest=walk_forward_validation(train,features,TARGET)

    log("\nTraining final model...")
    model=create_model()
    model.fit(train[features],train[TARGET])
    model_data["predicted_12m_growth"]=model.predict(model_data[features])
    if is_v11() and not backtest.empty:
        # History gets its walk-forward (out-of-sample) prediction, so scores and calibration are honest;
        # quarters newer than the training data keep the final model's prediction, which is out of sample.
        oos=backtest.set_index(["market","date"])["walk_forward_predicted_12m_growth"]
        keys=list(zip(model_data["market"],model_data.index))
        in_train=model_data[TARGET].notna()
        model_data["predicted_12m_growth"]=[oos.get(k,float("nan")) if t else p for k,t,p in zip(keys,in_train,model_data["predicted_12m_growth"])]
        model_data["prediction_basis"]=["WALK_FORWARD" if t and k in oos.index else ("NONE" if t else "FINAL_MODEL") for k,t in zip(keys,in_train)]
    model_data["projected_hpi_12m"]=model_data["hpi"]*(1+model_data["predicted_12m_growth"])
    importances=pd.DataFrame({"feature":features,"importance":model.feature_importances_}).sort_values("importance",ascending=False)

    model_data=add_entry_scores(model_data)
    model_data["entry_signal"]=model_data["entry_score"].apply(entry_signal)
    model_data["market_regime"]=model_data.apply(classify_market_regime,axis=1)

    latest=model_data.groupby("market").tail(1).copy()
    latest=prediction_interval_from_backtest(latest,backtest)
    latest["hpi_yoy_pct"]=latest["hpi_yoy"]*100
    latest["predicted_12m_growth_pct"]=latest["predicted_12m_growth"]*100
    latest["prediction_interval_low_pct"]=latest["prediction_interval_low"]*100
    latest["prediction_interval_high_pct"]=latest["prediction_interval_high"]*100
    latest["inflation_yoy_pct"]=latest["inflation_yoy"]*100

    log(f"\nRunning Monte Carlo simulation with {N_SIMULATIONS:,} simulations per market...")
    simulations,simulation_summary,signal_probabilities,best_windows=run_monte_carlo_simulation(
        model_data=model_data,features=features,base_prediction_model=model,
        n_simulations=N_SIMULATIONS,max_months=MAX_PROJECTION_MONTHS,
        step_months=PROJECTION_STEP_MONTHS,min_confidence=MIN_PROJECTION_CONFIDENCE,rates_outlook=rates_outlook)

    log(f"\nBuilding {version} decision and optimization tools...")
    rates_now=fred_loader.latest_rate_features() if is_v11_1() else None
    write_data_quality(latest,rates_now)
    meaningful=meaningful_window_summary(simulation_summary)
    sensitivity=sensitivity_analysis(latest,model_data)
    triggers=trigger_engine(latest)
    monitoring=monitoring_snapshot(latest,OUTPUT_DIR,model_version=version)
    profile=load_profile(INPUT_DIR)
    ranking=build_market_ranking(latest,simulation_summary)
    financing=build_financing_optimizer(profile,latest)
    combined=build_combined_score(latest,profile,ranking)
    alerts=build_alerts(latest,monitoring,meaningful,timing_advice=not is_v11_1())
    calibration,calibration_diagnostics=build_historical_calibration(model_data)

    log("\nCombined Purchase Readiness")
    log(combined.round(3).to_string(index=False) if not combined.empty else "No personal profile found.")

    log("\nMarket Ranking")
    log(ranking.round(3).to_string(index=False))

    if not calibration_diagnostics.empty:
        log("\nHistorical Calibration Diagnostics")
        log(calibration_diagnostics.round(3).to_string(index=False))

    display_cols=["market","market_regime","hpi","hpi_yoy_pct","mortgage_30yr","rate_features_as_of","zillow_zhvi",
                  "payment_to_income_ratio","predicted_12m_growth_pct","entry_score",
                  "entry_signal","forecast_confidence_score"]
    display_cols=[c for c in display_cols if c in latest.columns]

    export_v10(
        model_data,latest[display_cols],backtest,importances,county_drilldown,features,
        simulations,simulation_summary,signal_probabilities,best_windows,
        meaningful,sensitivity,triggers,monitoring,ranking,financing,combined,alerts,
        calibration,calibration_diagnostics)

    log(f"\nHousing Predictor {version} optimization platform complete.")

if __name__=="__main__":
    main()