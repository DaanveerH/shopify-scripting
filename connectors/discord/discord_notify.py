#!/usr/bin/env python3
"""Send drop events to a Discord channel. Python 3.8+, standard library only.

The monitors write one JSON object per line to events.jsonl. This script follows
that file and posts a short message to a Discord webhook for the events that matter.

    export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
    python3 discord_notify.py --events ../../palace/events.jsonl

Try it without Discord (prints what it would send):

    python3 discord_notify.py --events ../../palace/events.jsonl --from-start --dry-run

Checkout links are left out of messages unless you pass --include-checkout-links.
A checkout link lets anyone who has it open your cart, so only turn that on for a
private channel that you alone can read.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# event type -> (colour, headline). Events not listed here are not posted.
STYLE = {
    "monitor_started": (0x5865F2, "Monitor started"),
    "site_state": (0x99AAB5, "Shop status changed"),
    "product_live": (0x57F287, "Product is live"),
    "draw_open": (0xFEE75C, "Draw entry is open"),
    "item_skipped": (0xFEE75C, "Item left out"),
    "cart_built": (0x5865F2, "Cart built"),
    "checkout_opened": (0x57F287, "Checkout is open - review and pay"),
    "cart_failed": (0xED4245, "Cart failed"),
    "monitor_done": (0x99AAB5, "Monitor finished"),
}


def to_message(event, include_checkout_links=False):
    """Turn one event into a Discord webhook payload, or None to skip it."""
    style = STYLE.get(event.get("type"))
    if not style:
        return None
    colour, headline = style
    lines = []
    if event.get("cart"):
        lines.append(f"**{event['cart']}**")
    if event.get("title"):
        lines.append(event["title"])
    for item in event.get("items") or []:
        lines.append(f"• {item}")
    for key, label in (("total", "Total before shipping and tax"), ("stock", "Stock"),
                       ("state", "Status"), ("reason", "Reason"), ("site", "Shop")):
        if event.get(key):
            lines.append(f"{label}: {event[key]}")
    if event.get("url"):
        lines.append(event["url"])
    if include_checkout_links and event.get("checkout_url"):
        lines.append(f"Checkout: {event['checkout_url']}")
    return {"username": "Drop monitor", "embeds": [{
        "title": headline, "description": "\n".join(lines)[:4000], "color": colour,
        "footer": {"text": f"{event.get('source', 'monitor')} • {event.get('ts', '')}"}}]}


def post(webhook, payload):
    req = urllib.request.Request(webhook, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "drop-connector"})
    for _ in range(3):
        try:
            urllib.request.urlopen(req, timeout=10).read()
            return True
        except urllib.error.HTTPError as e:
            if e.code != 429:
                print(f"Discord answered HTTP {e.code}", file=sys.stderr)
                return False
            time.sleep(2)  # rate limited: wait and try again
        except Exception as e:
            print(f"could not reach Discord: {e!r}", file=sys.stderr)
            return False
    return False


def follow(path, from_start=False, keep_going=True):
    """Yield each event in the file, then every new one as the monitor writes it."""
    while not os.path.exists(path):
        if not keep_going:
            return
        time.sleep(1)
    with open(path) as f:
        if not from_start:
            f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                if not keep_going:
                    return
                time.sleep(0.5)
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", required=True, help="path to a monitor's events.jsonl")
    ap.add_argument("--from-start", action="store_true", help="also send events already in the file")
    ap.add_argument("--once", action="store_true", help="stop at the end of the file instead of waiting for more")
    ap.add_argument("--dry-run", action="store_true", help="print messages instead of sending them")
    ap.add_argument("--only", default="", help="comma-separated event types to send (default: all known types)")
    ap.add_argument("--include-checkout-links", action="store_true",
                    help="put checkout links in messages; private channels only")
    args = ap.parse_args()

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook and not args.dry_run:
        sys.exit("set DISCORD_WEBHOOK_URL first, or use --dry-run to see the messages")
    only = {t.strip() for t in args.only.split(",") if t.strip()}

    for event in follow(args.events, args.from_start, keep_going=not args.once):
        if only and event.get("type") not in only:
            continue
        payload = to_message(event, args.include_checkout_links)
        if payload is None:
            continue
        if args.dry_run:
            embed = payload["embeds"][0]
            print(f"--- {embed['title']}\n{embed['description']}\n")
        else:
            post(webhook, payload)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
