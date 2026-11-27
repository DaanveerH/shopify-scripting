# Research notes: what the bot scene teaches, and what this project leaves out

People who built commercial checkout bots, and people who study the systems that stop them, write openly about how both sides work. These notes summarise what we read, what we took from it, and what we decided not to build. They explain several design choices in this repo.

Sources read on 25 November 2026:

- **@blastbots** (veritas) on X. Researches browser fingerprinting and anti-bot systems, and writes the nullpt.rs blog. Mainly the thread that opens "Your stealth browser isn't stealthy" (19 November 2026).
- **@offline** (Lucas) on X. Runs Cybersole, a commercial checkout bot. Mainly the September 2026 posts looking back at Shopify checkout between 2018 and 2023.

Only part of each timeline was visible when we read them, so this is not a full survey.

## The short version

| What we read | What we did with it |
|---|---|
| Pretending to be a different browser makes you easier to spot, not harder | Added an honest identity option to both monitors. See [below](#1-do-not-pretend-to-be-something-you-are-not). |
| The only thing that reliably looks like a real person's browser is a real person's browser | Already the design: checkout always happens in your own browser. Now explained in the docs. |
| Stores close the fast paths that bots depend on, usually within months | Kept to the paths a store's own pages use, and wrote down which ones those are. |
| Commercial bots won by using thousands of accounts and by skipping captchas and checkpoints | Not built, and will not be. See [what we leave out](#what-we-leave-out). |

## What we took from it

### 1. Do not pretend to be something you are not

The thread's main point: a program that claims to be Chrome on a Mac has to fake far more than one header to be believed. Anti-bot systems compare hundreds of signals with each other, and a single mismatch (the example given is a browser that says it runs on one kind of processor while its arithmetic behaves like another) marks the visitor as an impossible device. That is worse than being an unusual one. The thread quotes Tor's approach as the alternative: do not lie about what you are; just be consistent.

This applied to us directly. Both monitors used to introduce themselves as Chrome on macOS while being a Python script. A store that looks below the headers can tell, so the label gained nothing and was not true.

**What changed:** both monitors take `--user-agent`.

| Value | What the store is told |
|---|---|
| `browser` (default for now) | A Chrome label, as before |
| `honest` | `shopify-scripting/1.0` with a link to this repo, and no browser-only headers |
| any other text | Sent as written |

**What we checked:**

| Check | Result |
|---|---|
| Shopify's own demo store, full monitor run with `--user-agent honest` | Served normally: product feed and product pages read, draws detected |
| Palace US while closed, product feed and checkout gate, honest against browser | Identical answers |
| The pretend shop, every request in a run | Tests confirm the honest label is on all of them and the browser-only headers are gone |
| Palace while **open**: product feed and add-to-cart with `--user-agent honest` | **Not checked.** Every region was closed when this was written. |

`browser` stays the default until the last row has been checked on a live shop. After that the default should become `honest`.

### 2. Your own browser is the part that matters

The same thread explains why rented "stealth" browsers in a data centre get caught: they are not what they say they are. The opposite also holds. Your everyday browser on your own computer, signed in to your own account, is exactly what it says it is.

That is why the monitors only *read* product data and *build a cart*, then hand over to your browser for everything that involves you: sign-in, address, payment, any captcha or queue. This project will not add a headless or remote browser.

### 3. Fast paths get closed

The @offline posts describe several years of one store platform closing each shortcut bots found: a checkout API with generous limits, then a payment route, then another. Each lasted until the platform noticed.

For this project: the monitors use the same requests the store's own pages make (the product feed, the add-to-cart button's request, the cart's checkout link). Those change when the site changes, not when someone decides to block a loophole. Where a path is store-specific, the guide says how to re-derive it ([agent-setup.md, Path C](agent-setup.md#path-c-another-headless-shopify-store)).

### 4. Publish your results, including the misses

One post argues bot makers should publish real success numbers. We are not a business, but the idea carries over: every guide here has a "what has been tested" section that lists what has **not** been tested as well.

## What we leave out

These came up repeatedly in what we read. They are how commercial bots win, and they are outside this project's [ground rules](../README.md#the-rules).

| Technique described | Why it is not here |
|---|---|
| Faking browser fingerprints, or patching a browser to look like another device | It is deception aimed at a store's security, and by the researchers' own account it is an arms race that the faker eventually loses |
| Solving or skipping captchas, checkpoints and queues | These are how a store decides who gets to buy. A person can pass them; this tool leaves them to the person. |
| Creating many accounts with made-up details to spread requests around rate limits | Fake identities, and a way round purchase limits |
| Submitting payment automatically | A human presses Pay. No exceptions. |
| Rotating proxies | Only useful for hiding volume this tool does not generate |
| Using private or undocumented admin routes | Not what a store's own pages do |

If you are looking for those, this is the wrong project.

## What a real Palace US checkout showed (27 November 2026)

A person recorded their browser's network traffic (a HAR file) while buying on Palace US just after a drop. The recording itself is not in this repo: it holds their cookies and order details. What it taught us:

| Seen | What we did |
|---|---|
| Collection data comes 30 products a page, with `pageInfo.hasNextPage` and an `endCursor`. The next page is the same route with `?direction=next&cursor=…`. The monitor read only page 1 and missed a live item for 20 minutes. | The monitor now follows the pages, one request per poll interval, up to `max_pages` (default 5), and watches `new` instead of `all` by default. |
| The checkout link (`/cart/c/<token>?key=…`) first redirected to `/checkpoint`, an hCaptcha page. The person solved it, then went on to Shop Pay. | Documented. The person solves it; nothing here will. |
| A second checkout in the same browser 3 minutes later skipped the checkpoint. | Documented, with the caveat that we saw it once. |
| The checkout link went to Shop Pay on its own, without `payment=shop_pay`. | The `shop_pay` option stays off by default; it may not be needed. |
| The site's own Add to Cart now posts JSON to `/api/cart`: `{"lines": [{"merchandiseId": "gid://shopify/ProductVariant/…", "quantity": 1}]}`, and gets `200` with the cart (including its checkout link) back. The monitor still sends the form post (`intent=add`). | Not changed: the form post still built a cart on Palace US on 27 November (one in-stock item, `--test-cart`, nothing opened or paid). If it ever stops working, the JSON body is the fallback. |

## Ideas for later that fit the rules

- **Make `honest` the default** once it has passed on a live Palace drop.
- **A "what the store sees" check:** print the exact headers a monitor sends, so anyone can confirm it is not pretending.
- **Slow down further when a store asks.** Honour `Retry-After` on rate-limit answers instead of a fixed back-off.
