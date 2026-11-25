# Notes for coding agents

This repo holds small scripts that watch an online store, build a cart and open checkout in a person's browser. A human always presses Pay.

## If you are asked to set up or run a drop

Follow [`skills/drop-setup/SKILL.md`](skills/drop-setup/SKILL.md). The long form, including how to classify an unknown store, is [`docs/agent-setup.md`](docs/agent-setup.md).

## Rules that are not negotiable

- Never press Pay, enter payment details, passwords or verification codes.
- Never add captcha solving, proxies, multiple identities, or more than one unit of an item.
- Never commit a person's `carts.json`, logs, event files, webhook addresses or any personal details. They are git-ignored; keep it that way.
- Keep polling intervals at or above the current minimums, and keep the back-off on HTTP 429, 430 and 503.

## If you are asked to change the code

- Python 3.8+, standard library only. Do not add dependencies.
- Each monitor is a single file that runs on its own. Keep it that way.
- Run the tests before you finish: `python3 -m unittest discover -s tests`. They use the pretend shop in `palace/fake_shop.py` and never contact a real store.
- If you change what a monitor sends to a real store, say in your summary that it is untested against the live site until someone runs it there.
- Monitors report through `log()` and `emit()`. New event types go in the table in `connectors/README.md`.
- Docs are written for people who do not code. Use plain words, and put the command before the explanation.

## Layout

| Path | What |
|---|---|
| `palace/` | Palace monitor, cart file example, pretend shop, demo |
| `shopify/` | Standard Shopify monitor |
| `connectors/` | Event file format, Discord connector, connector template |
| `skills/drop-setup/` | The agent skill |
| `docs/` | Agent setup guide, FAQ, research notes (what is deliberately not built, and why) |
| `tests/` | `unittest` tests |
