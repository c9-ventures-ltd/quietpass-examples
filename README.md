# QuietPass API examples

Phone intelligence for CRM, product, and automation workflows. Start with free number formatting, then choose carrier information, available network status, or reported WhatsApp and Telegram registration.

[Developer quickstart](https://quietpass.com/docs/) · [Integrations and workflows](https://quietpass.com/integrations/) · [Pricing](https://quietpass.com/pricing/) · [Coverage](https://quietpass.com/coverage/)

These are the same starter files published on quietpass.com. They contain no API keys or customer data. JavaScript and Python start in quote-only mode. The Postman collection requires explicit live-execution permission, and the n8n HTTP starter imports inactive.

| Starter | Requirements | File |
| --- | --- | --- |
| JavaScript | Node.js 20+, no packages | [quietpass.mjs](javascript/quietpass.mjs) |
| Python | Python 3.10+, standard library | [quietpass.py](python/quietpass.py) |
| Postman | Postman with Vault support | [Collection](postman/quietpass.postman_collection.json) |
| n8n HTTP workflow | Compatible n8n instance | [Inactive workflow](n8n/quietpass.n8n.json) |

## First request

Create a [QuietPass account](https://quietpass.com/signup.html), complete account setup, activate credit, and create a server API key. Set `QUIETPASS_API_KEY` through your secret manager; never commit or paste it into a workflow or public issue.

```sh
export QUIETPASS_PHONE="YOUR_AUTHORIZED_PHONE_NUMBER"
export QUIETPASS_CURRENCY="GBP"
export QUIETPASS_MAX_MICROS="50000"
# For national input, also set QUIETPASS_COUNTRY, for example GB.
node javascript/quietpass.mjs --free
# Or:
python3 python/quietpass.py --free
```

International `+` and `00` input needs no default country. A free formatting result does not prove that a number is assigned, reachable, or owned by someone.

## Review before paid use

Run the script without `--free` to prepare a quote. Review the selected checks, price, and currency, then use `--execute` to submit the saved operation within the chosen maximum. `50000` is 0.05 in the workspace currency; each workspace has one fixed currency. See the [full setup instructions](https://quietpass.com/docs/#integration-kit).

The scripts save references in `quietpass-operation.json`. Preserve that file after a timeout or failure. Read the original status before starting another operation; retrying a CRM write does not require purchasing another lookup. Results are retained for 24 hours. Protect terminal output and execution history.

## Connect a platform

- [HubSpot direct connection](https://quietpass.com/integrations/hubspot/)
- [n8n verified node and HubSpot workflows](https://quietpass.com/integrations/n8n/)
- [Make app invitation and CRM/Sheets blueprints](https://quietpass.com/integrations/make/)
- [Zapier installation invitation](https://quietpass.com/integrations/zapier/)
- [Clay HTTP recipe](https://quietpass.com/integrations/clay/)
- [HighLevel workflow recipes](https://quietpass.com/integrations/highlevel/)

The HTTP starter here is separate from the [verified QuietPass n8n node](https://github.com/c9-ventures-ltd/n8n-nodes-quietpass). Invitation apps and manual recipes are described accurately in their guides; these links do not imply Marketplace approval.

## Support and maintenance

Use [hello@quietpass.com](mailto:hello@quietpass.com) for support. Include a request reference and the error code, never API keys, customer numbers, or complete results. Downloadable starters are learning examples; use durable application storage for production queues.

The source and release checks are maintained in QuietPass's application repository. This repository mirrors the published starter files. No supplier call is made merely by cloning or importing them. These examples are provided for copying and adaptation in integrations with the QuietPass API; service use remains subject to the [service terms](https://quietpass.com/terms/).
