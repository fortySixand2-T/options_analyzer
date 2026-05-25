"""Webhook notification dispatcher — sends alerts to external services.

Supports Discord, Slack, Telegram, and generic webhook URLs.
Uses requests (already in requirements).
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TIMEOUT = 10


def send_discord(url: str, title: str, body: str = "") -> bool:
    """Send notification to Discord via webhook."""
    try:
        payload = {
            "embeds": [{
                "title": title,
                "description": body,
                "color": 2067276,  # teal
            }]
        }
        resp = requests.post(url, json=payload, timeout=TIMEOUT)
        return resp.status_code in (200, 204)
    except Exception as e:
        logger.warning("Discord webhook failed: %s", e)
        return False


def send_slack(url: str, title: str, body: str = "") -> bool:
    """Send notification to Slack via incoming webhook."""
    try:
        text = f"*{title}*\n{body}" if body else f"*{title}*"
        resp = requests.post(url, json={"text": text}, timeout=TIMEOUT)
        return resp.status_code == 200
    except Exception as e:
        logger.warning("Slack webhook failed: %s", e)
        return False


def send_telegram(bot_token: str, chat_id: str, title: str, body: str = "") -> bool:
    """Send notification via Telegram Bot API."""
    try:
        text = f"<b>{title}</b>\n{body}" if body else f"<b>{title}</b>"
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=TIMEOUT)
        return resp.status_code == 200
    except Exception as e:
        logger.warning("Telegram notification failed: %s", e)
        return False


def send_generic_webhook(url: str, title: str, body: str = "") -> bool:
    """Send notification to a generic webhook URL (POST JSON)."""
    try:
        payload = {"title": title, "body": body, "source": "options-analyzer"}
        resp = requests.post(url, json=payload, timeout=TIMEOUT)
        return 200 <= resp.status_code < 300
    except Exception as e:
        logger.warning("Generic webhook failed: %s", e)
        return False


def dispatch_webhook(webhook_type: str, config: dict, title: str, body: str = "") -> bool:
    """Dispatch a notification via the appropriate webhook type."""
    url = config.get("url", "")

    if webhook_type == "discord":
        return send_discord(url, title, body)
    elif webhook_type == "slack":
        return send_slack(url, title, body)
    elif webhook_type == "telegram":
        return send_telegram(config.get("bot_token", ""), config.get("chat_id", ""), title, body)
    elif webhook_type == "webhook":
        return send_generic_webhook(url, title, body)
    else:
        logger.warning("Unknown webhook type: %s", webhook_type)
        return False
