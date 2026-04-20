"""
Risk rules engine — pre-trade risk checks.

Enforces position limits, event blackouts, correlation constraints,
and stop/target rules before allowing a trade entry.

Options Analytics Team — 2026-04
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RuleViolation:
    """A single rule violation."""
    rule: str           # rule name
    message: str        # human-readable explanation
    severity: str       # "block" (hard stop) or "warn" (advisory)


@dataclass
class RiskRules:
    """Configurable risk rules for pre-trade checks."""
    max_positions: int = 5
    max_risk_pct: float = 0.02          # max risk per trade as fraction
    max_portfolio_risk_pct: float = 0.10  # max total portfolio risk
    max_correlated: int = 2             # max positions in correlated underlyings
    event_blackout: bool = True         # block trades during event windows
    min_dte_for_entry: int = 0          # min DTE to allow entry
    max_loss_per_trade: float = 500.0   # absolute max loss per trade
    require_stop: bool = True           # require a stop-loss defined

    @classmethod
    def from_env(cls) -> "RiskRules":
        """Build rules from environment variables."""
        return cls(
            max_positions=int(os.getenv("OPTIONS_MAX_POSITIONS", "5")),
            max_risk_pct=float(os.getenv("OPTIONS_MAX_RISK_PCT", "0.02")),
            max_portfolio_risk_pct=float(os.getenv("OPTIONS_MAX_PORTFOLIO_RISK_PCT", "0.10")),
            max_correlated=int(os.getenv("OPTIONS_MAX_CORRELATED", "2")),
            event_blackout=os.getenv("OPTIONS_EVENT_BLACKOUT", "true").lower() in ("true", "1", "yes"),
            max_loss_per_trade=float(os.getenv("OPTIONS_MAX_LOSS_PER_TRADE", "500")),
        )


# Correlation groups: symbols that tend to move together
CORRELATION_GROUPS = {
    "large_cap_index": {"SPX", "SPY", "ES"},
    "tech_index": {"QQQ", "NQ", "NDX"},
    "small_cap": {"IWM", "RUT"},
    "mega_tech": {"AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA"},
    "semis": {"NVDA", "AMD", "INTC", "SMH", "SOXX"},
    "energy": {"XLE", "USO", "XOM", "CVX"},
    "financials": {"XLF", "JPM", "GS", "BAC"},
}


def _get_correlation_group(symbol: str) -> Optional[str]:
    """Find which correlation group a symbol belongs to."""
    symbol_upper = symbol.upper()
    for group_name, members in CORRELATION_GROUPS.items():
        if symbol_upper in members:
            return group_name
    return None


def check_max_positions(
    current_positions: List[Dict],
    rules: RiskRules,
) -> Optional[RuleViolation]:
    """Check if max position limit would be exceeded."""
    if len(current_positions) >= rules.max_positions:
        return RuleViolation(
            rule="max_positions",
            message=f"At position limit ({len(current_positions)}/{rules.max_positions})",
            severity="block",
        )
    return None


def check_correlation(
    symbol: str,
    current_positions: List[Dict],
    rules: RiskRules,
) -> Optional[RuleViolation]:
    """Check if adding this symbol would exceed correlation limits."""
    new_group = _get_correlation_group(symbol)
    if new_group is None:
        return None

    correlated_count = 0
    for pos in current_positions:
        pos_symbol = pos.get("symbol", "")
        if _get_correlation_group(pos_symbol) == new_group:
            correlated_count += 1

    if correlated_count >= rules.max_correlated:
        return RuleViolation(
            rule="correlation",
            message=(
                f"{symbol} in '{new_group}' group — already have "
                f"{correlated_count} correlated position(s) (limit: {rules.max_correlated})"
            ),
            severity="warn",
        )
    return None


def check_event_blackout(
    rules: RiskRules,
) -> Optional[RuleViolation]:
    """Check if we're in an event blackout window."""
    if not rules.event_blackout:
        return None

    try:
        from regime.calendar import is_event_window
        in_event, event_type, days = is_event_window()
        if in_event:
            return RuleViolation(
                rule="event_blackout",
                message=f"{event_type} in {days} day(s) — event blackout active",
                severity="warn",
            )
    except ImportError:
        pass

    return None


def check_portfolio_risk(
    current_positions: List[Dict],
    new_risk: float,
    fund_size: Optional[float] = None,
    rules: Optional[RiskRules] = None,
) -> Optional[RuleViolation]:
    """Check if total portfolio risk would exceed limit."""
    rules = rules or RiskRules.from_env()
    fund = fund_size or float(os.getenv("OPTIONS_FUND_SIZE", "10000"))

    current_risk = sum(abs(p.get("risk", 0)) for p in current_positions)
    total_risk = current_risk + abs(new_risk)
    risk_pct = total_risk / fund if fund > 0 else 1.0

    if risk_pct > rules.max_portfolio_risk_pct:
        return RuleViolation(
            rule="portfolio_risk",
            message=(
                f"Total risk ${total_risk:.0f} ({risk_pct:.1%}) would exceed "
                f"limit of {rules.max_portfolio_risk_pct:.1%}"
            ),
            severity="block",
        )
    return None


def check_trade_risk(
    max_loss: float,
    rules: RiskRules,
    fund_size: Optional[float] = None,
) -> Optional[RuleViolation]:
    """Check if single trade risk exceeds limits."""
    fund = fund_size or float(os.getenv("OPTIONS_FUND_SIZE", "10000"))
    max_loss = abs(max_loss)

    if max_loss > rules.max_loss_per_trade:
        return RuleViolation(
            rule="max_trade_loss",
            message=f"Max loss ${max_loss:.0f} exceeds per-trade limit ${rules.max_loss_per_trade:.0f}",
            severity="block",
        )

    risk_pct = max_loss / fund if fund > 0 else 1.0
    if risk_pct > rules.max_risk_pct:
        return RuleViolation(
            rule="trade_risk_pct",
            message=f"Trade risk {risk_pct:.1%} exceeds per-trade limit {rules.max_risk_pct:.1%}",
            severity="block",
        )

    return None


def check_all_rules(
    symbol: str,
    max_loss: float,
    current_positions: Optional[List[Dict]] = None,
    fund_size: Optional[float] = None,
    rules: Optional[RiskRules] = None,
) -> List[RuleViolation]:
    """Run all pre-trade risk checks.

    Parameters
    ----------
    symbol : str
        Symbol to trade.
    max_loss : float
        Maximum loss for this trade.
    current_positions : list of dict, optional
        Current open positions (each with "symbol" and "risk" keys).
    fund_size : float, optional
        Total fund size.
    rules : RiskRules, optional
        Risk rules to apply (default: from env).

    Returns
    -------
    List[RuleViolation]
        Empty list means all checks pass.
    """
    rules = rules or RiskRules.from_env()
    positions = current_positions or []
    violations = []

    v = check_max_positions(positions, rules)
    if v:
        violations.append(v)

    v = check_correlation(symbol, positions, rules)
    if v:
        violations.append(v)

    v = check_event_blackout(rules)
    if v:
        violations.append(v)

    v = check_portfolio_risk(positions, max_loss, fund_size, rules)
    if v:
        violations.append(v)

    v = check_trade_risk(max_loss, rules, fund_size)
    if v:
        violations.append(v)

    return violations
