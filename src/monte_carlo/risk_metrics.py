#!/usr/bin/env python3
"""
Risk Metrics for Monte Carlo Simulations
=========================================

Pure functions operating on numpy arrays for computing
tail-risk metrics and distribution statistics.

Author: Options Analytics Team
Date: March 2026
"""

import numpy as np
from typing import Dict


def compute_var(pnl: np.ndarray, confidence: float = 0.95) -> float:
    """
    Compute Value at Risk (VaR) at the given confidence level.

    VaR is the loss threshold such that losses exceed it with probability (1 - confidence).
    Returns a positive number representing the loss magnitude.

    Parameters:
    -----------
    pnl : np.ndarray
        Array of P&L values (can be negative for losses)
    confidence : float
        Confidence level (e.g., 0.95 for 95% VaR)

    Returns:
    --------
    float
        VaR (positive number = loss magnitude)
    """
    return float(-np.percentile(pnl, (1 - confidence) * 100))


def compute_cvar(pnl: np.ndarray, confidence: float = 0.95) -> float:
    """
    Compute Conditional Value at Risk (CVaR / Expected Shortfall).

    CVaR is the expected loss given that the loss exceeds VaR.
    Returns a positive number representing the expected loss beyond VaR.

    Parameters:
    -----------
    pnl : np.ndarray
        Array of P&L values
    confidence : float
        Confidence level (e.g., 0.95)

    Returns:
    --------
    float
        CVaR (positive number = expected loss beyond VaR threshold)
    """
    threshold = np.percentile(pnl, (1 - confidence) * 100)
    tail_losses = pnl[pnl <= threshold]
    if len(tail_losses) == 0:
        return compute_var(pnl, confidence)
    return float(-np.mean(tail_losses))


def compute_distribution_stats(values: np.ndarray) -> Dict[str, float]:
    """
    Compute descriptive statistics for a distribution.

    Parameters:
    -----------
    values : np.ndarray
        Array of values to summarize

    Returns:
    --------
    Dict[str, float]
        Dictionary with keys: mean, std, min, max, p5, p25, p50, p75, p95
    """
    return {
        'mean': float(np.mean(values)),
        'std': float(np.std(values)),
        'min': float(np.min(values)),
        'max': float(np.max(values)),
        'p5': float(np.percentile(values, 5)),
        'p25': float(np.percentile(values, 25)),
        'p50': float(np.percentile(values, 50)),
        'p75': float(np.percentile(values, 75)),
        'p95': float(np.percentile(values, 95)),
    }
