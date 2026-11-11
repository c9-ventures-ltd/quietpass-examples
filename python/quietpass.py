"""Python 3.10+; standard library only. Run on a server, never in a browser."""
import json
import hashlib
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ORIGIN = "https://quietpass.com"
CHECKS = ["basic_line_type", "enhanced_line_type", "current_carrier", "mnp", "live_status", "sms", "whatsapp", "telegram"]
UUID = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", re.I)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Redirect refused; API credentials stay on QuietPass.")


def amount_micros(value):
    text = format(Decimal(str(value)), "f") if type(value) in [int, float] else value
    if not isinstance(text, str) or not re.fullmatch(r"(0|[1-9][0-9]{0,11})(\.[0-9]{1,6})?", text):
        raise RuntimeError("maxSpend must be an amount such as 0.05.")
    whole, _, fraction = text.partition(".")
    micros = int(whole) * 1000000 + int(fraction.ljust(6, "0"))
    if micros > 100000000:
        raise RuntimeError("maxSpend exceeds the per-lookup limit.")
    return micros


def amount(value):
    return str(value // 1000000) + "." + str(value % 1000000).rjust(6, "0").rstrip("0").ljust(2, "0")


def request_input(value):
    allowed = {"phone", "defaultCountry", "default_country", "checks", "currency", "maxSpend", "maxSpendMicros"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise RuntimeError("Use phone, defaultCountry, checks, currency, and maxSpend in the request JSON.")
    if not isinstance(value.get("phone"), str) or not value["phone"].strip() or not isinstance(value.get("checks"), list) or any(not isinstance(c, str) or c not in CHECKS for c in value["checks"]) or len(set(value["checks"])) != len(value["checks"]):
        raise RuntimeError("Set phone and select supported checks in the request JSON.")
    country = value.get("defaultCountry", value.get("default_country"))
    if ("defaultCountry" in value or "default_country" in value) and (not isinstance(country, str) or not re.fullmatch(r"[A-Za-z]{2}", country)):
        raise RuntimeError("defaultCountry must be a two-letter country code.")
    if "defaultCountry" in value and "default_country" in value and str(value["defaultCountry"]).upper() != str(value["default_country"]).upper():
        raise RuntimeError("Conflicting country fields. Use defaultCountry.")
    if "currency" in value and value["currency"] not in ["GBP", "USD", "EUR"]:
        raise RuntimeError("currency must be GBP, USD, or EUR.")
    if "maxSpendMicros" in value and (type(value["maxSpendMicros"]) is not int or not 0 <= value["maxSpendMicros"] <= 100000000):
        raise RuntimeError("maxSpendMicros must be an integer from 0 to 100000000.")
    limit = amount_micros(value["maxSpend"]) if "maxSpend" in value else value.get("maxSpendMicros")
    if "maxSpend" in value and "maxSpendMicros" in value and limit != value["maxSpendMicros"]:
        raise RuntimeError("Conflicting spending limits. Use maxSpend.")
    return {"phone": value["phone"], **({"defaultCountry": country.upper()} if country is not None else {}), "checks": [c for c in CHECKS if c in value["checks"]], **({"currency": value["currency"]} if "currency" in value else {}), **({"maxSpend": amount(limit)} if limit is not None else {})}


def run_request_file(file, args, env, api, output):
    value = request_input(json.loads(Path(file).read_text()))
    if "--free" in args:
        value = {**value, "checks": ["basic_line_type"], "maxSpend": "0.00"}
    fingerprint = hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    path = Path(env.get("QUIETPASS_OPERATION_FILE", file + ".quietpass-operation.json"))
    try:
        operation = json.loads(path.read_text())
    except FileNotFoundError:
        operation = None
    if operation is not None:
        if not isinstance(operation, dict) or operation.get("kind") not in ["direct", "quote"] or not UUID.fullmatch(str(operation.get("idempotencyKey", ""))) or not re.fullmatch(r"[a-f0-9]{64}", str(operation.get("fingerprint", ""))) or operation["kind"] == "quote" and (not UUID.fullmatch(str(operation.get("quoteId", ""))) or type(operation.get("maxSpendMicros")) is not int or operation["maxSpendMicros"] < 0):
            raise RuntimeError("Invalid saved lookup. Keep the operation file for support.")
        try:
            status = api("/v1/phone/lookup?includeDetails=true" if operation["kind"] == "direct" else "/v1/phone/results/" + operation["quoteId"] + "?includeDetails=true", key=operation["idempotencyKey"])
        except Exception as error:
            if operation["kind"] == "direct" and getattr(error, "code", None) == "DIRECT_LOOKUP_NOT_FOUND":
                status = {"state": "not_started", "result": None}
            else:
                raise
        if status.get("state") not in ["not_started", "pending", "settled", "expired"]:
            raise RuntimeError("Unknown lookup state. Keep the operation file.")
        if "--new-lookup" in args:
            if status["state"] not in ["settled", "expired"]:
                raise RuntimeError("The original lookup is unresolved. Keep its Idempotency-Key.")
            path.unlink()
            operation = None
        else:
            if operation["fingerprint"] != fingerprint:
                raise RuntimeError("The request JSON changed. Recover the original lookup; use --new-lookup only after it is settled or expired.")
            if status["state"] != "not_started":
                output(status)
                return
    if operation is None:
        if "--quote" in args:
            phone = value
            quoted = api("/v1/phone/quote", phone)
            q = quoted.get("quote", {})
            try:
                valid_expiry = datetime.fromisoformat(q["expiresAt"].replace("Z", "+00:00")) > datetime.now(timezone.utc)
            except (KeyError, ValueError, TypeError):
                valid_expiry = False
            if not UUID.fullmatch(str(q.get("id", ""))) or q.get("currency") not in ["GBP", "USD", "EUR"] or type(q.get("maxMicros")) is not int or not 0 <= q["maxMicros"] <= 100000000 or "currency" in value and q["currency"] != value["currency"] or "maxSpend" in value and q["maxMicros"] > amount_micros(value["maxSpend"]) or not valid_expiry:
                raise RuntimeError("The quote does not match the currency or spending limit. Nothing was run.")
            operation = {"kind": "quote", "fingerprint": fingerprint, "idempotencyKey": str(uuid.uuid4()), "quoteId": q["id"], "maxSpendMicros": q["maxMicros"], "quote": q, "unavailableChecks": quoted.get("unavailableChecks", [])}
        else:
            operation = {"kind": "direct", "fingerprint": fingerprint, "idempotencyKey": str(uuid.uuid4())}
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as saved:
            json.dump(operation, saved, indent=2)
    if "--quote" in args:
        output({"quote": operation["quote"], "unavailableChecks": operation.get("unavailableChecks", [])} if operation["kind"] == "quote" else {"instruction": "The original direct lookup has no separate quote. Run the same command without --quote to recover it."})
        return
    try:
        output(api("/v1/phone/lookup?includeDetails=true" if operation["kind"] == "direct" else "/v1/phone/execute?includeDetails=true", value if operation["kind"] == "direct" else {"quoteId": operation["quoteId"], "maxSpend": amount(operation["maxSpendMicros"])}, operation["idempotencyKey"]))
    except Exception:
        output("Keep the request JSON and operation file. Run the same command to read the original status before retrying.")
        raise


def main(env=None, args=None, output=print):
    env = os.environ if env is None else env
    args = sys.argv[1:] if args is None else args
    files = [arg for arg in args if not arg.startswith("--")]
    if len(files) > 1 or any(arg.startswith("--") and arg not in ["--free", "--execute", "--quote", "--new-lookup"] for arg in args):
        raise RuntimeError("Use request.json, with optional --quote or --new-lookup.")
    if "--quote" in args and "--execute" in args:
        raise RuntimeError("Choose --quote or --execute.")
    request_file = files[0] if files else None
    args = [arg for arg in args if arg != request_file]
    if not request_file and "--free" in args and len(args) > 1:
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
            failure = RuntimeError(code + (" (request " + reference + ")" if reference else ""))
            failure.code = code
            raise failure from None

    if request_file:
        return run_request_file(request_file, args, env, api, output)
    if "--quote" in args:
        raise RuntimeError("Supply request.json to use --quote.")

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
