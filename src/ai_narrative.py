"""
AI synthesis of the full options opportunity set.

Sends a compact JSON summary to the configured AI provider (SYNTHESIS_PROVIDER)
and returns an analyst-style narrative. Reuses TC's existing config vars
so no additional env configuration is needed.
"""
import json
import logging
import os
from typing import Any, Dict, List

import anthropic
import openai

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SYNTHESIS_PROVIDER = os.getenv("SYNTHESIS_PROVIDER", "anthropic")

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a professional options trader and market analyst.
You will receive structured JSON output from an options opportunity scanner.
Some tickers also include KNOWLEDGE BASE STRATEGIES — book-grounded setups retrieved
from technical analysis literature via RAG. When present, incorporate these into your
analysis and note whether the quantitative opportunity aligns with or contradicts the
book-derived strategy.

Your task:
1. For each ticker, state the directional thesis in one sentence and justify it with the key TA signals.
2. Identify the most compelling trade across the three outlooks (short/medium/long) and explain why —
   referencing specific entry, exit, and stop levels.
3. If knowledge base strategies are present, note whether they support or conflict with the scan output.
4. Flag the primary risk for each trade (IV regime, theta decay, binary event, spread width, etc.).
5. If there are cross-ticker themes (e.g., broad-market setup, sector correlation), note them briefly.

Tone: direct, specific, data-driven. No filler sentences.
Format: one section per ticker, with a header like "AAPL —", then bullet points.
Total length: under 600 words."""


def _build_prompt(results: List[Dict[str, Any]]) -> str:
    summary = []
    for r in results:
        if "error" in r:
            continue
        entry = {
            "ticker":               r["ticker"],
            "name":                 r.get("name", ""),
            "price":                r["current_price"],
            "knowledge_strategies": r.get("knowledge_strategies"),
            "opportunities": [
                {
                    "outlook":           o["outlook"],
                    "dte":               o["dte"],
                    "bias":              o["bias"],
                    "bias_score":        o["bias_score"],
                    "strategy":          o["strategy"],
                    "strike":            o.get("legs", [{}])[0].get("strike"),
                    "expiry":            o["expiry"],
                    "iv":                o.get("legs", [{}])[0].get("iv"),
                    "hist_vol":          o["hist_vol"],
                    "iv_vs_hv":          o["iv_vs_hv"],
                    "entry":             o["entry"],
                    "exit_target":       o["exit_target"],
                    "exit_pct":          o["exit_pct"],
                    "target_underlying": o["target_underlying"],
                    "option_stop":       o["option_stop"],
                    "underlying_stop":   o["underlying_stop"],
                    "prob_profit":       o["prob_profit"],
                    "delta":             o["delta"],
                    "theta":             o["theta"],
                    "nearest_resistance":o["nearest_resistance"],
                    "nearest_support":   o["nearest_support"],
                }
                for o in r["opportunities"]
            ],
        }
        summary.append(entry)

    return json.dumps(summary, indent=2)


def generate_narrative(results: List[Dict[str, Any]]) -> str:
    """Generate scan synthesis via SYNTHESIS_PROVIDER (inherits TC's provider setting)."""
    prompt = _build_prompt(results)
    user_msg = f"Scanner results:\n\n{prompt}"

    provider = SYNTHESIS_PROVIDER
    try:
        if provider == "anthropic":
            if not ANTHROPIC_API_KEY:
                raise RuntimeError("ANTHROPIC_API_KEY is not set.")
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=700,
                temperature=0.3,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            return msg.content[0].text

        elif provider == "openai":
            if not OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY is not set.")
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model="gpt-4o",
                max_tokens=700,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
            )
            return resp.choices[0].message.content or ""

        else:
            raise ValueError(f"Unknown SYNTHESIS_PROVIDER: {provider!r}")

    except Exception as exc:
        logger.error(f"Options AI narrative failed: {exc}")
        return f"[AI narrative error — provider={provider}: {exc}]"
