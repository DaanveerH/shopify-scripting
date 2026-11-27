#!/usr/bin/env python3
"""A pretend Palace shop that runs on your own computer, for demos and tests.

It answers the same four routes the monitor uses, in the same data format:

  GET  /collections/<name>.data   product list, a few per page like the real shop's 30
                                  (?direction=next&cursor=N for the next page;
                                  a redirect to /password while "closed")
  POST /api/cart                  add one item to a cart, tracked by a `cart` cookie
  GET  /cart.data                 the cart, with its checkout link
  GET  /password                  200 while checkout is "locked", a redirect once open

Nothing here talks to the internet and nothing can be bought.

    python3 fake_shop.py --port 8765 --closed-for 5

Then point the monitor at it:

    PALACE_SITE=http://127.0.0.1:8765 PALACE_CHECKOUT=http://127.0.0.1:8765 \
        python3 palace_monitor.py --carts carts.example.json --dry-run --test-cart
"""
import argparse
import html
import json
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SIZES = ["Small", "Medium", "Large", "X-Large"]

# (title, price, sizes or None for one-size, sold-out sizes)
CATALOGUE = [
    ("FROLIC KNIT BLACK", 168, SIZES, ["Small"]),
    ("FROLIC KNIT NAVY", 168, SIZES, []),
    ("POLARTEC 200 RUGBY CREW ULTIMATE GREY", 148, SIZES, []),
    ("POLARTEC 200 RUGBY CREW BLACK", 148, SIZES, ["Large"]),
    ("DR PALACE T-SHIRT GREY MARL", 48, SIZES, ["Large"]),  # the wanted size is gone
    ("DR PALACE T-SHIRT WHITE", 48, SIZES, []),
    ("FROLIC NEIN CUFF BEANIE CHILL PINK", 42, None, []),
    ("FROLIC NEIN CUFF BEANIE WHITE", 42, None, []),
    ("FROLIC NEIN CUFF BEANIE OFF WHITE", 42, None, []),
    ("BASICALLY A TECH DECK BLACK", 12, None, []),
]


def build_products():
    products, n = [], 1000
    for i, (title, price, sizes, sold_out) in enumerate(CATALOGUE):
        variants = []
        for size in sizes or ["Default Title"]:
            n += 1
            variants.append({"id": f"gid://shopify/ProductVariant/{n}", "availableForSale": size not in sold_out,
                             "selectedOptions": [{"name": "Size", "value": size}]})
        products.append({"id": f"gid://shopify/Product/{i + 1}", "handle": f"demo{i + 1:08d}", "title": title,
                         "price": price, "variants": {"nodes": variants}})
    return products


def encode_route_data(obj):
    """The reverse of palace_monitor.decode_route_data: nested data -> flat, index-referenced JSON."""
    flat = []

    def put(value):
        if value is None:
            return -5
        index = len(flat)
        flat.append(None)
        if isinstance(value, dict):
            node = {}
            for key, inner in value.items():
                key_index = put(key)
                node[f"_{key_index}"] = put(inner)
            flat[index] = node
        elif isinstance(value, list):
            flat[index] = [put(inner) for inner in value]
        else:
            flat[index] = value
        return index

    put(obj)
    return json.dumps(flat)


class Shop:
    def __init__(self, closed_for=0.0, locked_for=0.0, page_size=4):
        self.started = time.time()
        self.closed_for = closed_for      # seconds the shop stays "closed" after start
        self.locked_for = locked_for      # extra seconds the checkout stays locked after opening
        self.page_size = page_size        # the real shop uses 30; a small page keeps paging in every test
        self.products = build_products()
        self.paths = []                   # the path of every request, for tests
        self.carts = {}
        self.lock = threading.Lock()
        self.seen_headers = []            # the headers of every request, for tests

    def closed(self):
        return time.time() - self.started < self.closed_for

    def checkout_locked(self):
        return time.time() - self.started < self.closed_for + self.locked_for

    def variant(self, variant_id):
        for p in self.products:
            for v in p["variants"]["nodes"]:
                if v["id"] == variant_id:
                    return p, v
        return None, None


def make_handler(shop, base_url):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, status, body, content_type="text/x-script", headers=None):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def cart_id(self):
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return cookie["cart"].value if "cart" in cookie else None

        def do_GET(self):
            shop.seen_headers.append(dict(self.headers))
            shop.paths.append(self.path)
            url = urllib.parse.urlparse(self.path)
            path, query = url.path, urllib.parse.parse_qs(url.query)
            if path == "/password":
                if shop.checkout_locked():
                    return self.send(200, "<h1>Web shop re-opens soon (demo)</h1>", "text/html")
                return self.send(302, "", headers={"Location": "/"})
            if path.startswith("/collections/") and path.endswith(".data"):
                if shop.closed():
                    return self.send(200, encode_route_data(["SingleFetchRedirect", {"redirect": "/password"}]))
                # Same shape as the real shop: edges of nodes, plus pageInfo with an opaque cursor.
                start = int((query.get("cursor") or ["0"])[0]) if query.get("direction") == ["next"] else 0
                end = start + shop.page_size
                page = {"edges": [{"node": p} for p in shop.products[start:end]],
                        "pageInfo": {"hasPreviousPage": start > 0, "hasNextPage": end < len(shop.products),
                                     "startCursor": str(start), "endCursor": str(end)}}
                return self.send(200, encode_route_data(
                    {"root": {"data": {"shop": "demo"}},
                     "routes/($locale).collections.$handle": {"data": {"collection": {"products": page}}}}))
            if path == "/cart.data":
                lines = shop.carts.get(self.cart_id(), [])
                cart = None
                if lines:
                    total = sum(shop.variant(v)[0]["price"] for v in lines)
                    cart = {"totalQuantity": len(lines), "checkoutUrl": f"{base_url}/checkout/{self.cart_id()}",
                            "cost": {"checkoutChargeAmount": {"amount": f"{total}.0", "currencyCode": "USD"}},
                            "lines": {"nodes": [{"quantity": 1, "merchandise": {"id": v}} for v in lines]}}
                return self.send(200, encode_route_data({"root": {"data": {"cart": cart}}}))
            if path.startswith("/checkout/"):
                rows = "".join(
                    f"<li>{html.escape(p['title'])} &middot; {html.escape(v['selectedOptions'][0]['value'])}"
                    f" &middot; ${p['price']}</li>"
                    for p, v in (shop.variant(i) for i in shop.carts.get(path.rsplit('/', 1)[1], [])))
                return self.send(200, "<body style='font:16px system-ui;max-width:520px;margin:60px auto'>"
                                      "<h1>Demo checkout</h1><p>This page is served from your own computer. "
                                      "Nothing is real and nothing can be bought.</p>"
                                      f"<ul>{rows}</ul><p>On a real drop, this is where you check the order "
                                      "and press Pay.</p></body>", "text/html")
            self.send(404, "not found", "text/plain")

        def do_POST(self):
            shop.seen_headers.append(dict(self.headers))
            shop.paths.append(self.path)
            if urllib.parse.urlparse(self.path).path != "/api/cart":
                return self.send(404, "not found", "text/plain")
            length = int(self.headers.get("Content-Length") or 0)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode())
            variant_id = (form.get("merchandiseId") or [""])[0]
            product, variant = shop.variant(variant_id)
            if shop.closed() or product is None:
                return self.send(404, "not found", "text/plain")
            with shop.lock:
                cart_id = self.cart_id() or f"demo{len(shop.carts) + 1}"
                lines = shop.carts.setdefault(cart_id, [])
                # Like the real shop: a sold-out size is accepted and then left out of the cart.
                if variant["availableForSale"] and variant_id not in lines:
                    lines.append(variant_id)
            self.send(303, "", headers={"Location": f"/products/{product['handle']}",
                                        "Set-Cookie": f"cart={cart_id}; Path=/"})

    return Handler


def start(port=0, closed_for=0.0, locked_for=0.0, page_size=4):
    """Start the shop on a background thread. Returns (server, base_url, shop)."""
    shop = Shop(closed_for, locked_for, page_size)
    server = ThreadingHTTPServer(("127.0.0.1", port), None)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    server.RequestHandlerClass = make_handler(shop, base_url)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, base_url, shop


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run a pretend Palace shop on this computer.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--closed-for", type=float, default=5, help="seconds the shop stays closed after start")
    ap.add_argument("--locked-for", type=float, default=2, help="extra seconds the checkout stays locked")
    a = ap.parse_args()
    _, url, _ = start(a.port, a.closed_for, a.locked_for)
    print(f"demo shop on {url}: closed for {a.closed_for:.0f}s, then open. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
