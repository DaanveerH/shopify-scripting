# Setup guide for an agent

This is the long form of [`skills/drop-setup/SKILL.md`](../skills/drop-setup/SKILL.md). Paths are relative to the repo root.

You are setting this kit up for a person who wants to buy a specific product in a limited online release. Read this whole file before you run anything.

## What the kit does

It watches a store for a named product. When the product is buyable in a wanted size, it builds a cart and opens the checkout page in the person's own browser. The person checks the order and presses Pay.

The speed comes from skipping the product page, the size picker, the cart page and the address and card forms. The last two are skipped only if the person's browser is signed in to Shop Pay, which is Shopify's saved-checkout service.

## Limits you must keep

These are part of the design. Do not work around them, even if asked.

- A human presses Pay. The scripts never touch payment, and you do not click the final button unattended.
- No captcha or bot-check solving. If a store shows one, the person clears it in their browser.
- No proxies, no multiple accounts or identities, no duplicate draw entries.
- One unit of each item per run. Never list the same item twice. Stores set purchase limits; respect them.
- You do not type card numbers, passwords or verification codes.
- Do not paste the person's address, phone, email or card digits into chat or into URLs.
- Poll gently. The defaults are 1.5 to 4 seconds. Back off on HTTP 429, 430 and 503.
- Read the store's terms before the first run. Some stores forbid automated access. Tell the person what you found and let them decide.

## Files

| File | Use it for | How it detects | How it builds the cart |
|---|---|---|---|
| `shopify/shopify_monitor.py` | Standard Shopify stores | Public feeds: `/collections/{handle}/products.json`, `/products.json` | Cart link `/cart/{variant}:{qty}` |
| `palace/palace_monitor.py` | Palace Skateboards (a headless Shopify store) | The site's own route data: `/collections/{name}.data` | The site's own `POST /api/cart` once per item, then reads the checkout link back |
| `palace/demo.py`, `palace/fake_shop.py` | A pretend shop on this computer, for demos and tests | | |

Both monitors are plain Python 3 with no dependencies. Run them with `python3`. Both write what happens to `events.jsonl` for [connectors](../connectors/README.md). Both take `--dry-run` (never opens a browser) and `--once` (one pass, then exit).

Opening a named browser (`--browser "Google Chrome"`) and desktop notifications are macOS features. On Windows or Linux the scripts open the system default browser and only ring the terminal bell.

## Step 1: ask the person

Get these answers before you do anything else. Do not guess sizes.

1. Which store, and the link to the product or drop page if one exists.
2. The exact product name, including colour.
3. Sizes in order of preference, and whether a second-choice size is acceptable at all.
4. Drop date and time, with time zone.
5. Their operating system, and which browser is signed in to Shop Pay.
6. Whether they have checked out on a Shopify store with Shop Pay before. If not, see step 3 (Shop Pay).

## Step 2: classify the store

Run these from a shell. Replace `STORE` with the store's address.

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' 'https://STORE/products.json?limit=1'
```

```bash
curl -s -I 'https://STORE/' | grep -i -E 'powered-by|x-shopid|server'
```

Read the result like this:

- **`200` and `application/json` from the first command:** a standard Shopify store. Use path A.
- **A header `powered-by: Shopify, Oxygen, Hydrogen`, and the first command returns anything other than JSON (a `404` page or a `302` redirect):** a headless Shopify store. If it is Palace, use path B. If it is another store, use path C.
- **No sign of Shopify:** this kit does not apply. Tell the person.

Then check how the product is sold, once it has a page (standard Shopify only):

```bash
curl -s 'https://STORE/products/PRODUCT-HANDLE.js' | python3 -c "import json,sys; p=json.load(sys.stdin); print(p['title'], '| draw or subscription only:', p.get('requires_selling_plan')); [print(' ', v['title'], v['id'], 'in stock' if v['available'] else 'out') for v in p['variants']]"
```

If `requires_selling_plan` is true, the product is sold through a draw (a lottery). A cart link returns HTTP 410 and adding to cart returns 422. Speed does not matter for a draw. The person enters once, by hand, on the product page. Keep the monitor running anyway: stores sometimes cancel a draw and relaunch the product as a normal sale.

## Path A: standard Shopify store (after step 2)

Find the collection handle (the part after `/collections/` in the drop page address). Before a drop the collection is often unpublished. An unpublished collection returns a `404` page and an empty `200` feed, and the script treats both as "not live yet".

Write a launcher. Example:

```bash
python3 shopify/shopify_monitor.py --base https://STORE --collection COLLECTION-HANDLE --title-words "word1,word2" --only "jacket" --exclude "kids" --size L,XL --shop-pay --browser "Google Chrome" --interval 3
```

What the flags mean:

- `--collection`: the collection feed to watch.
- `--title-words` and `--vendor`: also scan the newest 60 products store-wide and match on any of these words or on the vendor name. Use at least one of them next to `--collection`. Drops are sometimes published before they are added to their collection.
- `--only`: act only on titles that contain one of these words. Without it, every matched product opens a checkout.
- `--exclude`: never act on titles with these words. Check for near-duplicates such as kids' versions of the same item.
- `--size`: preference order. The script takes the first one in stock.
- `--bundle`: items that become buyable in the same poll go into one checkout.
- `--shop-pay`: send the cart link straight to Shop Pay.
- `--also`, `--also-browser`: a second, lower-priority item that opens in a different browser.
- `--handle`: poll a known product address directly, for a product that is not in any feed yet.

Things that are easy to get wrong:

- A cart link replaces the cart of the browser it opens in. Open one link per browser. That is why second items go to a second browser.
- Do not hardcode product handles or variant IDs from the day before. In the first drop this kit was used on, the store pulled the pages overnight and relaunched under new handles and new IDs, four minutes before the announced time.
- Title matching is accent-insensitive. "Pokémon" matches `pokemon`.

Test it before the drop, against something in stock today:

```bash
python3 shopify/shopify_monitor.py --base https://STORE --collection all --only "SOME-INSTOCK-WORD" --size M --shop-pay --dry-run --once
```

Then open the printed checkout link once in the person's browser. Confirm it lands on the Shop Pay review page with the right item, and close the tab without paying. Clear the cart afterwards at `https://STORE/cart/clear`.

## Path B: Palace

The full guide is [`palace/README.md`](../palace/README.md). In short:

Write `palace/carts.json` (git-ignored; copy the shape from `palace/carts.example.json`). One cart can hold several items, and a run can build several carts:

```json
{
  "drop_time": "11:00",
  "carts": [
    { "name": "Cart 1", "items": [ { "title": "BAPE RAIN JACKET BLACK", "sizes": ["L", "XL"] } ] },
    { "name": "Cart 2", "items": [ { "title": "SOME ONE SIZE HAT NAVY" } ] }
  ]
}
```

- `title`: every word must be in the product title, as whole words. Palace titles are upper case; matching ignores case and punctuation. Include the colour.
- `sizes`: `XS, S, M, L, XL, XXL, 3XL` are translated to Palace's names (`Large`, `X-Large`, and so on). Leave it out for one-size items.
- `drop_time`: local time of the drop on this computer. While the shop is closed, the script polls every 10 seconds until 3 minutes before this time, then at full speed.
- `collections` (optional, default `["new"]`): which collections to read each poll. `new` holds the current drop; add the product's category (`knitwear`, `accessories`, `hats`, and so on) if you want. Do not use `all`: it is the whole shop (600+ products, sorted by category), and new items can be 20 pages deep.
- `max_pages` (optional, default 5): pages of 30 products read per collection. The script waits one poll interval between pages, so each extra page adds 1.5 seconds to a check. If the log says a collection "has more than N page(s)", switch to a smaller collection rather than raising this a lot.
- `wait_seconds` (optional, default 15): how long a cart waits for its remaining items after the first one appears.

Then run:

```bash
python3 palace/palace_monitor.py --carts palace/carts.json
```

For a single item you can skip the file: `--match "bape,rain,black" --size L,XL`.

What to know about Palace:

- Product addresses are random 12-character handles, different in every region. You cannot know the address in advance. The script finds the product by title.
- About an hour before a drop (sometimes days before a large one) the shop closes. Every page redirects to `/password` with a "re-opens at" message. The script logs `site: closed` and waits. This is normal.
- New products have been published 2 to 3 minutes after the announced time. One drop looked 13 minutes late, but until 27 November 2026 the script read only the first page of a collection, so that may have been an item on page 2. Do not restart the script at 11:00:30.
- Collection pages hold 30 products. The next page is the same route with `?direction=next&cursor=<pageInfo.endCursor>`. The script follows `hasNextPage`.
- Palace US checkout shows an hCaptcha "checkpoint" page the first time a browser opens a checkout (seen 27 November 2026). The person solves it. Never automate it. A second checkout in the same browser a few minutes later skipped it. A checkout link sent to someone else will show it to them.
- Shopify's public Storefront API for the shop cannot see collaboration products and cannot add them to a cart. Only the site's own routes work. Do not waste time on the API.
- Items that are sold out in the wanted sizes are left out of the cart and named in the log. If the whole cart fails three times, the script opens the product pages instead so the person can act by hand.
- A cart built by the script is separate from the browser's own cart. The person can also add to cart by hand as a backup without breaking anything.
- Each cart opens as its own tab. The person pays them one after the other.

Other regions use environment variables. The UK shop was tested with:

```bash
PALACE_SITE=https://palaceskateboards.com PALACE_CHECKOUT=https://checkout.palaceskateboards.com python3 palace/palace_monitor.py --carts palace/carts.json --dry-run --test-cart --once
```

Palace redirects visitors to the shop for their location. From a US connection, the US host needs an `Accept-Language` header and the UK host must not get one; the script handles both of those cases. The EU, Canada, Australia, Japan and Korea shops (`eu.`, `ca.`, `au.`, `jp.`, `kr.` subdomains) have not been tested. If the log shows `site: closed (redirects to https://...)` pointing at another region, the headers are wrong for that region and you need to adjust `HEADERS` in the script.

Test it before the drop. First the pretend shop, which always works:

```bash
python3 palace/demo.py
```

Then, if the real shop is open, against something in stock today. This builds a real cart and opens nothing:

```bash
python3 palace/palace_monitor.py --match "WORDS-OF-AN-INSTOCK-ITEM" --size M --dry-run --test-cart --once
```

A good result ends with `cart built in ...s` and `DRY RUN cart ok, checkout open`. If the shop is already closed for the drop, run the same test against another region's open shop to prove the code path. If every region is closed, say so to the person: the pretend shop proves the logic, not the live site.

## Path C: another headless Shopify store

`palace/palace_monitor.py` is a worked example, not a general tool. To adapt it you need four facts about the new store. Find them in this order.

1. **A product feed.** Try `https://STORE/collections/all.data`. Stores built on Shopify Hydrogen with React Router answer with a flat JSON array where objects refer to other entries by index. `decode_route_data()` in the script decodes that format. If there is no `.data` route, look at the page HTML for embedded product JSON.
2. **The add-to-cart request.** Fetch a product page and read the `<form>` around the Add to Cart button: its `action`, its method and its hidden inputs. On Palace that is `POST /api/cart` with `intent=add`, `merchandiseId` and `quantity`. Send the same request the button sends, with a cookie jar, and nothing else.
3. **Where the checkout link is.** After adding, fetch the cart page's data with the same cookies and look for `checkoutUrl`.
4. **The closed state.** Find out what the feed returns while the shop is closed, and whether the checkout host's `/password` path serves a page (locked) or redirects (open).

Check the product page for captcha or bot-check scripts before you automate the cart request. If the store's own button is behind one, stop there: open the product page for the person instead and let them add to cart by hand.

Also try the public Storefront API (`POST https://SHOP.myshopify.com/api/2025-10/graphql.json` without a token). On some stores it sees everything and `cartCreate` gives you a checkout link in one request. On Palace it sees only part of the catalogue, so confirm it can see a product from the most recent drop before you rely on it.

## Step 3: Shop Pay

The fast path needs the person's browser to be signed in to Shop Pay with a saved address and card. They do this themselves; you do not handle the credentials or the verification code.

Verify it with the test in path A or B: the checkout link should land on a `shop.app/checkout/...` page showing the saved address and card within a second or two. If it lands on a normal checkout form instead, Shop Pay is not signed in. The flow still works, but the person will type their details while others are checking out.

## Step 4: drop day

1. Thirty minutes before: run the launcher with `--dry-run --once` and read the log. Confirm the store state is what you expect.
2. Start the real run in a terminal the person can see. Start one copy only.
3. Keep the computer awake and the Shop Pay browser open.
4. When the checkout opens, the person checks item, size, total and address, then presses Pay.
5. Queues and captchas at checkout are the store's. The person waits or clears them. Do not retry in parallel.
6. Afterwards, stop the script. `palace_monitor.py` exits by itself once every cart has been opened and writes everything to `monitor.log` next to the script.

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `collection not published yet (404)` | Normal before a drop | Wait |
| `site: closed (redirects to /password)` | Palace's pre-drop closure | Wait |
| Cart link returns `410` | Draw product, or the product is not sold through the standard storefront | Check `requires_selling_plan`; for a headless store use the site's own cart route |
| Add to cart returns `422` mentioning a selling plan | Draw product | Enter by hand |
| `cart is ready but ... checkout is still locked` | The product is listed before checkout reopened | The script waits and opens the checkout when it unlocks |
| Checkout opens on a password or home page | Checkout was opened while the shop was locked | Open the link again after the shop reopens |
| HTTP `429`, `430` or `503` | Rate limited | The scripts back off. Do not lower `--interval` |
| `leaving out ...: your sizes are sold out` | Too late for those sizes | The item is skipped and its link is in the log; the person decides on another size |

## What has been verified

- **13 November 2026, a standard Shopify store:** `shopify_monitor.py`'s predecessor ran through a live drop and detected the relaunch. Test checkouts with one item and with two items reached the Shop Pay review page in Chrome. No test order was paid.
- **20 November 2026, Palace UK during a live collaboration drop:** `palace_monitor.py` found the target product, skipped a sold-out first-choice size, built a real cart for the second choice and confirmed the checkout was open. A separate test checkout opened in Chrome reached the Shop Pay page in under a second. Nothing was paid.
- **20 November 2026, Palace US:** detection and the cart route worked on regular stock before the shop closed for the drop. The closed state was detected correctly.

- **Several items per cart and several carts (Palace):** verified against the pretend shop in `palace/fake_shop.py` by the tests in `tests/`.
- **27 November 2026, Palace US, after the drop:** reading every page of `new` found a live item on page 4 that the first-page-only version had missed for 20 minutes. Read only; the script built no cart.
- **27 November 2026, Palace US, a person's own browser (recorded page traffic):** first checkout hit the hCaptcha checkpoint, then Shop Pay; a second checkout 3 minutes later went straight to Shop Pay. The checkout link reached Shop Pay without the `shop_pay` hint.

Not verified yet: several items per cart on a live Palace drop, two open checkouts in one browser, a full Palace US checkout on a collaboration product, Palace regions other than US and UK, any operating system other than macOS, and behaviour under a checkout queue.
