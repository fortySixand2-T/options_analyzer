"""
Sentiment module configuration.

All settings are read from environment variables with sensible defaults.
No imports from other src/ packages.
"""
import os


# ── API keys ───────────────────────────────────────────────────────────────────
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
BENZINGA_KEY = os.getenv("BENZINGA_KEY", "")

# ── Provider selection ─────────────────────────────────────────────────────────
# 'newsapi', 'benzinga', 'csv'
NEWS_PROVIDER = os.getenv("SENTIMENT_PROVIDER", "csv")

# Path to CSV file for csv_provider (historical backtesting)
CSV_PATH = os.getenv("SENTIMENT_CSV_PATH", "")

# ── FinBERT ────────────────────────────────────────────────────────────────────
FINBERT_MODEL = os.getenv("FINBERT_MODEL", "ProsusAI/finbert")
FINBERT_BATCH_SIZE = int(os.getenv("FINBERT_BATCH_SIZE", "32"))
FINBERT_MAX_LENGTH = int(os.getenv("FINBERT_MAX_LENGTH", "128"))

# Minimum confidence to include a scored headline in aggregation
MIN_CONFIDENCE = float(os.getenv("SENTIMENT_MIN_CONFIDENCE", "0.5"))

# ── Aggregation windows ───────────────────────────────────────────────────────
# Windows in hours for rolling sentiment aggregation
WINDOWS = {
    "1h": 1.0,
    "6h": 6.0,
    "24h": 24.0,
}

# Exponential decay halflife (hours) — headlines older than this get half weight
DECAY_HALFLIFE_HOURS = float(os.getenv("SENTIMENT_DECAY_HALFLIFE", "4.0"))

# ── Signal thresholds ─────────────────────────────────────────────────────────
# Composite score thresholds for signal labels (range [-1, +1])
STRONG_THRESHOLD = float(os.getenv("SENTIMENT_STRONG_THRESHOLD", "0.4"))
LEAN_THRESHOLD = float(os.getenv("SENTIMENT_LEAN_THRESHOLD", "0.15"))

# Minimum headlines in a window to generate a signal
MIN_HEADLINES = int(os.getenv("SENTIMENT_MIN_HEADLINES", "3"))

# ── Signal composition weights ─────────────────────────────────────────────────
# How the final SentimentSignal.score is composed
SIGNAL_WEIGHTS = {
    "composite": float(os.getenv("SENTIMENT_W_COMPOSITE", "0.40")),
    "velocity": float(os.getenv("SENTIMENT_W_VELOCITY", "0.40")),
    "breadth": float(os.getenv("SENTIMENT_W_BREADTH", "0.20")),
}

# ── Storage ────────────────────────────────────────────────────────────────────
# SQLite database path
SENTIMENT_DB_PATH = os.getenv(
    "SENTIMENT_DB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "sentiment.db",
    ),
)

# ── Ticker mapping ─────────────────────────────────────────────────────────────
# Headlines about indices or macro news get mapped to these tickers
MACRO_TICKERS = {"SPX", "SPY", "QQQ", "IWM", "DIA"}

# Keywords that indicate macro/index-level news (mapped to ticker 'MACRO')
MACRO_KEYWORDS = [
    "fed", "fomc", "cpi", "ppi", "jobs", "nonfarm", "gdp", "inflation",
    "treasury", "rate cut", "rate hike", "s&p", "dow", "nasdaq",
    "market rally", "market sell", "recession", "tariff",
]
