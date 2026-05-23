"""
DXFeed streamer for live option quotes via Tastytrade's DXLink WebSocket.

Connects to TT's streaming API and publishes real-time quotes (bid/ask/greeks)
for subscribed option symbols. Used to power the WS /ws/greeks endpoint.

Options Analytics Team — 2026-04
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class StreamerState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    SUBSCRIBED = "subscribed"
    ERROR = "error"


@dataclass
class QuoteUpdate:
    """A single streaming quote update for an option contract."""
    symbol: str             # streamer symbol (e.g. ".SPY260417C590")
    bid: float
    ask: float
    mid: float
    last: float
    volume: int
    iv: float               # implied volatility from feed
    delta: float
    gamma: float
    theta: float
    vega: float
    underlying: float       # underlying spot price
    timestamp: float        # epoch seconds


@dataclass
class DXFeedStreamer:
    """Manages a DXLink WebSocket connection for live option quotes.

    Usage:
        streamer = DXFeedStreamer()
        await streamer.connect()
        streamer.subscribe(["SPY"], max_dte=14)
        async for update in streamer.updates():
            print(update)
    """
    state: StreamerState = StreamerState.DISCONNECTED
    _session: object = field(default=None, repr=False)
    _streamer: object = field(default=None, repr=False)
    _subscriptions: Set[str] = field(default_factory=set)
    _callbacks: List[Callable] = field(default_factory=list)
    _quote_buffer: Dict[str, QuoteUpdate] = field(default_factory=dict)
    _last_update: float = 0.0

    async def connect(self, session=None) -> bool:
        """Connect to DXLink streaming.

        Parameters
        ----------
        session : tastytrade.Session, optional
            Existing TT session. If None, creates one from env vars.

        Returns
        -------
        bool — True if connected successfully.
        """
        self.state = StreamerState.CONNECTING

        try:
            if session is None:
                from tastytrade import Session
                username = os.getenv("TT_USERNAME", "")
                password = os.getenv("TT_PASSWORD", "")
                if not username or not password:
                    logger.warning("TT credentials not set, cannot start streamer")
                    self.state = StreamerState.ERROR
                    return False
                is_test = os.getenv("TT_SANDBOX", "").lower() in ("1", "true", "yes")
                session = Session(login=username, password=password, is_test=is_test)

            self._session = session

            from tastytrade import DXLinkStreamer
            self._streamer = await DXLinkStreamer.create(session)

            self.state = StreamerState.CONNECTED
            logger.info("DXLink streamer connected")
            return True

        except ImportError:
            logger.warning("tastytrade package not available for streaming")
            self.state = StreamerState.ERROR
            return False
        except Exception as e:
            logger.warning("DXLink connection failed: %s", e)
            self.state = StreamerState.ERROR
            return False

    async def subscribe(self, symbols: List[str], max_dte: int = 14) -> int:
        """Subscribe to option quotes for given underlying symbols.

        Fetches the option chain for each symbol and subscribes to
        streamer symbols for contracts within max_dte.

        Returns the number of contracts subscribed.
        """
        if self._streamer is None or self.state not in (StreamerState.CONNECTED, StreamerState.SUBSCRIBED):
            logger.warning("Cannot subscribe — streamer not connected")
            return 0

        try:
            from tastytrade.instruments import get_option_chain
            from tastytrade.dxfeed import Quote, Greeks

            streamer_symbols = []
            for symbol in symbols:
                chain = get_option_chain(self._session, symbol)
                for expiration in chain:
                    from datetime import datetime
                    exp_dt = datetime.combine(expiration.expiration_date, datetime.min.time())
                    dte = (exp_dt - datetime.now()).days
                    if dte < 0 or dte > max_dte:
                        continue
                    for strike in expiration.strikes:
                        if strike.call_streamer_symbol:
                            streamer_symbols.append(strike.call_streamer_symbol)
                        if strike.put_streamer_symbol:
                            streamer_symbols.append(strike.put_streamer_symbol)

            if streamer_symbols:
                await self._streamer.subscribe(Quote, streamer_symbols)
                await self._streamer.subscribe(Greeks, streamer_symbols)
                self._subscriptions.update(streamer_symbols)
                self.state = StreamerState.SUBSCRIBED
                logger.info("Subscribed to %d option contracts", len(streamer_symbols))

            return len(streamer_symbols)

        except Exception as e:
            logger.warning("Subscription failed: %s", e)
            return 0

    async def listen(self, callback: Optional[Callable] = None):
        """Listen for quote/greeks updates in a loop.

        Parameters
        ----------
        callback : callable, optional
            Called with each QuoteUpdate. If None, updates are buffered
            in self._quote_buffer for polling.
        """
        if self._streamer is None:
            return

        try:
            from tastytrade.dxfeed import Quote, Greeks

            async for event in self._streamer.listen(Quote):
                update = self._process_quote(event)
                if update:
                    self._quote_buffer[update.symbol] = update
                    self._last_update = time.time()
                    if callback:
                        await callback(update) if asyncio.iscoroutinefunction(callback) else callback(update)

        except Exception as e:
            logger.warning("Streamer listen error: %s", e)
            self.state = StreamerState.ERROR

    def _process_quote(self, event) -> Optional[QuoteUpdate]:
        """Convert a DXFeed event to our QuoteUpdate format."""
        try:
            symbol = getattr(event, 'event_symbol', '') or getattr(event, 'symbol', '')
            bid = float(getattr(event, 'bid_price', 0) or 0)
            ask = float(getattr(event, 'ask_price', 0) or 0)
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
            last = float(getattr(event, 'last_price', 0) or 0)
            volume = int(getattr(event, 'day_volume', 0) or 0)

            return QuoteUpdate(
                symbol=symbol,
                bid=bid,
                ask=ask,
                mid=mid,
                last=last,
                volume=volume,
                iv=float(getattr(event, 'volatility', 0) or 0),
                delta=float(getattr(event, 'delta', 0) or 0),
                gamma=float(getattr(event, 'gamma', 0) or 0),
                theta=float(getattr(event, 'theta', 0) or 0),
                vega=float(getattr(event, 'vega', 0) or 0),
                underlying=float(getattr(event, 'underlying_price', 0) or 0),
                timestamp=time.time(),
            )
        except Exception:
            return None

    def get_latest(self, symbol: str = None) -> Dict[str, QuoteUpdate]:
        """Get latest buffered quotes.

        Parameters
        ----------
        symbol : str, optional
            Filter to a single symbol. If None, return all.
        """
        if symbol:
            q = self._quote_buffer.get(symbol)
            return {symbol: q} if q else {}
        return dict(self._quote_buffer)

    async def disconnect(self):
        """Close the streaming connection."""
        if self._streamer:
            try:
                await self._streamer.close()
            except Exception:
                pass
        self._streamer = None
        self._session = None
        self._subscriptions.clear()
        self._quote_buffer.clear()
        self.state = StreamerState.DISCONNECTED
        logger.info("DXLink streamer disconnected")
