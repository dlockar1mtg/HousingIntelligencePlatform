"""Mortgage payment and historical calibration on synthetic data."""
import numpy as np
import pandas as pd
import pytest

from decision.purchase_optimizer import payment
from validation.historical_calibration import build_historical_calibration


def test_payment_matches_the_standard_formula():
    assert payment(280000, 6.5, 30) == pytest.approx(1769.79, abs=0.01)
    assert payment(0, 6.5, 30) == 0.0


def test_calibration_passes_when_higher_scores_precede_higher_growth():
    rng = np.random.default_rng(2)
    score = rng.uniform(20, 80, 80)
    df = pd.DataFrame({"market": "A", "entry_score": score, "target_4q_growth": 0.001 * score + rng.normal(0, 0.005, 80)})
    _, diag = build_historical_calibration(df)
    assert bool(diag.iloc[0]["calibration_pass"]) and diag.iloc[0]["entry_score_future_growth_correlation"] > 0.5
