# Plain-English FAQ

### Is this a bot?

It automates the clicking before checkout: finding the product, choosing your size, adding to cart. It stops at the checkout page. It does not pay, it does not get around captchas or queues, and it buys one of each item, the same as you would by hand.

### How does it find the item?

The store's own product list has an ID next to every size. The script finds your item by name, picks your size, and sends that ID to the cart. Here it is for Palace:

```python
# 1. the feed: same request the site makes when you click "New"
raw = GET("https://usa.palaceskateboards.com/collections/new.data")   # 30 a page; ?direction=next&cursor=... for more
products = decode(raw)   # React Router "single fetch": flat JSON array, objects reference each other by index

# 2. keyword match on title, then size -> variant
p = next(p for p in products if all(w in p["title"].lower() for w in ["frolic", "knit", "black"]))
v = next(v for v in p["variants"]["nodes"]
         if v["selectedOptions"][0]["value"] == "Large" and v["availableForSale"])
# v["id"] == "gid://shopify/ProductVariant/4xxxxxxxxxxxxx"

# 3. ATC: the exact form post the site's own button sends
POST("https://usa.palaceskateboards.com/api/cart",
     data={"intent": "add", "merchandiseId": v["id"], "quantity": 1})   # 303 + a `cart` cookie

# 4. checkout link comes back off the cart route
checkout = decode(GET("https://usa.palaceskateboards.com/cart.data"))["root"]["data"]["cart"]["checkoutUrl"]
```

That is simplified. The real thing is [`palace_monitor.py`](../palace/palace_monitor.py). Normal Shopify stores work the same way through `/products.json`.

### Will it guarantee I get the item?

No. It gets you to checkout quickly. Popular items can sell out in seconds, and stores can add queues or checks at checkout that only you can pass.

### Do I need to know how to code?

No. If you have a coding agent, open this folder in it and say what you want to buy. See [the agent section of the main README](../README.md#dont-want-to-do-this-yourself). If you do not, you need to be able to paste three commands into a terminal.

### What do I need installed?

Python 3.8 or newer. On a Mac, open Terminal and type `python3 --version`. If it prints a version number, you are set.

### Does it see my card or my password?

No. The scripts never ask for them and never read your browser's data. Payment details live in Shop Pay, in your browser. The script only tells your browser to open a link.

### What is Shop Pay, and do I need it?

Shop Pay is Shopify's saved-checkout service. If your browser is signed in to it, checkout opens with your address and card already filled in, and paying is one tap. Without it everything still works, but you type your details while other people are checking out.

### What is a "dry run"?

A practice run. With `--dry-run` the script watches and reports as usual but never opens your browser. Use it to check your setup before the real thing.

### What is the demo?

`python3 palace/demo.py` starts a pretend shop on your own computer and runs the real monitor against it. It is the quickest way to see what a drop looks like. It contacts no real store.

### Can I buy several things at once?

On Palace, yes: put several items in one cart, and use several carts if you want separate orders. See [the cart file](../palace/README.md#your-cart-file). Each item can be listed once.

### What happens if my size sells out?

List sizes in order of preference and the first one in stock is used. If none are in stock, that item is left out, the log tells you, and the rest of the cart still goes to checkout.

### Is this allowed?

That depends on the store. Some stores' terms do not allow automated access. Read the terms of the store you plan to use it on and decide for yourself. This project keeps to low request rates and one unit per item. By default its requests are labelled as a Chrome browser, which is how the scripts started out; run with `--user-agent honest` to have them say what they are instead. The [research notes](research-notes.md) explain why that is the direction this project is moving in.

### Does it work on Windows or Linux?

The scripts are plain Python and should run, but they have only been tested on macOS. On other systems they open your default browser and ring the terminal bell instead of showing a notification.

### Words you will see

| Word | Meaning |
|---|---|
| **Drop** | A limited release that goes on sale at a set time |
| **Monitor** | A script that keeps checking the store for you |
| **Poll** | One check of the store |
| **Cart link / checkout link** | A web address that opens a cart or checkout with items already in it |
| **Variant** | One buyable version of a product, usually one size |
| **Draw** | A lottery for the right to buy. Speed does not help. |
| **Headless store** | A Shopify store with a custom-built website on top, such as Palace |
| **Webhook** | A private address an app (such as Discord) gives you for posting messages into it |
| **Agent** | An AI tool that can read files and run commands for you |
