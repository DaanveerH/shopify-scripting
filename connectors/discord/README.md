# discord connector

Posts a short message to a Discord channel when your script sees something. The shop opened. An item is live. A cart is built. Checkout is open.

It uses a **webhook**. A webhook is a private address that Discord gives you for posting in one channel. You do not need a bot account. You do not need to install anything.

## set it up

**1. Make a webhook.** In Discord: channel settings → **Integrations** → **Webhooks** → **New Webhook** → **Copy Webhook URL**.

**2. Put the address in your terminal.** Do not save it in a file.

```bash
export DISCORD_WEBHOOK_URL='paste-the-address-here'
```

**3. See what it would send.** This prints the messages. It sends nothing.

```bash
python3 discord_notify.py --events ../../palace/events.jsonl --from-start --once --dry-run
```

**4. Drop day.** Open a second terminal. Run this next to the script.

```bash
python3 discord_notify.py --events ../../palace/events.jsonl
```

It waits for new events and posts each one. Stop it with Ctrl-C.

## options

| Option | What it does |
|---|---|
| `--events FILE` | The script's `events.jsonl` |
| `--from-start` | Also send events that are already in the file |
| `--once` | Stop at the end of the file |
| `--dry-run` | Print the messages. Send nothing. |
| `--only checkout_opened,cart_failed` | Send only these event types |
| `--include-checkout-links` | Put checkout links in the messages |

> [!WARNING]
> Checkout links are left out by default. Anyone who can read the channel could open your cart with one. Only use `--include-checkout-links` in a channel that only you can read.

## what a message looks like

```text
Checkout is open - review and pay
Cart 1
• FROLIC KNIT BLACK / Large
• POLARTEC 200 RUGBY CREW ULTIMATE GREY / Large
Total before shipping and tax: 316.0 USD
```

## is it tested?

- Message layout and file reading: yes. Covered by the tests and by `--dry-run`.
- Posting to a real Discord webhook: not yet. If Discord rejects a message, the script prints the error code it got.
