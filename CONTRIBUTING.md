# Contributing

Thanks for looking. Small, focused changes are the easiest to review.

## Good first contributions

- **A connector.** Copy [`connectors/template/`](connectors/template/) and send events somewhere new. See [connectors/README.md](connectors/README.md).
- **Store notes.** Tried a monitor on a region or store that is not in a "tested" list? Open an issue with what worked and what did not.
- **Docs.** If a step confused you, it will confuse the next person. Fixes are welcome.

## Before you open a pull request

```bash
python3 -m unittest discover -s tests
```

- Python 3.8+, standard library only.
- Each monitor stays a single file that runs on its own.
- Say what you tested, and where. "Tested against the pretend shop only" is a fine answer; just say it.

## What will not be merged

Anything that pays for the user, solves or bypasses captchas, bot checks or queues, uses proxies or multiple identities, buys more than one unit of an item, or removes the request-rate limits. See the [ground rules](README.md#the-rules).

Never include real cart files, logs, checkout links, webhook addresses or personal details in an issue or pull request.
