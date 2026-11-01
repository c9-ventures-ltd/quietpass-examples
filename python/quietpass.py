"""Python 3.10+; standard library only. Run on a server, never in a browser."""
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ORIGIN = "https://quietpass.com"
CHECKS = ["basic_line_type", "enhanced_line_type", "current_carrier", "mnp", "live_status", "sms", "whatsapp", "telegram"]
UUID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Redirect refused; API credentials stay on QuietPass.")


def main(env=None, args=None, output=print):
    env = os.environ if env is None else env
    args = sys.argv[1:] if args is None else args
    if any(arg not in ["--free", "--execute", "--new-lookup"] for arg in args):
        raise RuntimeError("Use --free, --execute, or --new-lookup.")
    if "--free" in args and len(args) > 1:
        raise RuntimeError("Run --free separately from paid lookups.")
    if not env.get("QUIETPASS_API_KEY"):
        raise RuntimeError("Set QUIETPASS_API_KEY in your server environment.")
    opener = urllib.request.build_opener(NoRedirect())

    def api(path, body=None, key=None):
        # Identify the application instead of sending urllib's library default.
        headers = {"Authorization": "Bearer " + env["QUIETPASS_API_KEY"], "User-Agent": "QuietPass-Python-Example/1.0"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key
        request = urllib.request.Request(ORIGIN + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with opener.open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            try:
                detail = json.load(error).get("error", {})
            except (ValueError, AttributeError):
                detail = {}
            code = detail.get("code", "HTTP_" + str(error.code)) if isinstance(detail, dict) else "HTTP_" + str(error.code)
            reference = detail.get("requestId") if isinstance(detail, dict) else None
            raise RuntimeError(code + (" (request " + reference + ")" if reference else "")) from None

    def number_input(free=False):
        if not env.get("QUIETPASS_PHONE", "").strip():
            raise RuntimeError("Set QUIETPASS_PHONE to a number you are authorized to query.")
        selected = ["basic_line_type"] if free else [c.strip() for c in env.get("QUIETPASS_CHECKS", ",".join(CHECKS)).split(",")]
        if len(set(selected)) != len(selected) or any(c not in CHECKS for c in selected):
            raise RuntimeError("QUIETPASS_CHECKS contains an unknown or repeated check.")
        value = {"phone": env["QUIETPASS_PHONE"], "checks": selected}
        if env.get("QUIETPASS_COUNTRY"):
            value["default_country"] = env["QUIETPASS_COUNTRY"]
        return value

    if "--free" in args:
        output(api("/v1/phone/check", number_input(True)))
        return
    currency = env.get("QUIETPASS_CURRENCY")
    raw_maximum = env.get("QUIETPASS_MAX_MICROS", "")
    if currency not in ["GBP", "USD", "EUR"] or not re.fullmatch(r"[0-9]{1,12}", raw_maximum) or int(raw_maximum) > 100000000000:
        raise RuntimeError("Set QUIETPASS_CURRENCY and QUIETPASS_MAX_MICROS. 50000 means 0.05 of that currency.")
    maximum = int(raw_maximum)
    path = Path(env.get("QUIETPASS_OPERATION_FILE", "./quietpass-operation.json"))
    try:
        operation = json.loads(path.read_text())
    except FileNotFoundError:
        operation = None
    if operation is not None:
        if not isinstance(operation, dict) or not UUID.fullmatch(str(operation.get("quoteId", ""))) or not UUID.fullmatch(str(operation.get("idempotencyKey", ""))) or operation.get("currency") != currency or type(operation.get("maxSpendMicros")) is not int or not 0 <= operation["maxSpendMicros"] <= maximum:
            raise RuntimeError("Saved operation is invalid or exceeds the configured currency/limit. Retain it for support.")
        status = api("/v1/phone/results/" + operation["quoteId"] + "?include_details=true")
        if status.get("state") not in ["settled", "expired", "pending", "not_started"]:
            raise RuntimeError("Unknown request state. Retain the original operation.")
        if "--new-lookup" in args:
            if status["state"] not in ["settled", "expired"]:
                raise RuntimeError("Original request is unresolved. Do not replace its quote or request key.")
            path.unlink()
            operation = None
        elif status["state"] != "not_started":
            output(status)
            return
    if operation is None:
        quoted = api("/v1/phone/quote", number_input())
        quote = quoted.get("quote", {})
        try:
            expiry = datetime.fromisoformat(quote["expiresAt"].replace("Z", "+00:00"))
            valid_expiry = expiry > datetime.now(timezone.utc)
        except (KeyError, ValueError, TypeError):
            valid_expiry = False
        if not UUID.fullmatch(str(quote.get("id", ""))) or quote.get("currency") != currency or type(quote.get("maxMicros")) is not int or not 0 <= quote["maxMicros"] <= maximum or not valid_expiry:
            raise RuntimeError("Review the quoted currency, price, or expiry. Nothing was executed.")
        operation = {"quoteId": quote["id"], "currency": currency, "maxSpendMicros": quote["maxMicros"], "idempotencyKey": str(uuid.uuid4())}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as saved:
            json.dump(operation, saved, indent=2)
        output({"quote": quote, "unavailableChecks": quoted.get("unavailableChecks", [])})
    output({"operation": operation, "instruction": "This saved operation takes precedence over changed phone/check settings. Keep this file for recovery."})
    if "--execute" not in args:
        output("Quote only. Run this script with --execute to submit this original request.")
        return
    try:
        output(api("/v1/phone/execute?include_details=true", {"quoteId": operation["quoteId"], "maxSpendMicros": operation["maxSpendMicros"]}, operation["idempotencyKey"]))
    except Exception:
        output("Execution may be unresolved. Run this same script again without --execute to read the original status. Never delete its saved reference while pending.")
        raise


if __name__ == "__main__":
    try:
        main(output=lambda value: print(json.dumps(value, indent=2) if isinstance(value, (dict, list)) else value))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
