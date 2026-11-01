// Node.js 20+; no packages. Run only on a server, never in a browser.
import {readFile, writeFile, unlink} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const origin = 'https://quietpass.com';
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const checks = ['basic_line_type', 'enhanced_line_type', 'current_carrier', 'mnp', 'live_status', 'sms', 'whatsapp', 'telegram'];

export async function main({env = process.env, args = process.argv.slice(2), fetch = globalThis.fetch, log = console.log} = {}) {
  if (args.some(arg => !['--free', '--execute', '--new-lookup'].includes(arg))) throw Error('Use --free, --execute, or --new-lookup.');
  if (args.includes('--free') && args.length > 1) throw Error('Run --free separately from paid lookups.');
  if (!env.QUIETPASS_API_KEY) throw Error('Set QUIETPASS_API_KEY in your server environment.');
  async function api(path, body, key) {
    const response = await fetch(origin + path, {
      method: body ? 'POST' : 'GET', redirect: 'error', signal: AbortSignal.timeout(30000),
      headers: {Authorization: 'Bearer ' + env.QUIETPASS_API_KEY, ...(body ? {'Content-Type': 'application/json'} : {}), ...(key ? {'Idempotency-Key': key} : {})},
      ...(body ? {body: JSON.stringify(body)} : {}),
    });
    const value = await response.json().catch(() => null);
    if (!response.ok) {
      const code = value?.error?.code || 'HTTP_' + response.status;
      const reference = value?.error?.requestId || response.headers.get('X-Request-Id');
      throw Error(code + (reference ? ' (request ' + reference + ')' : ''));
    }
    if (!value || typeof value !== 'object') throw Error('Unexpected response; retain the original operation for recovery.');
    return value;
  }
  function input(free = false) {
    if (!env.QUIETPASS_PHONE?.trim()) throw Error('Set QUIETPASS_PHONE to a number you are authorized to query.');
    const selected = free ? ['basic_line_type'] : (env.QUIETPASS_CHECKS || checks.join(',')).split(',').map(v => v.trim());
    if (!selected.length || new Set(selected).size !== selected.length || selected.some(v => !checks.includes(v))) throw Error('QUIETPASS_CHECKS contains an unknown or repeated check.');
    return {phone: env.QUIETPASS_PHONE, ...(env.QUIETPASS_COUNTRY ? {default_country: env.QUIETPASS_COUNTRY} : {}), checks: selected};
  }
  if (args.includes('--free')) {log(await api('/v1/phone/check', input(true))); return;}

  const currency = env.QUIETPASS_CURRENCY;
  const maximum = Number(env.QUIETPASS_MAX_MICROS);
  if (!['GBP', 'USD', 'EUR'].includes(currency) || !env.QUIETPASS_MAX_MICROS || !Number.isSafeInteger(maximum) || maximum < 0 || maximum > 100000000000) throw Error('Set QUIETPASS_CURRENCY and QUIETPASS_MAX_MICROS. 50000 means 0.05 of that currency.');
  const path = env.QUIETPASS_OPERATION_FILE || './quietpass-operation.json';
  let operation;
  try {operation = JSON.parse(await readFile(path, 'utf8'));} catch (error) {if (error.code !== 'ENOENT') throw error;}
  if (operation) {
    if (!uuid.test(operation.quoteId) || !uuid.test(operation.idempotencyKey) || operation.currency !== currency || !Number.isSafeInteger(operation.maxSpendMicros) || operation.maxSpendMicros < 0 || operation.maxSpendMicros > maximum) throw Error('Saved operation is invalid or exceeds the configured currency/limit. Retain it for support.');
    const status = await api('/v1/phone/results/' + operation.quoteId + '?include_details=true');
    if (!['settled', 'expired', 'pending', 'not_started'].includes(status.state)) throw Error('Unknown request state. Retain the original operation.');
    if (args.includes('--new-lookup')) {
      if (!['settled', 'expired'].includes(status.state)) throw Error('Original request is unresolved. Do not replace its quote or request key.');
      await unlink(path); operation = undefined;
    } else if (status.state !== 'not_started') {log(status); return;}
  }
  if (!operation) {
    const quoted = await api('/v1/phone/quote', input());
    const quote = quoted.quote;
    if (!quote || !uuid.test(quote.id) || quote.currency !== currency || !Number.isSafeInteger(quote.maxMicros) || quote.maxMicros < 0 || quote.maxMicros > maximum || !Number.isFinite(Date.parse(quote.expiresAt)) || Date.parse(quote.expiresAt) <= Date.now()) throw Error('Review the quoted currency, price, or expiry. Nothing was executed.');
    operation = {quoteId: quote.id, currency, maxSpendMicros: quote.maxMicros, idempotencyKey: randomUUID()};
    // Exclusive creation prevents two concurrent runs from both starting a lookup.
    await writeFile(path, JSON.stringify(operation, null, 2), {flag: 'wx', mode: 0o600});
    log({quote, unavailableChecks: quoted.unavailableChecks});
  }
  log({operation, instruction: 'This saved operation takes precedence over changed phone/check settings. Keep this file for recovery.'});
  if (!args.includes('--execute')) {log('Quote only. Run this script with --execute to submit this original request.'); return;}
  try {
    log(await api('/v1/phone/execute?include_details=true', {quoteId: operation.quoteId, maxSpendMicros: operation.maxSpendMicros}, operation.idempotencyKey));
    // Keep the reference after success so accidentally running again cannot buy a new lookup.
  } catch (error) {
    log('Execution may be unresolved. Run this same script again without --execute to read the original status. Never delete its saved reference while pending.');
    throw error;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main().catch(error => {console.error(error.message); process.exitCode = 1;});
}
