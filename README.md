# QuietPass API examples

Send a phone number and choose the information you need: free number details, current network and live status, or linked messaging accounts. Use the answers in your forms, CRM, or automation workflows.

[API quickstart](https://quietpass.com/docs/) · [API reference](https://quietpass.com/docs/api/) · [Integrations](https://quietpass.com/integrations/) · [Pricing](https://quietpass.com/pricing/) · [Coverage](https://quietpass.com/coverage/)

## Choose a starter

| Tool | What you need | Download |
| --- | --- | --- |
| JavaScript | Node.js 20+; no packages | [JavaScript starter](javascript/quietpass.mjs) |
| Python | Python 3.10+; standard library | [Python starter](python/quietpass.py) |
| Postman | Postman with Vault support | [Postman collection](postman/quietpass.postman_collection.json) |
| n8n | An n8n instance | [API workflow](n8n/quietpass.n8n.json) |

JavaScript, Python, and Postman use the same [request JSON](request.json). The n8n workflow has equivalent fields in **Contact and limits** and imports inactive with paid checks off.

## Make your first lookup

Create a [QuietPass account](https://quietpass.com/signup.html) and an API key. Set `QUIETPASS_API_KEY` in your server environment.

In [request.json](request.json), set `phone` to the number you want to check. Use `defaultCountry` for a local number; international numbers beginning with `+` or `00` do not need it. For example, `07400 123456` with `defaultCountry: "GB"` is accepted.

The supplied request selects free number details:

```json
{
  "phone": "",
  "defaultCountry": "GB",
  "checks": ["basic_line_type"],
  "currency": "GBP",
  "maxSpend": "0.00"
}
```

Run either starter from this repository's root:

```sh
node javascript/quietpass.mjs request.json
```

```sh
python3 python/quietpass.py request.json
```

For Postman, import the collection, add your key to Vault as `quietpass-api-key`, set the collection's `request` variable to your request JSON, and send **Run lookup**.

## Add the checks you need

Select individual checks within either paid package, or combine both in the same request.

| Package | Check names | Price per number, per lookup |
| --- | --- | --- |
| Basic details | `basic_line_type` | Free |
| Phone services | `enhanced_line_type`, `current_carrier`, `mnp`, `live_status`, `sms` | 0.02 |
| Messaging apps | `whatsapp`, `telegram` | 0.03 |

Prices above are in your workspace currency: GBP, USD, or EUR. Each selected paid package is charged once when at least one requested check gives a definite answer, including a negative. A package with only unavailable or inconclusive answers costs zero. [Billing details](https://quietpass.com/pricing/#charging).

For example, change `checks` to `["current_carrier", "whatsapp"]` and `maxSpend` to `"0.05"` to allow both packages. Use your workspace's currency in `currency`. The lookup returns the actual charge in `billing.amount` and `billing.currency`.

**Quotes are optional.** To review a quote first, run either starter with `request.json --quote`. Run it again without `--quote` to execute that saved quote. In Postman, open **Optional quote-based examples**.

## Read a result again

The scripts save a reference beside the request file as `request.json.quietpass-operation.json`. Rerun the same command to read the original lookup before submitting anything again. To deliberately check again after the original lookup has settled or expired, add `--new-lookup`.

In Postman, use **Read original result**. To deliberately start another lookup after settlement or expiry, set `start_new_lookup` to `true` before sending **Run lookup**.

Saved results are available for 24 hours. Keep the original request and operation reference after a timeout; a missing response does not establish whether the lookup ran.

## Connect a platform

- [HubSpot setup](https://quietpass.com/integrations/hubspot/)
- [n8n verified node and HubSpot workflows](https://quietpass.com/integrations/n8n/)
- [Make setup and workflow downloads](https://quietpass.com/integrations/make/)
- [Zapier setup](https://quietpass.com/integrations/zapier/)
- [Clay setup](https://quietpass.com/integrations/clay/)
- [HighLevel setup](https://quietpass.com/integrations/highlevel/)

The n8n HTTP starter in this repository uses built-in nodes. The HubSpot workflows use the separate [verified QuietPass node](https://github.com/c9-ventures-ltd/n8n-nodes-quietpass).

## Help

[Contact QuietPass](https://quietpass.com/contact/) with the request reference and error code if you need help. Keep API keys and customer data out of public issues and shared exports.

These files match the starters published on quietpass.com. [Service terms](https://quietpass.com/terms/) apply to use of the API.
