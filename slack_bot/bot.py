"""Slack bot for the Espresso Club.

Commands (slash):
    /espresso join              — onboard yourself
    /espresso topup [amount]    — get a top-up invoice (default $10)
    /espresso balance           — show your current balance
    /espresso leaderboard       — top spenders this month

Background (cron, daily at 9am local time):
    DM users whose balance is below LOW_BALANCE_THRESHOLD_USD with a top-up link.
    Post a weekly leaderboard summary to a configured channel.

Configuration via env vars:
    SLACK_BOT_TOKEN, SLACK_APP_TOKEN — Bolt SDK socket-mode credentials
    ESPRESSO_APP_URL                 — base URL of the espresso app
    LOW_BALANCE_THRESHOLD_USD        — default $2.00
    LEADERBOARD_CHANNEL              — channel id for weekly summary (optional)
"""

from __future__ import annotations

import logging
import os

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler


log = logging.getLogger("espresso-bot")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s: %(message)s")

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
ESPRESSO_APP_URL = os.environ.get("ESPRESSO_APP_URL", "http://espresso-app:8080")
LOW_BALANCE_USD = float(os.environ.get("LOW_BALANCE_THRESHOLD_USD", "2.00"))
LEADERBOARD_CHANNEL = os.environ.get("LEADERBOARD_CHANNEL")

if not (SLACK_BOT_TOKEN and SLACK_APP_TOKEN):
    raise SystemExit("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set")

app = App(token=SLACK_BOT_TOKEN)


def call_app(method: str, path: str, **kwargs) -> dict:
    with httpx.Client(timeout=10.0) as client:
        r = client.request(method, f"{ESPRESSO_APP_URL}{path}", **kwargs)
        r.raise_for_status()
        return r.json() if r.content else {}


# ---- slash command --------------------------------------------------------

@app.command("/espresso")
def handle_espresso(ack, body, respond, client):
    ack()
    text = (body.get("text") or "").strip().lower()
    slack_user = body["user_id"]
    args = text.split()
    sub = args[0] if args else "help"

    if sub == "join":
        # We don't carry the user's real name from Slack — they need to
        # confirm. Send a link.
        respond(
            f"To join the Espresso Club, visit {ESPRESSO_APP_URL}/onboard "
            "and tap your NFC card on the office reader within 30 seconds."
        )
        return

    if sub == "balance":
        u = call_app("GET", f"/api/slack/user/{slack_user}")
        if not u.get("found"):
            respond("You're not registered yet — type `/espresso join`.")
            return
        respond(f"Hi {u['name']} — balance: *${u['balance_usd']:.2f}*")
        return

    if sub == "topup":
        amount = float(args[1]) if len(args) > 1 else 10.0
        u = call_app("GET", f"/api/slack/user/{slack_user}")
        if not u.get("found"):
            respond("You're not registered yet — type `/espresso join`.")
            return
        respond(
            f"Tap to top up *${amount:.2f}*: "
            f"{ESPRESSO_APP_URL}/topup/{u['id']}"
        )
        return

    if sub == "leaderboard":
        rows = call_app("GET", "/api/leaderboard")
        if not rows:
            respond("Leaderboard is empty — go drink some coffee!")
            return
        lines = [
            f"{i+1}. {r['name']} — {r['drinks']} drinks, ${r['usd']:.2f}"
            for i, r in enumerate(rows[:10])
        ]
        respond("☕ *Top caffeine consumers (30 days)*\n" + "\n".join(lines))
        return

    respond(
        "Espresso Club commands:\n"
        "• `/espresso join` — onboard\n"
        "• `/espresso balance` — check your balance\n"
        "• `/espresso topup [amount]` — top-up link (default $10)\n"
        "• `/espresso leaderboard` — top 10 this month"
    )


# ---- daily low-balance pings ----------------------------------------------

def daily_low_balance_pings():
    log.info("running daily low-balance scan…")
    rows = call_app("GET", f"/api/low-balance?threshold_usd={LOW_BALANCE_USD}")
    for u in rows:
        if not u.get("slack_user_id"):
            continue
        try:
            app.client.chat_postMessage(
                channel=u["slack_user_id"],
                text=(f"Hey {u['name']}, your espresso balance is "
                      f"*${u['balance_usd']:.2f}*. Top up: "
                      f"{ESPRESSO_APP_URL}/topup/{u['id']}"),
            )
        except Exception as e:
            log.warning("ping failed for %s: %s", u["name"], e)


def weekly_leaderboard():
    if not LEADERBOARD_CHANNEL:
        return
    rows = call_app("GET", "/api/leaderboard")
    if not rows:
        return
    lines = [
        f"{i+1}. {r['name']} — {r['drinks']} drinks, ${r['usd']:.2f}"
        for i, r in enumerate(rows[:5])
    ]
    app.client.chat_postMessage(
        channel=LEADERBOARD_CHANNEL,
        text="☕ *This week's caffeine champions*\n" + "\n".join(lines),
    )


def main():
    scheduler = BackgroundScheduler()
    scheduler.add_job(daily_low_balance_pings, "cron", hour=9, minute=0)
    scheduler.add_job(weekly_leaderboard, "cron", day_of_week="fri", hour=16)
    scheduler.start()
    log.info("Slack bot ready (low-balance threshold = $%.2f)", LOW_BALANCE_USD)
    SocketModeHandler(app, SLACK_APP_TOKEN).start()


if __name__ == "__main__":
    main()
