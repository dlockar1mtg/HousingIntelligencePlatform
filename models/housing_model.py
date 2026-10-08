from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from config.utils import load_settings

TARGET = "target_4q_growth"

def create_model() -> RandomForestRegressor:
    settings = load_settings().get("model", {})
    return RandomForestRegressor(
        n_estimators=settings.get("n_estimators", 900),
        max_depth=settings.get("max_depth", 7),
        min_samples_leaf=settings.get("min_samples_leaf", 3),
        random_state=settings.get("random_state", 42),
    )

def walk_forward_validation(data: pd.DataFrame, features: list[str], target: str = TARGET) -> pd.DataFrame:
    rows = []
    min_train_rows = load_settings().get("model", {}).get("min_train_rows", 40)

    for market in data["market"].unique():
        m = data[data["market"] == market].sort_index().dropna(subset=features + [target])

        for i in range(min_train_rows, len(m)):
            train = m.iloc[:i]
            test = m.iloc[[i]]

            model = create_model()
            model.fit(train[features], train[target])

            pred = model.predict(test[features])[0]
            actual = test[target].iloc[0]

            rows.append({
                "date": test.index[0],
                "market": market,
                "actual_12m_growth": actual,
                "walk_forward_predicted_12m_growth": pred,
                "error": pred - actual,
                "absolute_error": abs(pred - actual),
                "direction_correct": np.sign(pred) == np.sign(actual),
            })

    return pd.DataFrame(rows)

def prediction_interval_from_backtest(latest: pd.DataFrame, backtest: pd.DataFrame) -> pd.DataFrame:
    latest = latest.copy()

    if backtest.empty:
        latest["prediction_interval_low"] = np.nan
        latest["prediction_interval_high"] = np.nan
        latest["forecast_confidence_score"] = np.nan
        return latest

    error_stats = backtest.groupby("market")["error"].agg(
        error_std="std",
        error_mae=lambda x: np.mean(np.abs(x)),
    ).reset_index()

    latest = latest.merge(error_stats, on="market", how="left")
    latest["prediction_interval_low"] = latest["predicted_12m_growth"] - 1.64 * latest["error_std"]
    latest["prediction_interval_high"] = latest["predicted_12m_growth"] + 1.64 * latest["error_std"]
    latest["forecast_confidence_score"] = (100 - latest["error_mae"] * 1000).clip(0, 100)
    return latest