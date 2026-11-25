#!/usr/bin/env python3
"""Palace drop monitor. Python 3.8+, standard library only.

Watches a Palace web shop for the products you name. When they go on sale it
builds your cart (or several carts) and opens each checkout page in your own
browser. You review the order and press Pay yourself.

Two ways to say what you want:

  One item, on the command line:
      python3 palace_monitor.py --match "frolic,knit,black" --size L

  Several items in one or more carts, from a file:
      python3 palace_monitor.py --carts carts.json

How it works (all through the shop's own front end):
  detect - GET /collections/<name>.data, the data the collection page renders from.
           While the shop is closed before a drop this answers with a redirect to /password.
  cart   - the same POST /api/cart the Add to Cart button sends, once per item with one
           cookie jar per cart, then GET /cart.data to read back the cart's checkout link.
  gate   - the checkout host's /password page is served while locked and redirects once open.

It never touches payment, never solves a captcha, and adds one unit of each item.
Everything is logged to monitor.log, and written as JSON lines to events.jsonl
for connectors (see ../connectors).
"""
import argparse
import difflib
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

# Defaults are the US shop. The env overrides exist so the whole flow can be run
# against another region's shop, or against the local demo shop (fake_shop.py).
SITE = os.environ.get("PALACE_SITE", "https://usa.palaceskateboards.com").rstrip("/")
CHECKOUT_HOST = os.environ.get("PALACE_CHECKOUT", "https://checkout.usa.palaceskateboards.com").rstrip("/")
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
HONEST_UA = "shopify-scripting/1.0 (+https://github.com/DaanveerH/shopify-scripting)"
HEADERS = {}


def set_identity(user_agent="browser"):
    """Choose how requests introduce themselves to the shop (--user-agent).

    "browser"  the original behaviour: a Chrome User-Agent and the headers a browser's
               own fetch() sends. A shop can still tell this is not Chrome, because
               everything below the headers (TLS, HTTP/2) is Python's.
    "honest"   says what this is: the project name and link, and no browser-only headers.
    anything else is sent as the User-Agent as written.
    """
    HEADERS.clear()
    if user_agent == "browser":
        HEADERS.update({"User-Agent": BROWSER_UA, "Accept": "*/*", "Sec-Fetch-Dest": "empty",
                        "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"})
    else:
        HEADERS.update({"User-Agent": HONEST_UA if user_agent == "honest" else user_agent, "Accept": "*/*"})
    if "PALACE_SITE" not in os.environ:
        # The US host redirects visitors by location unless the request asks for US English.
        # Other regions geo-redirect on this header, so runs against them leave it off.
        HEADERS["Accept-Language"] = "en-US,en;q=0.9"


set_identity()
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "monitor.log")
EVENTS = os.path.join(HERE, "events.jsonl")

SIZE_ALIASES = {"XS": "X-Small", "S": "Small", "M": "Medium", "L": "Large",
                "XL": "X-Large", "XXL": "2X-Large", "2XL": "2X-Large", "3XL": "3X-Large"}
VARIANT_PREFIX = "gid://shopify/ProductVariant/"


class Closed(Exception):
    """The site answered with a redirect (its /password "shop closed" page) instead of data."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


# ---------------------------------------------------------------- output

def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    if LOG:
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d')} {line}\n")


def emit(event_type, **fields):
    """Append one event to events.jsonl. Connectors (Discord and others) read this file."""
    if not EVENTS:
        return
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": "palace", "type": event_type}
    record.update(fields)
    try:
        with open(EVENTS, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def notify(title, body):
    sys.stdout.write("\a")
    if sys.platform == "darwin":
        script = f'display notification {json.dumps(body)} with title {json.dumps(title)} sound name "Glass"'
        subprocess.run(["osascript", "-e", script], capture_output=True)


def open_url(url, browser, args):
    if args.dry_run:
        return
    if browser and browser.lower() != "default" and sys.platform == "darwin":
        if subprocess.run(["open", "-a", browser, url], capture_output=True).returncode == 0:
            return
        log(f"could not open {browser!r}, falling back to the default browser")
    import webbrowser
    webbrowser.open(url)


# ---------------------------------------------------------------- the shop

def decode_route_data(text):
    """Decode a React Router single-fetch payload (flat, index-referenced JSON)."""
    flat = json.loads(text.split("\n", 1)[0])
    cache = {}

    def hyd(i):
        if isinstance(i, int) and i < 0:
            return None
        if i in cache:
            return cache[i]
        v = flat[i]
        if isinstance(v, dict):
            out = cache[i] = {}
            for k, vi in v.items():
                out[flat[int(k[1:])]] = hyd(vi)
            return out
        if isinstance(v, list):
            out = cache[i] = []
            out.extend(hyd(x) if isinstance(x, int) else x for x in v)
            return out
        cache[i] = v
        return v

    return hyd(0)


def site_get(path, opener=None, timeout=6):
    req = urllib.request.Request(SITE + path, headers=HEADERS)
    do_open = opener.open if opener else urllib.request.urlopen
    with do_open(req, timeout=timeout) as r:
        data = decode_route_data(r.read().decode())
    if isinstance(data, list) and data and data[0] == "SingleFetchRedirect":
        target = data[1].get("redirect") if len(data) > 1 and isinstance(data[1], dict) else "?"
        raise Closed(str(target))
    return data


def site_feed(collection):
    """Every product on one collection page, as plain dicts."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            if "variants" in o and "title" in o and "handle" in o:
                nodes = [{"id": v["id"], "availableForSale": v["availableForSale"],
                          "title": v["selectedOptions"][0]["value"]} for v in o["variants"]["nodes"]]
                found.append({"id": o["id"], "handle": o["handle"], "title": o["title"], "variants": nodes})
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(site_get(f"/collections/{collection}.data"))
    return found


def checkout_locked():
    """True while Palace's pre-drop lock is on."""
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(CHECKOUT_HOST + "/password", headers=HEADERS), timeout=5) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return not (300 <= e.code < 400)
    except Exception:
        return True


class CartSession:
    """One cart on the shop: one cookie jar, any number of items."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        cookies = urllib.request.HTTPCookieProcessor(self.jar)
        self._post = urllib.request.build_opener(cookies, NoRedirect)
        self._get = urllib.request.build_opener(cookies)

    def add(self, variant_id, handle):
        """Send the request the Add to Cart button sends, for one unit."""
        body = urllib.parse.urlencode({"intent": "add", "merchandiseId": variant_id, "quantity": "1"}).encode()
        req = urllib.request.Request(SITE + "/api/cart", data=body, headers=dict(
            HEADERS, **{"Content-Type": "application/x-www-form-urlencoded", "Origin": SITE,
                        "Referer": f"{SITE}/products/{handle}"}))
        try:
            self._post.open(req, timeout=8).read()
        except urllib.error.HTTPError as e:
            if not 300 <= e.code < 400:  # the route answers 303 back to the product page on success
                raise
        if not any(c.name == "cart" for c in self.jar):
            raise RuntimeError("no cart cookie came back")

    def read(self):
        """The cart as the shop sees it, or {} if there is none."""
        return (site_get("/cart.data", self._get).get("root", {}).get("data") or {}).get("cart") or {}


def variant_ids_in(obj):
    """Every product-variant ID mentioned anywhere inside a cart payload."""
    ids = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o.startswith(VARIANT_PREFIX):
            ids.add(o)

    walk(obj)
    return ids


# ---------------------------------------------------------------- matching

def words(text):
    """'DR PALACE T-SHIRT Grey Marl' -> ['dr', 'palace', 't', 'shirt', 'grey', 'marl']"""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", text)


def find_product(item, products):
    """The product whose title holds every word of the item. Returns (product, how_many_matched).

    Whole words only, so 'tech' does not match 'polartec'. If several products match,
    the one with the fewest extra words in its title wins (an exact title always wins).
    """
    want, avoid = set(item["words"]), set(item["exclude"])
    hits = []
    for p in products:
        have = words(p["title"])
        if want <= set(have) and not (avoid & set(have)):
            hits.append((len(have) - len(item["words"]), p["title"], p))
    if not hits:
        return None, 0
    hits.sort(key=lambda h: h[:2])
    return hits[0][2], len(hits)


def pick(product, sizes):
    """The first in-stock variant in the person's size order. None if nothing fits."""
    vs = product["variants"]
    if len(vs) == 1:  # one-size item
        return vs[0] if vs[0]["availableForSale"] else None
    by_size = {v["title"].lower(): v for v in vs}
    for s in sizes:
        v = by_size.get(s.lower())
        if v and v["availableForSale"]:
            return v
    return None


def stock_line(product):
    if len(product["variants"]) == 1:
        return "one size=" + ("in" if product["variants"][0]["availableForSale"] else "out")
    return ", ".join(f"{v['title']}={'in' if v['availableForSale'] else 'out'}" for v in product["variants"])


# ---------------------------------------------------------------- the plan

def as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    return [str(x).strip() for x in value if str(x).strip()]


def make_item(spec, where):
    if isinstance(spec, str):
        spec = {"title": spec}
    title = (spec.get("title") or "").strip()
    if not words(title):
        sys.exit(f"{where}: every item needs a \"title\" with the product name")
    sizes = as_list(spec.get("sizes", spec.get("size")))
    return {"title": title, "words": words(title), "exclude": words(" ".join(as_list(spec.get("exclude")))),
            "sizes": [SIZE_ALIASES.get(s.upper(), s) for s in sizes],
            "product": None, "variant": None, "status": "waiting", "hinted": False, "skip_logged": False}


def load_plan(args):
    """Turn --carts FILE, or the single-item flags, into one plan the loop can run."""
    if args.carts:
        try:
            with open(args.carts) as f:
                raw = json.load(f)
        except OSError as e:
            sys.exit(f"cannot read {args.carts}: {e.strerror}")
        except json.JSONDecodeError as e:
            sys.exit(f"{args.carts} is not valid JSON (line {e.lineno}): {e.msg}")
        if not isinstance(raw, dict) or not raw.get("carts"):
            sys.exit(f"{args.carts}: expected an object with a \"carts\" list")
        carts = []
        for n, c in enumerate(raw["carts"], 1):
            name = c.get("name") or f"Cart {n}"
            items = [make_item(i, f"{args.carts}, {name}") for i in c.get("items", [])]
            if not items:
                sys.exit(f"{args.carts}: {name} has no items")
            carts.append({"name": name, "browser": c.get("browser"), "items": items})
        seen = {}
        for c in carts:
            for it in c["items"]:
                key = frozenset(it["words"])
                if key in seen:
                    sys.exit(f"{args.carts}: \"{it['title']}\" is listed twice ({seen[key]} and {c['name']}). "
                             "One of each item per run.")
                seen[key] = c["name"]
        plan = {"carts": carts, "open_missing": bool(raw.get("open_missing", False)),
                "shop_pay": bool(args.shop_pay or raw.get("shop_pay", False))}
        for key, flag in (("drop_time", "drop"), ("collections", "collections"),
                          ("wait_seconds", "wait"), ("browser", "browser")):
            if getattr(args, flag) is None and raw.get(key) is not None:
                setattr(args, flag, raw[key])
    else:
        if not args.match:
            sys.exit("say what to buy: --carts FILE, or --match WORDS for a single item")
        item = make_item({"title": " ".join(as_list(args.match)), "sizes": args.size, "exclude": args.exclude},
                         "--match")
        # A single item keeps the original behaviour: if it cannot be carted, open its page.
        plan = {"carts": [{"name": "Cart", "browser": None, "items": [item]}], "open_missing": True,
                "shop_pay": bool(args.shop_pay)}

    args.drop = args.drop or "11:00"
    args.collections = as_list(args.collections) or ["all"]
    args.wait = float(args.wait if args.wait is not None else 15)
    args.browser = args.browser or "Google Chrome"
    for c in plan["carts"]:
        c.update({"browser": c["browser"] or args.browser, "first_seen": None, "done": False,
                  "attempts": 0, "result": "nothing", "built": None})
    return plan


# ---------------------------------------------------------------- building and opening carts

def build_cart(ready):
    """Add every ready item to one new cart. Returns (checkout_url, total, items_in_cart)."""
    session = CartSession()
    sent = []
    for it in ready:
        error = None
        for _ in range(2):
            try:
                session.add(it["variant"]["id"], it["product"]["handle"])
                error = None
                break
            except Exception as e:
                error = e
                time.sleep(0.25)
        if error:
            it["status"] = "failed"
            log(f"  add to cart failed for {it['title']}: {error!r}")
        else:
            sent.append(it)
    if not sent:
        raise RuntimeError("every add-to-cart request failed")

    cart = session.read()
    quantity = cart.get("totalQuantity") or 0
    if not quantity or not cart.get("checkoutUrl"):
        raise RuntimeError("cart is empty after add (sold out or refused)")

    # The shop accepts an add for a sold-out size and then leaves it out of the cart,
    # so check what actually landed.
    ids = variant_ids_in(cart)
    inside = [it for it in sent if it["variant"]["id"] in ids] if ids else sent
    for it in sent:
        it["status"] = "added" if it in inside else "refused"
    if not ids and quantity < len(sent):
        log(f"  the cart holds {quantity} of {len(sent)} items and does not say which; check the checkout page")
    cost = (cart.get("cost") or {}).get("checkoutChargeAmount") or {}
    total = f"{cost.get('amount', '?')} {cost.get('currencyCode', '')}".strip()
    return cart["checkoutUrl"], total, inside


def with_shop_pay(url):
    """Add Shopify's payment=shop_pay hint, so checkout goes to Shop Pay without a redirect first."""
    return url + ("&" if "?" in url else "?") + "payment=shop_pay"


def describe(it):
    size = it["variant"]["title"] if it.get("variant") else ""
    title = it["product"]["title"] if it.get("product") else it["title"]
    return f"{title} / {size}" if size and size.lower() != "default title" else title


def product_url(it):
    return f"{SITE}/products/{it['product']['handle']}" if it.get("product") else None


def finish_cart(cart, plan, args):
    """Build this cart from whatever is buyable right now. open_built() opens it afterwards."""
    tag = f"[{cart['name']}]"
    ready = [it for it in cart["items"] if it["variant"]]
    for it in cart["items"]:
        if it["variant"] or it["skip_logged"]:
            continue
        it["skip_logged"] = True
        it["status"] = "sold_out" if it["product"] else "not_found"
        why = "your sizes are sold out" if it["product"] else "it never appeared in the shop"
        log(f"{tag} leaving out {it['title']}: {why}" + (f" ({product_url(it)})" if it["product"] else ""))
        emit("item_skipped", cart=cart["name"], title=it["title"], reason=it["status"], url=product_url(it))
        if it["product"] and plan["open_missing"]:
            open_url(product_url(it), cart["browser"], args)

    if not ready:
        cart["done"] = True
        log(f"{tag} nothing to check out")
        emit("cart_failed", cart=cart["name"], reason="nothing buyable")
        if not args.dry_run:
            notify(f"Palace: {cart['name']}", "Nothing buyable in your sizes")
        return

    names = [describe(it) for it in ready]
    if args.dry_run and not args.test_cart:
        cart["done"], cart["result"] = True, "dry run"
        log(f"{tag} DRY RUN would check out {len(ready)} item(s): " + "; ".join(names))
        return

    try:
        started = time.time()
        url, total, inside = build_cart(ready)
    except Exception as e:
        cart["attempts"] += 1
        log(f"{tag} cart failed (try {cart['attempts']} of 3): {e!r}")
        if cart["attempts"] >= 3:
            cart["done"] = True
            emit("cart_failed", cart=cart["name"], reason=str(e))
            log(f"{tag} giving up on the automatic cart; opening the product pages so you can add by hand")
            for it in ready:
                open_url(product_url(it), cart["browser"], args)
            if not args.dry_run:
                notify(f"Palace: {cart['name']}", "Cart failed - add to cart by hand")
        return

    for it in ready:
        if it["status"] != "added":
            log(f"{tag} not in the cart: {describe(it)} ({it['status']}) {product_url(it)}")
            emit("item_skipped", cart=cart["name"], title=it["title"], reason=it["status"], url=product_url(it))
    if plan["shop_pay"]:
        url = with_shop_pay(url)
    names = [describe(it) for it in inside]
    log(f"{tag} cart built in {time.time() - started:.2f}s with {len(inside)} item(s), "
        f"{total} before shipping and tax: " + "; ".join(names))
    emit("cart_built", cart=cart["name"], items=names, total=total, checkout_url=url)
    cart["built"] = {"url": url, "total": total, "names": names, "at": time.time(), "told": False}


def open_built(carts, args, patience=0.0):
    """Open each built cart once Palace's checkout is unlocked.

    Checks the lock now and then every half second for up to `patience` seconds, so a
    locked checkout never stops the other carts from being built in the meantime.
    """
    deadline = time.time() + patience
    while True:
        built = [c for c in carts if c["built"] and not c["done"]]
        if not built:
            return
        locked = checkout_locked()
        for cart in built:
            b, tag = cart["built"], f"[{cart['name']}]"
            gave_up = time.time() - b["at"] >= args.lock_wait
            if locked and not gave_up:
                if not b["told"]:
                    b["told"] = True
                    log(f"{tag} cart is ready but Palace's checkout is still locked; "
                        f"opening it the moment it unlocks (max {args.lock_wait:.0f}s)")
                continue
            cart["done"] = True
            if args.dry_run:
                cart["result"] = "dry run"
                log(f"{tag} DRY RUN cart ok, checkout {'still locked' if locked else 'open'}; not opening the browser")
                continue
            open_url(b["url"], cart["browser"], args)
            cart["result"] = "opened"
            log(f"{tag} CHECKOUT OPENED in {cart['browser']}: {len(b['names'])} item(s), {b['total']}"
                + (" (lock never lifted, opened anyway)" if locked else ""))
            emit("checkout_opened", cart=cart["name"], items=b["names"], total=b["total"], browser=cart["browser"])
            notify(f"Palace checkout open: {cart['name']}", f"{len(b['names'])} item(s), {b['total']} - review and pay")
        if time.time() >= deadline or all(c["done"] for c in built):
            return
        time.sleep(0.5)


# ---------------------------------------------------------------- main loop

def main():
    global LOG, EVENTS
    ap = argparse.ArgumentParser(description="Watch a Palace shop and open checkout when your items go on sale.")
    ap.add_argument("--carts", help="JSON file describing one or more carts (see carts.example.json)")
    ap.add_argument("--match", default="", help="single item: every word must be in the title, e.g. frolic,knit,black")
    ap.add_argument("--exclude", default="", help="single item: skip titles containing any of these words")
    ap.add_argument("--size", default="", help="single item: sizes, best first, e.g. L,XL (not needed for one-size items)")
    ap.add_argument("--collections", default=None, help="collection pages to read each poll, e.g. all,jackets (default all)")
    ap.add_argument("--interval", type=float, default=1.5, help="seconds between polls (minimum 1)")
    ap.add_argument("--drop", default=None, help="local drop time HH:MM (default 11:00); polls slowly until 3 min before it")
    ap.add_argument("--wait", type=float, default=None,
                    help="seconds to wait for a cart's other items after its first one appears (default 15)")
    ap.add_argument("--lock-wait", type=float, default=120, help="max seconds to hold a ready cart for the checkout unlock")
    ap.add_argument("--browser", default=None, help='macOS browser to open checkouts in (default "Google Chrome"; "default" = system default)')
    ap.add_argument("--shop-pay", action="store_true",
                    help="add payment=shop_pay to the checkout link (not yet tried on a live Palace shop)")
    ap.add_argument("--dry-run", action="store_true", help="never open the browser")
    ap.add_argument("--test-cart", action="store_true", help="with --dry-run: really build the carts, still open nothing")
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    ap.add_argument("--user-agent", default="browser",
                    help='how requests introduce themselves: "browser" (default), "honest", or your own text')
    ap.add_argument("--log", default=LOG, help="log file (default monitor.log next to this script)")
    ap.add_argument("--events", default=EVENTS, help="JSON-lines event file for connectors (default events.jsonl)")
    args = ap.parse_args()
    LOG, EVENTS = args.log, args.events
    set_identity(args.user_agent)
    plan = load_plan(args)
    carts = plan["carts"]
    args.interval = max(args.interval, 1.0)
    if args.once:
        args.wait = 0.0

    log(f"watching {SITE} every {args.interval}s" + (" (dry run)" if args.dry_run else ""))
    log(f"  identifying as: {HEADERS['User-Agent']}")
    for c in carts:
        log(f"  {c['name']} -> {c['browser']}")
        for it in c["items"]:
            log(f"    - {it['title']}" + (f"  [{', '.join(it['sizes'])}]" if it["sizes"] else "  [one size]"))
    emit("monitor_started", site=SITE, dry_run=args.dry_run,
         carts=[{"name": c["name"], "items": [it["title"] for it in c["items"]]} for c in carts])

    tick, delay, site_state, open_polls = 0, args.interval, None, 0
    hh, mm = (int(x) for x in args.drop.split(":"))
    drop_at = time.mktime(time.localtime()[:3] + (hh, mm, 0, 0, 0, -1))

    while True:
        tick += 1
        products, ok = {}, []
        for c in args.collections:
            try:
                for p in site_feed(c):
                    products.setdefault(p["id"], p)
                ok.append(c)
                state, delay = "OPEN", args.interval
            except Closed as e:
                state = f"closed (redirects to {e})"
            except urllib.error.HTTPError as e:
                state = f"HTTP {e.code}"
                if e.code in (429, 430, 503):
                    delay = min(delay * 2, 20)
            except Exception as e:
                state = f"error {e!r}"[:90]
            if c == args.collections[0] and state != site_state:
                log(f"site: {state}")
                emit("site_state", state=state)
                if site_state is not None and state == "OPEN":
                    notify("Palace site reopened", "watching for your items")
                site_state = state
        open_polls = open_polls + 1 if ok else 0

        for cart in carts:
            if cart["done"] or cart["built"]:
                continue
            for it in cart["items"]:
                p, how_many = find_product(it, products.values())
                if p:
                    if it["product"] is None:
                        log(f"LIVE: {p['title']} | {stock_line(p)} | {SITE}/products/{p['handle']}")
                        emit("product_live", cart=cart["name"], title=p["title"], stock=stock_line(p),
                             url=f"{SITE}/products/{p['handle']}")
                        if how_many > 1:
                            log(f"  note: {how_many} products match \"{it['title']}\"; using the closest title")
                    it["product"], it["variant"] = p, pick(p, it["sizes"])
                    cart["first_seen"] = cart["first_seen"] or time.time()
                elif products and open_polls >= 3 and not it["hinted"]:
                    it["hinted"] = True
                    titles = {" ".join(words(x["title"])): x["title"] for x in products.values()}
                    near = difflib.get_close_matches(" ".join(it["words"]), list(titles), n=3, cutoff=0.5)
                    log(f"not in the shop yet: \"{it['title']}\""
                        + (". Closest titles right now: " + "; ".join(titles[n] for n in near) if near else ""))
            everything_seen = all(it["product"] for it in cart["items"])
            if cart["first_seen"] and (everything_seen or time.time() - cart["first_seen"] >= args.wait):
                finish_cart(cart, plan, args)
                open_built(carts, args)  # open this one now; do not make it wait for the next cart's build
        open_built(carts, args)
        waiting = sum(not c["done"] for c in carts)

        if tick % 20 == 1:
            log(f"poll {tick}: feeds ok {ok}, {len(products)} products seen, {waiting} cart(s) still waiting")
        if not waiting:
            opened = sum(c["result"] == "opened" for c in carts)
            emit("monitor_done", carts_opened=opened)
            if opened:
                log(f"done. {opened} checkout(s) open. Review each order in the browser and press Pay yourself.")
            else:
                log("done.")
            return 0
        if args.once:
            return 0
        early = (site_state or "").startswith("closed") and time.time() < drop_at - 180
        pause = max(delay, 10) if early else delay
        if any(c["built"] and not c["done"] for c in carts):
            open_built(carts, args, patience=pause)  # spend the pause watching for the unlock
        else:
            time.sleep(pause)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
