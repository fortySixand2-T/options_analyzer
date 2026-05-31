"""Unit tests for the directional-signal IC verdict logic (signal_eval).

The IC computation itself needs network/yfinance, so we test the deterministic
verdict classifier here; the IC values are exercised in the alpha evaluation.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backtest.signal_eval import ic_verdict


def test_predictive():
    assert ic_verdict({"spearman": 0.10, "spearman_p": 0.01}) == "predictive"


def test_noise_when_not_significant():
    # Right sign but p ≥ 0.05 → not a real edge.
    assert ic_verdict({"spearman": 0.10, "spearman_p": 0.40}) == "noise"


def test_inverted_signal():
    assert ic_verdict({"spearman": -0.12, "spearman_p": 0.01}) == "inverted"


def test_insufficient_sample():
    assert ic_verdict({"n": 5}) == "insufficient_sample"
