"""Tests for the Palace monitor. They run against the local pretend shop, never a real one.

    python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PALACE = os.path.join(ROOT, "palace")
sys.path.insert(0, PALACE)
sys.path.insert(0, os.path.join(ROOT, "connectors", "discord"))

import discord_notify  # noqa: E402
import fake_shop  # noqa: E402
import palace_monitor as pm  # noqa: E402


def item(title, **kw):
    return pm.make_item(dict(title=title, **kw), "test")


class Matching(unittest.TestCase):
    PRODUCTS = [{"title": t, "handle": t, "id": t, "variants": []} for t in (
        "FROLIC NEIN CUFF BEANIE WHITE", "FROLIC NEIN CUFF BEANIE OFF WHITE",
        "POLARTEC 200 RUGBY CREW ULTIMATE GREY", "BASICALLY A TECH DECK BLACK")]

    def test_words_ignore_case_punctuation_and_accents(self):
        self.assertEqual(pm.words("DR Palace T-Shirt, Grey Marl"), ["dr", "palace", "t", "shirt", "grey", "marl"])
        self.assertEqual(pm.words("Pokémon"), ["pokemon"])

    def test_exact_title_beats_longer_title(self):
        p, n = pm.find_product(item("frolic nein cuff beanie white"), self.PRODUCTS)
        self.assertEqual((p["title"], n), ("FROLIC NEIN CUFF BEANIE WHITE", 2))

    def test_whole_words_only(self):
        self.assertIsNone(pm.find_product(item("tech rugby"), self.PRODUCTS)[0])  # 'tech' is not in 'polartec'

    def test_punctuation_in_the_wanted_title_is_ignored(self):
        p, _ = pm.find_product(item("POLARTEC 200 RUGBY CREW ULTIMATE -  GREY"), self.PRODUCTS)
        self.assertEqual(p["title"], "POLARTEC 200 RUGBY CREW ULTIMATE GREY")

    def test_exclude(self):
        p, _ = pm.find_product(item("beanie white", exclude=["off"]), self.PRODUCTS)
        self.assertEqual(p["title"], "FROLIC NEIN CUFF BEANIE WHITE")

    def test_size_order_and_aliases(self):
        product = {"variants": [{"title": "Large", "availableForSale": False, "id": 1},
                                {"title": "X-Large", "availableForSale": True, "id": 2}]}
        self.assertEqual(pm.pick(product, item("x", sizes=["L", "XL"])["sizes"])["id"], 2)
        self.assertIsNone(pm.pick(product, item("x", sizes=["L"])["sizes"]))


class ShopPayLink(unittest.TestCase):
    def test_hint_is_added_with_the_right_separator(self):
        self.assertEqual(pm.with_shop_pay("https://x/cart/c/abc?key=1"), "https://x/cart/c/abc?key=1&payment=shop_pay")
        self.assertEqual(pm.with_shop_pay("https://x/checkout/abc"), "https://x/checkout/abc?payment=shop_pay")


class RouteData(unittest.TestCase):
    def test_round_trip(self):
        data = {"a": [1, "two", None, {"b": True}], "c": {"d": "e"}}
        self.assertEqual(pm.decode_route_data(fake_shop.encode_route_data(data)), data)


class EndToEnd(unittest.TestCase):
    """The real monitor, as a separate program, against the pretend shop."""

    def run_monitor(self, closed_for, extra=(), locked_for=1):
        server, url, self.shop = fake_shop.start(closed_for=closed_for, locked_for=locked_for)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        out = tempfile.mkdtemp()
        events = os.path.join(out, "events.jsonl")
        cmd = [sys.executable, os.path.join(PALACE, "palace_monitor.py"), "--dry-run", "--test-cart",
               "--wait", "1", "--interval", "1", "--drop", "00:00",
               "--log", os.path.join(out, "monitor.log"), "--events", events, *extra]
        done = subprocess.run(cmd, env=dict(os.environ, PALACE_SITE=url, PALACE_CHECKOUT=url),
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        with open(events) as f:
            return [json.loads(line) for line in f], done.stdout

    def test_two_carts_from_a_file(self):
        events, out = self.run_monitor(2, ["--carts", os.path.join(PALACE, "carts.example.json")])
        built = {e["cart"]: e for e in events if e["type"] == "cart_built"}
        self.assertEqual(built["Cart 1"]["items"], ["FROLIC KNIT BLACK / Large",
                                                    "POLARTEC 200 RUGBY CREW ULTIMATE GREY / Large"])
        self.assertEqual(built["Cart 1"]["total"], "316.0 USD")
        # The tee's only wanted size is sold out in the pretend shop, so it is left out.
        self.assertEqual(built["Cart 2"]["items"], ["FROLIC NEIN CUFF BEANIE CHILL PINK",
                                                    "FROLIC NEIN CUFF BEANIE WHITE",
                                                    "BASICALLY A TECH DECK BLACK"])
        skipped = [e for e in events if e["type"] == "item_skipped"]
        self.assertEqual([(e["title"], e["reason"]) for e in skipped], [("DR PALACE T-SHIRT GREY MARL", "sold_out")])
        self.assertNotEqual(built["Cart 1"]["checkout_url"], built["Cart 2"]["checkout_url"])
        self.assertIn("site: closed", out)
        self.assertNotIn("CHECKOUT OPENED", out)  # dry run never opens a browser

    def test_single_item_flags_still_work(self):
        events, _ = self.run_monitor(0, ["--match", "frolic,knit,black", "--size", "S,M"])
        built = [e for e in events if e["type"] == "cart_built"]
        self.assertEqual(built[0]["items"], ["FROLIC KNIT BLACK / Medium"])  # Small is sold out


    def test_honest_identity_is_sent_on_every_request(self):
        events, out = self.run_monitor(0, ["--match", "tech,deck", "--user-agent", "honest"])
        self.assertTrue([e for e in events if e["type"] == "cart_built"])
        agents = {h.get("User-Agent") for h in self.shop.seen_headers}
        self.assertEqual(agents, {pm.HONEST_UA})
        self.assertFalse([h for h in self.shop.seen_headers if any(k.lower().startswith("sec-fetch") for k in h)])
        self.assertIn("identifying as: shopify-scripting/", out)

    def test_shop_pay_is_off_unless_asked_for(self):
        events, _ = self.run_monitor(0, ["--match", "tech,deck"])
        self.assertNotIn("shop_pay", [e for e in events if e["type"] == "cart_built"][0]["checkout_url"])
        events, _ = self.run_monitor(0, ["--match", "tech,deck", "--shop-pay"])
        self.assertTrue([e for e in events if e["type"] == "cart_built"][0]["checkout_url"].endswith("payment=shop_pay"))

    def test_first_cart_does_not_wait_for_the_second(self):
        _, out = self.run_monitor(0, ["--carts", os.path.join(PALACE, "carts.example.json")], locked_for=0)
        lines = out.splitlines()
        first_done = next(i for i, l in enumerate(lines) if "[Cart 1] DRY RUN cart ok" in l)
        second_built = next(i for i, l in enumerate(lines) if "[Cart 2] cart built" in l)
        self.assertLess(first_done, second_built)

    def test_default_identity_is_unchanged(self):
        self.run_monitor(0, ["--match", "tech,deck"])
        self.assertEqual({h.get("User-Agent") for h in self.shop.seen_headers}, {pm.BROWSER_UA})


class Discord(unittest.TestCase):
    def test_checkout_links_are_left_out_by_default(self):
        event = {"type": "cart_built", "cart": "Cart 1", "items": ["A / Large"], "checkout_url": "https://x/secret"}
        self.assertNotIn("secret", json.dumps(discord_notify.to_message(event)))
        self.assertIn("secret", json.dumps(discord_notify.to_message(event, include_checkout_links=True)))

    def test_unknown_events_are_skipped(self):
        self.assertIsNone(discord_notify.to_message({"type": "something_else"}))


if __name__ == "__main__":
    unittest.main()
