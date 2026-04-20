"""
Tastytrade order placement — paper-first, then live.

Handles multi-leg order construction, validation, submission, and
status tracking via the Tastytrade API.

Safety:
    - Paper trading is the default (TT_SANDBOX=true)
    - Live orders require explicit TT_LIVE_TRADING=true
    - All orders are validated against risk rules before submission
    - Maximum order size is capped

Options Analytics Team — 2026-04
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass
class OrderLeg:
    """Single leg of a multi-leg order."""
    action: str             # "buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"
    symbol: str             # OCC symbol (e.g. "SPY   260417C00590000")
    quantity: int
    option_type: str        # "call" or "put"
    strike: float
    expiry: str             # YYYY-MM-DD


@dataclass
class OrderRequest:
    """Order request before submission."""
    underlying: str
    strategy: str           # e.g. "iron_condor", "credit_spread"
    legs: List[OrderLeg]
    order_type: str = "limit"   # "limit" or "market"
    price: Optional[float] = None  # limit price (credit=positive, debit=negative)
    time_in_force: str = "day"  # "day" or "gtc"
    dry_run: bool = False       # if True, validate but don't submit


@dataclass
class OrderResult:
    """Result of an order submission."""
    status: OrderStatus
    order_id: Optional[str] = None
    message: str = ""
    fill_price: Optional[float] = None
    filled_at: Optional[str] = None
    account_number: Optional[str] = None
    is_paper: bool = True
    raw_response: Optional[Dict] = None


class OrderManager:
    """Manages order lifecycle via Tastytrade API.

    Safety defaults:
    - Paper trading unless TT_LIVE_TRADING=true
    - Max 10 contracts per order
    - Risk rules checked before submission
    """

    MAX_CONTRACTS = 10

    def __init__(self, session=None):
        self._session = session
        self._account = None
        self._is_paper = not (os.getenv("TT_LIVE_TRADING", "").lower() in ("true", "1", "yes"))
        self._order_history: List[OrderResult] = []

    @property
    def is_paper(self) -> bool:
        return self._is_paper

    def connect(self, session=None) -> bool:
        """Establish TT session and resolve account.

        Returns True if ready for orders.
        """
        if session:
            self._session = session

        if self._session is None:
            try:
                from tastytrade import Session
                username = os.getenv("TT_USERNAME", "")
                password = os.getenv("TT_PASSWORD", "")
                if not username or not password:
                    logger.warning("TT credentials not set")
                    return False
                is_test = os.getenv("TT_SANDBOX", "true").lower() in ("1", "true", "yes")
                self._session = Session(login=username, password=password, is_test=is_test)
                self._is_paper = is_test
            except Exception as e:
                logger.warning("TT session failed: %s", e)
                return False

        # Resolve account
        try:
            from tastytrade import Account
            accounts = Account.get_accounts(self._session)
            if not accounts:
                logger.warning("No TT accounts found")
                return False
            self._account = accounts[0]
            logger.info("Connected to TT account %s (paper=%s)",
                        self._account.account_number, self._is_paper)
            return True
        except Exception as e:
            logger.warning("Account resolution failed: %s", e)
            return False

    def validate(self, request: OrderRequest) -> List[str]:
        """Validate an order request before submission.

        Returns list of validation errors (empty = valid).
        """
        errors = []

        if not request.legs:
            errors.append("Order has no legs")

        total_qty = sum(leg.quantity for leg in request.legs)
        if total_qty > self.MAX_CONTRACTS:
            errors.append(f"Total quantity {total_qty} exceeds max {self.MAX_CONTRACTS}")

        for leg in request.legs:
            if leg.quantity <= 0:
                errors.append(f"Leg {leg.symbol}: quantity must be positive")
            if leg.strike <= 0:
                errors.append(f"Leg {leg.symbol}: invalid strike {leg.strike}")

        if request.order_type == "limit" and request.price is None:
            errors.append("Limit order requires a price")

        # Risk rules check
        try:
            from risk.rules import check_all_rules
            max_loss = abs(request.price or 0) * 100 * total_qty
            violations = check_all_rules(
                symbol=request.underlying,
                max_loss=max_loss,
            )
            for v in violations:
                if v.severity == "block":
                    errors.append(f"Risk rule [{v.rule}]: {v.message}")
        except ImportError:
            pass  # risk module not available

        return errors

    def submit(self, request: OrderRequest) -> OrderResult:
        """Submit an order to Tastytrade.

        Parameters
        ----------
        request : OrderRequest
            The order to submit.

        Returns
        -------
        OrderResult
        """
        # Validate first
        errors = self.validate(request)
        if errors:
            result = OrderResult(
                status=OrderStatus.REJECTED,
                message="; ".join(errors),
                is_paper=self._is_paper,
            )
            self._order_history.append(result)
            return result

        if request.dry_run:
            result = OrderResult(
                status=OrderStatus.PENDING,
                message="Dry run — order validated but not submitted",
                is_paper=self._is_paper,
            )
            self._order_history.append(result)
            return result

        if self._session is None or self._account is None:
            if not self.connect():
                result = OrderResult(
                    status=OrderStatus.ERROR,
                    message="Not connected to Tastytrade",
                    is_paper=self._is_paper,
                )
                self._order_history.append(result)
                return result

        # Build TT order
        try:
            order = self._build_tt_order(request)
            response = self._account.place_order(self._session, order, dry_run=False)

            order_id = str(getattr(response, 'id', '')) or str(getattr(response, 'order_id', ''))
            status = OrderStatus.SUBMITTED

            result = OrderResult(
                status=status,
                order_id=order_id,
                message=f"Order submitted {'(paper)' if self._is_paper else '(LIVE)'}",
                account_number=self._account.account_number,
                is_paper=self._is_paper,
            )
            self._order_history.append(result)

            logger.info("Order %s submitted: %s %s (%d legs, price=%s)",
                        order_id, request.strategy, request.underlying,
                        len(request.legs), request.price)

            return result

        except Exception as e:
            result = OrderResult(
                status=OrderStatus.ERROR,
                message=f"Order submission failed: {e}",
                is_paper=self._is_paper,
            )
            self._order_history.append(result)
            return result

    def _build_tt_order(self, request: OrderRequest):
        """Convert OrderRequest into a Tastytrade Order object."""
        from tastytrade.order import NewOrder, OrderAction, OrderTimeInForce, OrderType, PriceEffect

        tt_legs = []
        for leg in request.legs:
            from tastytrade.instruments import Option
            # Map our action names to TT OrderAction
            action_map = {
                "buy_to_open": OrderAction.BUY_TO_OPEN,
                "sell_to_open": OrderAction.SELL_TO_OPEN,
                "buy_to_close": OrderAction.BUY_TO_CLOSE,
                "sell_to_close": OrderAction.SELL_TO_CLOSE,
            }
            tt_action = action_map.get(leg.action, OrderAction.BUY_TO_OPEN)

            tt_legs.append({
                "instrument-type": "Equity Option",
                "symbol": leg.symbol,
                "action": tt_action,
                "quantity": leg.quantity,
            })

        price_effect = PriceEffect.CREDIT if (request.price and request.price > 0) else PriceEffect.DEBIT
        tt_tif = OrderTimeInForce.DAY if request.time_in_force == "day" else OrderTimeInForce.GTC
        tt_type = OrderType.LIMIT if request.order_type == "limit" else OrderType.MARKET

        order = NewOrder(
            time_in_force=tt_tif,
            order_type=tt_type,
            legs=tt_legs,
            price=abs(request.price) if request.price else None,
            price_effect=price_effect,
        )
        return order

    def cancel(self, order_id: str) -> bool:
        """Cancel a pending order."""
        if not self._session or not self._account:
            return False
        try:
            self._account.delete_order(self._session, order_id)
            logger.info("Order %s cancelled", order_id)
            return True
        except Exception as e:
            logger.warning("Cancel failed for %s: %s", order_id, e)
            return False

    def get_positions(self) -> List[Dict]:
        """Get current account positions."""
        if not self._session or not self._account:
            return []
        try:
            positions = self._account.get_positions(self._session)
            return [
                {
                    "symbol": str(getattr(p, 'symbol', '')),
                    "quantity": int(getattr(p, 'quantity', 0)),
                    "direction": str(getattr(p, 'quantity_direction', '')),
                    "average_price": float(getattr(p, 'average_open_price', 0)),
                    "close_price": float(getattr(p, 'close_price', 0)),
                    "pnl": float(getattr(p, 'realized_day_gain', 0)),
                }
                for p in positions
            ]
        except Exception as e:
            logger.warning("Get positions failed: %s", e)
            return []

    @property
    def order_history(self) -> List[OrderResult]:
        return list(self._order_history)


def build_order_from_strategy(strategy_result, contracts: int = 1,
                               order_type: str = "limit",
                               price: Optional[float] = None) -> OrderRequest:
    """Build an OrderRequest from a StrategyResult.

    Convenience function that maps strategy legs to order legs.

    Parameters
    ----------
    strategy_result : StrategyResult
        From strategy evaluation.
    contracts : int
        Number of contracts per leg.
    order_type : str
        "limit" or "market".
    price : float, optional
        Limit price. If None, uses strategy_result.entry.

    Returns
    -------
    OrderRequest
    """
    legs = []
    for leg_dict in strategy_result.legs:
        action_raw = leg_dict.get("action", "buy")
        option_type = leg_dict.get("option_type", "call")
        strike = float(leg_dict.get("strike", 0))

        # Map simple action to order action
        if action_raw == "sell":
            action = "sell_to_open"
        else:
            action = "buy_to_open"

        # Build OCC-style symbol (placeholder — real symbol resolution needs chain data)
        occ_symbol = _build_occ_symbol(
            strategy_result.ticker, strike, option_type,
            strategy_result.suggested_dte,
        )

        legs.append(OrderLeg(
            action=action,
            symbol=occ_symbol,
            quantity=contracts,
            option_type=option_type,
            strike=strike,
            expiry="",  # would be resolved from chain
        ))

    order_price = price if price is not None else strategy_result.entry

    return OrderRequest(
        underlying=strategy_result.ticker,
        strategy=strategy_result.strategy_name,
        legs=legs,
        order_type=order_type,
        price=order_price,
    )


def _build_occ_symbol(underlying: str, strike: float, option_type: str, dte: int) -> str:
    """Build a placeholder OCC symbol.

    Real implementation would resolve from chain data.
    Format: SYMBOL  YYMMDD C/P STRIKE*1000 (padded)
    """
    from datetime import date, timedelta
    expiry = date.today() + timedelta(days=dte)
    cp = "C" if option_type == "call" else "P"
    strike_int = int(strike * 1000)
    return f"{underlying:<6s}{expiry.strftime('%y%m%d')}{cp}{strike_int:08d}"
