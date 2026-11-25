#!/usr/bin/env python3
"""Watch a standard Shopify store and jump to checkout the moment an item is buyable.

Works on stores that expose Shopify's public storefront feeds (/products.json).
It does not work on headless stores such as Palace; use palace_monitor.py there.

What it does
  - Polls a collection's public product feed and/or the newest products store-wide,
    matched by vendor name or by words in the title.
  - For each matching product, checks how it is sold:
      * draw / lottery (requires a selling plan) -> opens the product page so you can
        enter by hand. Speed does not matter for a draw.
      * normal product -> opens a Shopify cart link for your size, which lands you
        directly on checkout with the item already in the cart.
  - You finish payment yourself in your own browser (Shop Pay makes that one tap).

What it deliberately does not do
  - No captcha or bot-check solving, no proxies, no multiple identities, no payment entry.

Usage
  python3 shopify_monitor.py --base https://store.example --collection drop-handle \
      --title-words "word1,word2" --only "jacket" --size L,XL --shop-pay --browser "Google Chrome"
  python3 shopify_monitor.py --base https://store.example --collection all --dry-run --once   # self-test
"""
import argparse
import json
import os
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import webbrowser

BASE = ""  # set from --base in main()
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HONEST_UA = "shopify-scripting/1.0 (+https://github.com/DaanveerH/shopify-scripting)"
UA = BROWSER_UA  # set from --user-agent in main()


def norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def get_json(path):
    """GET a JSON endpoint. Returns (status, data_or_None)."""
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return 0, None


EVENTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "events.jsonl")  # --events


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def emit(event_type, **fields):
    """Append one event to events.jsonl. Connectors (Discord and others) read this file."""
    if not EVENTS:
        return
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": "shopify", "type": event_type}
    record.update(fields)
    try:
        with open(EVENTS, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def notify(title, body):
    sys.stdout.write("\a")
    if sys.platform == "darwin":
        script = f"display notification {json.dumps(body)} with title {json.dumps(title)} sound name \"Glass\""
        subprocess.run(["osascript", "-e", script], capture_output=True)


def open_url(url, args, lane="main"):
    """Main lane: the browser signed in to Shop Pay, else the system default.

    Second lane (--also items): a *different* browser, opened in the background, or
    nothing at all. A cart link replaces the cart of the browser it opens in, so the
    second lane must never touch the main browser while the main checkout is open.
    """
    if lane == "also":
        if not args.also_browser or sys.platform != "darwin":
            return  # link is printed and notified only
        if subprocess.run(["open", "-g", "-a", args.also_browser, url], capture_output=True).returncode != 0:
            log(f"  could not open {args.also_browser!r}; use the printed link once the main order is paid")
        return
    if args.browser and sys.platform == "darwin":
        if subprocess.run(["open", "-a", args.browser, url], capture_output=True).returncode == 0:
            return
        log(f"  could not open {args.browser!r}, falling back to the default browser")
    webbrowser.open(url)


def pick_variant(product, sizes):
    """First available variant, honouring size preference order. None if nothing fits."""
    available = [v for v in product["variants"] if v.get("available")]
    if not available:
        return None
    if len(product["variants"]) == 1:
        return available[0]
    for want in sizes:
        for v in available:
            if want in [norm(o) for o in v.get("options", [])]:
                return v
    return None


def handle_product(handle, args, done, lane="main"):
    """Decide what to do with one product. Returns True once it needs no more attention."""
    status, p = get_json(f"/products/{handle}.js")
    if p is None:
        if (handle, status) not in done["missing"]:
            done["missing"].add((handle, status))
            log(f"  {handle}: product page returned {status}, watching for it")
        return False
    if any(h == handle for h, _ in done["missing"]):
        done["missing"] = {(h, s) for h, s in done["missing"] if h != handle}
        log(f"  LIVE   {p['title']}: product page is now published")

    url = f"{BASE}/products/{handle}"
    title = p["title"] + (" [2nd lane]" if lane == "also" else "")
    sizes = args.also_size if lane == "also" else args.size

    if p.get("requires_selling_plan"):
        # Announce the draw once, then keep polling: the store may reopen the
        # same product as a normal first-come sale after the draw closes.
        if handle not in done["draw"]:
            done["draw"].add(handle)
            plans = [s["name"] for g in p.get("selling_plan_groups", []) for s in g["selling_plans"]]
            log(f"  DRAW   {title}: lottery entry, not first-come ({plans[0] if plans else 'selling plan'})")
            log(f"         enter here: {url}")
            emit("draw_open", title=title, url=url)
            if not args.dry_run and not args.no_draw_tab:
                open_url(url, args, lane)
                notify("Draw entry open", title)
        return False

    if handle in done["draw"]:
        log(f"  SWITCH {title}: no longer draw-only, now a normal sale")
        done["draw"].discard(handle)

    variant = pick_variant(p, sizes)
    if variant is None:
        in_stock = [v["title"] for v in p["variants"] if v.get("available")]
        if in_stock and not sizes:
            log(f"  OPEN   {title}: no size given, product page: {url} ({', '.join(in_stock)})")
            if not args.dry_run:
                open_url(url, args, lane)
                notify("Drop is live", title)
            return True
        if handle not in done["waiting"]:
            state = f"your sizes not in stock (have: {', '.join(in_stock)})" if in_stock else "not buyable yet"
            log(f"  WAIT   {title}: {state}, still watching")
            done["waiting"].add(handle)
        return False

    if lane == "main" and args.bundle:
        # Collected now, opened together by flush_bundle() once every main item was checked.
        done["bundle"].append((title, variant))
        return True

    link = f"{BASE}/cart/{variant['id']}:{args.qty}" + ("?payment=shop_pay" if args.shop_pay else "")
    log(f"  BUY    {title} / {variant['title']}: {variant['price'] / 100:.2f}")
    log(f"         checkout link: {link}")
    emit("cart_built", cart=lane, items=[f"{title} / {variant['title']}"],
         total=f"{variant['price'] / 100:.2f}", checkout_url=link)
    hold = False
    if lane == "also":
        # One checkout per browser: a second cart link would replace the first one's cart.
        hold = not args.also_browser or done.get("also_open", False)
        if not args.also_browser:
            log("         NOT opened: pay for the main item first, then use this link")
        elif hold:
            log(f"         NOT opened: {args.also_browser} already holds a checkout; use this link after that order is paid")
        else:
            done["also_open"] = True
            log(f"         opened in {args.also_browser} (background): pay for the main item first, then switch to it")
    if not args.dry_run:
        if not hold:
            open_url(link, args, lane)
            emit("checkout_opened", cart=lane, items=[f"{title} / {variant['title']}"],
                 total=f"{variant['price'] / 100:.2f}")
        notify("Second item ready" if lane == "also" else "Checkout ready", f"{title} / {variant['title']}")
    return True


def flush_bundle(args, done):
    """Open every main item found buyable in this poll as ONE checkout in the main browser.

    A cart link replaces the browser's cart, so the main browser gets exactly one link,
    ever. Items that only become buyable in a later poll go to the second browser (one
    checkout there too), or are printed for use after the first order is paid.
    """
    items, done["bundle"] = done["bundle"], []
    if not items:
        return
    pay = "?payment=shop_pay" if args.shop_pay else ""
    for title, v in items:
        log(f"  BUY    {title} / {v['title']}: {v['price'] / 100:.2f}")

    if not done.get("main_open"):
        done["main_open"] = True
        link = f"{BASE}/cart/" + ",".join(f"{v['id']}:{args.qty}" for _, v in items) + pay
        log(f"         ONE checkout for {len(items)} item(s): {link}")
        names = [f"{t} / {v['title']}" for t, v in items]
        total = f"{sum(v['price'] for _, v in items) / 100:.2f}"
        emit("cart_built", cart="main", items=names, total=total, checkout_url=link)
        if not args.dry_run:
            open_url(link, args)
            emit("checkout_opened", cart="main", items=names, total=total)
            notify("Checkout ready", " + ".join(t for t, _ in items))
        return

    for title, v in items:
        link = f"{BASE}/cart/{v['id']}:{args.qty}{pay}"
        log(f"         late item, separate checkout: {link}")
        if args.also_browser and not done.get("also_open"):
            done["also_open"] = True
            log(f"         opened in {args.also_browser} (background): finish the first order, then switch to it")
            if not args.dry_run:
                open_url(link, args, "also")
        else:
            log("         NOT opened: use this link after the open order is paid")
        if not args.dry_run:
            notify("Another item ready", f"{title} / {v['title']}")


def lane_for(title, args):
    """'main', 'also', or None (ignore) for a product title."""
    t = norm(title)
    if any(w in t for w in args.exclude):
        return None
    if not args.only or any(w in t for w in args.only):
        return "main"
    if any(w in t for w in args.also):
        return "also"
    return None


def discover(args, tick):
    """Return {handle: title} for products currently visible in the drop."""
    found = {}
    status, data = (None, None)
    if args.collection:
        status, data = get_json(f"/collections/{args.collection}/products.json?limit=250")
    if data and data["products"]:
        for p in data["products"]:
            found[p["handle"]] = p["title"]
    elif status == 200:
        status = 404  # Shopify serves an empty 200 feed for an unpublished collection
    elif status not in (404, None):
        log(f"collection feed returned {status}")

    # The store feed is sorted newest-published first, so the top of it is enough
    # to catch a drop the moment it is published, and small enough to read every poll.
    if args.vendor or args.title_words:
        _, data = get_json(f"/products.json?limit={args.feed_limit}")
        if data:
            for p in data["products"]:
                title = norm(p["title"])
                if (args.vendor and args.vendor in norm(p["vendor"])) or any(w in title for w in args.title_words):
                    found[p["handle"]] = p["title"]
    return found, status


def main():
    global BASE, EVENTS, UA
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="store address, e.g. https://www.example.com")
    ap.add_argument("--collection", default="", help="collection handle to watch (the part after /collections/)")
    ap.add_argument("--vendor", default="", help="also match the newest store products by vendor name")
    ap.add_argument("--title-words", default="", help="also match the newest store products whose title has any of these words")
    ap.add_argument("--size", default="", help="size preference order, e.g. L,XL")
    ap.add_argument("--only", default="", help="only act on titles containing one of these words")
    ap.add_argument("--qty", type=int, default=1)
    ap.add_argument("--interval", type=float, default=4.0, help="seconds between polls (min 2)")
    ap.add_argument("--dry-run", action="store_true", help="print links, do not open the browser")
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    ap.add_argument("--no-draw-tab", action="store_true", help="do not open draw pages (already entered)")
    ap.add_argument("--shop-pay", action="store_true", help="send the cart link straight to Shop Pay checkout")
    ap.add_argument("--browser", default="", help='macOS app to open links in, e.g. "Google Chrome"')
    ap.add_argument("--also", default="", help="second-lane items (title words); needs --only for the main item")
    ap.add_argument("--bundle", action="store_true",
                    help="put all main items buyable in the same poll into one checkout")
    ap.add_argument("--handle", default="", help="main-item product address(es) to poll directly, comma-separated")
    ap.add_argument("--feed-limit", type=int, default=60, help="how many newest store products to scan each poll")
    ap.add_argument("--exclude", default="", help="never act on titles containing one of these words, e.g. kids")
    ap.add_argument("--also-size", default=None, help="size order for second-lane items (default: same as --size)")
    ap.add_argument("--also-browser", default="", help='different macOS browser for second-lane links, e.g. "Safari"; '
                                                        "omit to only print them")
    ap.add_argument("--user-agent", default="browser",
                    help='how requests introduce themselves: "browser" (default), "honest", or your own text')
    ap.add_argument("--events", default=EVENTS, help="JSON-lines event file for connectors (default events.jsonl)")
    args = ap.parse_args()
    BASE, EVENTS = args.base.rstrip("/"), args.events
    UA = {"browser": BROWSER_UA, "honest": HONEST_UA}.get(args.user_agent, args.user_agent)
    emit("monitor_started", site=BASE, dry_run=args.dry_run)
    split = lambda s: [norm(x.strip()) for x in (s or "").split(",") if x.strip()]
    args.title_words = split(args.title_words)
    if not (args.collection or args.vendor or args.title_words):
        ap.error("give at least one of --collection, --vendor, --title-words")
    args.size, args.only, args.also = split(args.size), split(args.only), split(args.also)
    args.exclude = split(args.exclude)
    args.handle = [h.strip() for h in args.handle.split(",") if h.strip()]
    args.also_size = args.size if args.also_size is None else split(args.also_size)
    args.vendor = norm(args.vendor)
    args.interval = max(2.0, args.interval)
    if args.also and not args.only:
        ap.error("--also needs --only, so the main item is unambiguous")
    if args.also_browser and norm(args.also_browser) == norm(args.browser or ""):
        ap.error("--also-browser must differ from --browser: a second cart link in the same browser "
                 "would replace the main checkout's cart")

    log(f"watching {BASE}"
        + (f" /collections/{args.collection}" if args.collection else "")
        + (f" + vendor~'{args.vendor}'" if args.vendor else "")
        + (f" + title words {args.title_words}" if args.title_words else "")
        + (f" | sizes {args.size}" if args.size else " | no size preference")
        + (" | DRY RUN" if args.dry_run else ""))
    if args.also:
        log(f"second lane: {args.also} -> " + (args.also_browser or "links printed only, nothing opened"))

    done = {"handled": set(), "waiting": set(), "draw": set(), "missing": set(), "bundle": []}
    known = {}  # every product seen so far; re-polled each tick until handled
    # Product addresses known in advance are polled directly from the first tick,
    # so their return is seen even if no feed lists them yet.
    for h in args.handle:
        known[h] = args.only[0] if args.only else h
    tick, backoff, last_status = 0, 0.0, None
    while True:
        found, status = discover(args, tick)
        known.update(found)
        if status != last_status and status is not None:
            log({404: "collection not published yet (404)", 200: "collection is live"}.get(status, f"collection status {status}"))
            last_status = status
        backoff = min(60.0, backoff * 2 or 10.0) if status in (429, 430, 503) else 0.0

        # Main-lane items are always checked first; second-lane items only after.
        lanes = {"main": [], "also": []}
        for handle, title in known.items():
            if handle in done["handled"]:
                continue
            lane = lane_for(title, args)
            if lane:
                lanes[lane].append(handle)
        for lane in ("main", "also"):
            for handle in lanes[lane]:
                if handle_product(handle, args, done, lane):
                    done["handled"].add(handle)
            if lane == "main":
                flush_bundle(args, done)

        if args.once:
            break
        tick += 1
        time.sleep(args.interval + backoff)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
