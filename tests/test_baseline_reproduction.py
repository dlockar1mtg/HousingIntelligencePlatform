"""Phase 2 gate, offline half: the model and Entry Score reproduce the V10 run of 2026-09-13.

The baseline's full model history (features, target, predictions, scores) is committed. Refitting the
model on it and re-scoring must give the same latest Entry Scores and signals. The online half (the same
run rebuilt from live FRED plus the baseline input files) is the reproduce-baseline workflow.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from features.build_features import get_features
from models.housing_model import create_model
from scoring.entry_score import add_entry_scores, entry_signal

BASE = Path(__file__).resolve().parents[1] / "baseline" / "v10-2026-09-13" / "outputs"


def test_refit_reproduces_latest_scores_and_signals():
    hist = pd.read_csv(BASE / "v10_full_history.csv", index_col=0, parse_dates=True)
    features = get_features(hist)
    model = create_model()
    model.fit(hist[features], hist["target_4q_growth"])
    pred = model.predict(hist[features])
    assert np.abs(pred - hist["predicted_12m_growth"]).max() < 0.005
    scored = add_entry_scores(hist.drop(columns=[c for c in hist.columns if c.endswith("_score")]).assign(predicted_12m_growth=pred))
    latest = scored.groupby("market").tail(1).set_index("market")
    expected = pd.read_csv(BASE / "v10_latest_forecast.csv").set_index("market")
    for market in expected.index:
        assert abs(latest.loc[market, "entry_score"] - expected.loc[market, "entry_score"]) < 0.05
        assert entry_signal(latest.loc[market, "entry_score"]) == expected.loc[market, "entry_signal"]
