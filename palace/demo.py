#!/usr/bin/env python3
"""See a whole drop happen in about 15 seconds, on your own computer.

    python3 demo.py           # nothing opens; watch the log
    python3 demo.py --open    # also opens the two pretend checkout pages in your browser

It starts a pretend shop (fake_shop.py) that is "closed" for a few seconds and then
"drops", and runs the real monitor against it with carts.example.json.
No real shop is contacted and nothing can be bought.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time

import fake_shop

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--open", action="store_true", help="open the pretend checkout pages in your default browser")
    ap.add_argument("--carts", default=os.path.join(HERE, "carts.example.json"))
    ap.add_argument("--closed-for", type=float, default=5)
    args = ap.parse_args()

    _, url, _ = fake_shop.start(closed_for=args.closed_for, locked_for=2)
    print(f"Pretend shop running at {url}. It is closed for {args.closed_for:.0f} seconds, then it drops.\n", flush=True)

    out = tempfile.mkdtemp(prefix="palace-demo-")
    cmd = [sys.executable, os.path.join(HERE, "palace_monitor.py"), "--carts", args.carts,
           "--drop", time.strftime("%H:%M"), "--wait", "3", "--browser", "default",
           "--log", os.path.join(out, "monitor.log"), "--events", os.path.join(out, "events.jsonl")]
    if not args.open:
        cmd += ["--dry-run", "--test-cart"]
    code = subprocess.run(cmd, env=dict(os.environ, PALACE_SITE=url, PALACE_CHECKOUT=url)).returncode

    print(f"\nThat was the whole flow. The events a connector would receive are in {out}/events.jsonl")
    if args.open:
        print("The pretend checkout pages are served by this script. Press Ctrl-C when you have seen them.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print()
    return code


if __name__ == "__main__":
    sys.exit(main())
