#!/usr/bin/env python3
"""Starting point for your own connector. Copy this folder, rename it, fill in handle().

A connector is any program that reads a monitor's events.jsonl and does something
with each event: send a Slack or Telegram message, light a lamp, log to a sheet.
The monitors know nothing about connectors, so you never need to change them.

    python3 connector.py --events ../../palace/events.jsonl --from-start --once

The event format is described in ../README.md.
"""
import argparse
import json
import os
import time


def handle(event):
    """Called once per event. Replace the body with what your connector should do."""
    if event.get("type") == "checkout_opened":
        print(f"Checkout open for {event.get('cart')}: {', '.join(event.get('items', []))}")
    else:
        print(f"{event.get('ts')}  {event.get('type')}")


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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", required=True, help="path to a monitor's events.jsonl")
    ap.add_argument("--from-start", action="store_true", help="also handle events already in the file")
    ap.add_argument("--once", action="store_true", help="stop at the end of the file")
    a = ap.parse_args()
    try:
        for e in follow(a.events, a.from_start, keep_going=not a.once):
            handle(e)
    except KeyboardInterrupt:
        print()
