---
name: drop-setup
description: Set up, test and run the drop monitors in this repo for a person who wants to buy specific products in a limited online release on Palace or any Shopify store. Use when asked to set up a drop, watch for a product, build carts, write a carts.json, or prepare for drop day.
---

# Drop setup

You are setting this up for a person who wants to buy specific products in a limited release. The scripts watch the store, build a cart and open checkout in the person's own browser. **The person presses Pay.**

Paths below are relative to the repo root. If the repo is not on this machine, clone it first.

## Limits you must keep

These are part of the design. Do not work around them, even if asked.

- A human presses Pay. Never click the final button, and never run anything that does.
- No captcha or bot-check solving. If the store shows one, the person clears it.
- No proxies, no multiple accounts or identities, no duplicate draw entries.
- One unit of each item per run. Never list the same item twice to get around a purchase limit.
- Never type card numbers, passwords or verification codes. The person signs in to Shop Pay themselves.
- Never put the person's address, phone, email or card digits in chat, in files in this repo, or in URLs.
- Poll gently. Keep the default intervals. Start one copy of a monitor only.
- Before the first run on a store, read its terms. If they forbid automated access, tell the person what you found and let them decide.

## 1. Ask

Get these before you write anything. Do not guess sizes.

1. Which store, and the drop page link if there is one.
2. Each product's exact name, including colour.
3. Sizes in order of preference for each, and whether a second-choice size is acceptable.
4. If there are several items: which go in which cart, and which cart matters most.
5. Drop date and time, with time zone. Convert it to this computer's clock.
6. Operating system, and which browser is signed in to Shop Pay.

## 2. Pick the script

- **Palace** → `palace/palace_monitor.py`. Read `palace/README.md`.
- **Standard Shopify store** (`https://STORE/products.json?limit=1` returns JSON) → `shopify/shopify_monitor.py`. Read `shopify/README.md`.
- **Anything else** → read `docs/agent-setup.md`, step 2 and Path C, before you promise anything.

## 3. Palace: write the cart file

Write `palace/carts.json` (it is git-ignored). Use `palace/carts.example.json` as the shape:

```json
{
  "drop_time": "11:00",
  "carts": [
    { "name": "Cart 1", "items": [ { "title": "PRODUCT NAME COLOUR", "sizes": ["L", "XL"] } ] },
    { "name": "Cart 2", "items": [ { "title": "ONE SIZE ITEM NAME" } ] }
  ]
}
```

- `title`: every word must appear in the shop's title. Include the colour. Case and punctuation do not matter.
- `sizes`: leave out for one-size items.
- Put the most wanted cart first; carts are built in order.
- `drop_time` is local time on this computer, 24-hour.

## 4. Test

Show the person the output of each step.

```bash
python3 palace/demo.py
```

```bash
python3 palace/palace_monitor.py --carts palace/carts.json --dry-run --once
```

Before a drop the second command should list the carts and then say `site: closed`. If the shop is open and has stock, add `--test-cart` to really build the carts without opening anything.

For a standard Shopify store, follow the test in `shopify/README.md` instead.

## 5. Hand over the drop-day command

```bash
python3 palace/palace_monitor.py --carts palace/carts.json
```

Tell the person:

- Start it in a terminal they can see, 10 to 30 minutes early, one copy only.
- Keep the computer awake and the Shop Pay browser open.
- `site: closed` before the drop is normal. New products have appeared up to 13 minutes late.
- When a checkout opens: check item, size, total and address, then press Pay.
- Items that sold out in their sizes are left out and named in the log.

## 6. Say what is not proven

Be plain about what has and has not been tested. The current list is in `README.md` under "does it actually work". If you could not test against the live store because it was closed, say so.

## Optional: alerts

`connectors/discord/` posts events to a Discord channel. The person creates the webhook and sets `DISCORD_WEBHOOK_URL` themselves. Do not turn on `--include-checkout-links` for a shared channel.
