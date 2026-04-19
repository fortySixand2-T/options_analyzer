"""
Edge calculator for the options chain scanner.

Computes the theoretical option price using GARCH-calibrated forward
volatility, compares it to the market mid price, and returns edge metrics
along with BS Greeks.

Options Analytics Team — 2026-04-02
"""

from pathlib import Path
import sys

_SRC = str(Path(__file__).resolve().parent.parent / "pricing" / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from models.black_scholes import black_scholes_price, calculate_greeks

from .providers.base import OptionContract


def compute_edge(contract: OptionContract,
                 spot: float,
                 garch_vol: float,
                 risk_free_rate: float,
                 dte: int) -> dict:
    """Compute theoretical price, edge, direction, and Greeks for a contract.

    Parameters
    ----------
    contract : OptionContract
        The option contract to evaluate.
    spot : float
        Current underlying spot price.
    garch_vol : float
        GARCH-calibrated forward volatility (annualized decimal).
    risk_free_rate : float
        Annualized risk-free rate.
    dte : int
        Days to expiration.

    Returns
    -------
    dict
        Keys: theo_price, edge_pct, direction, delta, gamma, theta, vega, rho.
    """
    T = dte / 365.0

    # Theoretical price using GARCH vol
    theo_price = black_scholes_price(
        S=spot, K=contract.strike, T=T, r=risk_free_rate,
        sigma=garch_vol, option_type=contract.option_type,
    )

    # Edge: positive = underpriced (buy), negative = overpriced (sell)
    if contract.mid > 0:
        edge_pct = (theo_price - contract.mid) / contract.mid * 100
    else:
        edge_pct = 0.0

    direction = 'BUY' if edge_pct > 0 else 'SELL'

    # Greeks at chain IV (market perspective)
    greeks = calculate_greeks(
        S=spot, K=contract.strike, T=T, r=risk_free_rate,
        sigma=contract.implied_volatility,
        option_type=contract.option_type,
    )

    return {
        'theo_price': theo_price,
        'edge_pct': edge_pct,
        'direction': direction,
        'delta': greeks['Delta'],
        'gamma': greeks['Gamma'],
        'theta': greeks['Theta'],
        'vega': greeks['Vega'],
        'rho': greeks['Rho'],
    }
