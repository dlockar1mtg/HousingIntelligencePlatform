"""Entry Score boundaries and ranges (V10 behaviour, unchanged)."""
import numpy as np
import pandas as pd
import pytest

from scoring.entry_score import add_entry_scores, signal_rank, signal_strength


@pytest.mark.parametrize("score,signal", [(85, "Strong Buy"), (84.99, "Buy"), (72, "Buy"), (60, "Slight Buy"),
                                          (48, "Neutral / Fair Value"), (47.9, "Slight Wait"), (36, "Slight Wait"),
                                          (24, "Wait"), (23.9, "Strong Wait / High Risk")])
def test_signal_boundaries(score, signal):
    assert signal_strength(score) == signal


def test_signal_ranks_are_ordered():
    order = ["Strong Wait / High Risk", "Wait", "Slight Wait", "Neutral / Fair Value", "Slight Buy", "Buy", "Strong Buy"]
    assert [signal_rank(s) for s in order] == list(range(1, 8))


def test_scores_stay_between_0_and_100_with_missing_columns():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"market": ["A"] * 20 + ["B"] * 20, "predicted_12m_growth": rng.normal(0.03, 0.02, 40),
                       "hpi_yoy": rng.normal(0.04, 0.03, 40), "mortgage_30yr": rng.uniform(3, 8, 40)})
    out = add_entry_scores(df)
    assert out["entry_score"].between(0, 100).all()
    assert out["supply_score"].eq(50).all()          # absent inputs score a neutral 50
