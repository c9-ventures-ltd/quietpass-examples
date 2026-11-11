// Node.js 20+; no packages. Run only on a server, never in a browser.
import {readFile, writeFile, unlink} from 'node:fs/promises';
import {randomUUID,createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const origin = 'https://quietpass.com';
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const checks = ['basic_line_type', 'enhanced_line_type', 'current_carrier', 'mnp', 'live_status', 'sms', 'whatsapp', 'telegram'];

function amountMicros(value){
 const text=typeof value==='number'&&Number.isFinite(value)?String(value):value;
 if(typeof text!=='string'||!/^(0|[1-9][0-9]{0,11})(\.[0-9]{1,6})?$/.test(text))throw Error('maxSpend must be an amount such as 0.05.');
 const [whole,fraction='']=text.split('.'),micros=BigInt(whole)*1000000n+BigInt(fraction.padEnd(6,'0'));
 if(micros>100000000n)throw Error('maxSpend exceeds the per-lookup limit.');return Number(micros);
}
function amount(value){const n=BigInt(value);return (n/1000000n).toString()+'.'+(n%1000000n).toString().padStart(6,'0').replace(/0+$/,'').padEnd(2,'0');}
function requestInput(value){
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!['phone','defaultCountry','default_country','checks','currency','maxSpend','maxSpendMicros'].includes(k)))throw Error('Use phone, defaultCountry, checks, currency, and maxSpend in the request JSON.');
  if(typeof value.phone!=='string'||!value.phone.trim()||!Array.isArray(value.checks)||new Set(value.checks).size!==value.checks.length||value.checks.some(c=>!checks.includes(c)))throw Error('Set phone and select supported checks in the request JSON.');
  const country=Object.hasOwn(value,'defaultCountry')?value.defaultCountry:value.default_country;
  if(country!==undefined&&(typeof country!=='string'||!/^[A-Za-z]{2}$/.test(country)))throw Error('defaultCountry must be a two-letter country code.');
  if(value.defaultCountry!==undefined&&value.default_country!==undefined&&String(value.defaultCountry).toUpperCase()!==String(value.default_country).toUpperCase())throw Error('Conflicting country fields. Use defaultCountry.');
  if(value.currency!==undefined&&!['GBP','USD','EUR'].includes(value.currency))throw Error('currency must be GBP, USD, or EUR.');
  if(value.maxSpendMicros!==undefined&&(!Number.isSafeInteger(value.maxSpendMicros)||value.maxSpendMicros<0||value.maxSpendMicros>100000000))throw Error('maxSpendMicros must be an integer from 0 to 100000000.');
  const limit=value.maxSpend!==undefined?amountMicros(value.maxSpend):value.maxSpendMicros;
  if(value.maxSpend!==undefined&&value.maxSpendMicros!==undefined&&limit!==value.maxSpendMicros)throw Error('Conflicting spending limits. Use maxSpend.');
  return {phone:value.phone,...(country!==undefined?{defaultCountry:country.toUpperCase()}:{}),checks:checks.filter(c=>value.checks.includes(c)),...(value.currency!==undefined?{currency:value.currency}:{}),...(limit!==undefined?{maxSpend:amount(limit)}:{})};
}
async function runRequestFile(file,args,env,api,log){
  let input=requestInput(JSON.parse(await readFile(file,'utf8')));
  if(args.includes('--free'))input={...input,checks:['basic_line_type'],maxSpend:'0.00'};
  const fingerprint=createHash('sha256').update(JSON.stringify(input)).digest('hex');
  const path=env.QUIETPASS_OPERATION_FILE||file+'.quietpass-operation.json';
  let operation;
  try{operation=JSON.parse(await readFile(path,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}
  if(operation!==undefined){
    if(!operation||typeof operation!=='object'||!['direct','quote'].includes(operation.kind)||!uuid.test(operation.idempotencyKey)||!/^[a-f0-9]{64}$/.test(operation.fingerprint)||operation.kind==='quote'&&(!uuid.test(operation.quoteId)||!Number.isSafeInteger(operation.maxSpendMicros)||operation.maxSpendMicros<0))throw Error('Invalid saved lookup. Keep the operation file for support.');
    let status;
    try{status=await api(operation.kind==='direct'?'/v1/phone/lookup?includeDetails=true':'/v1/phone/results/'+operation.quoteId+'?includeDetails=true',undefined,operation.idempotencyKey);}
    catch(error){if(operation.kind==='direct'&&error.code==='DIRECT_LOOKUP_NOT_FOUND')status={state:'not_started',result:null};else throw error;}
    if(!['not_started','pending','settled','expired'].includes(status.state))throw Error('Unknown lookup state. Keep the operation file.');
    if(args.includes('--new-lookup')){
      if(!['settled','expired'].includes(status.state))throw Error('The original lookup is unresolved. Keep its Idempotency-Key.');
      await unlink(path);operation=undefined;
    }else{
      if(operation.fingerprint!==fingerprint)throw Error('The request JSON changed. Recover the original lookup; use --new-lookup only after it is settled or expired.');
      if(status.state!=='not_started'){log(status);return;}
    }
  }
  if(!operation){
    if(args.includes('--quote')){
      const {currency,maxSpend}=input;
      const quoted=await api('/v1/phone/quote',input),q=quoted.quote;
      if(!q||!uuid.test(q.id)||!['GBP','USD','EUR'].includes(q.currency)||!Number.isSafeInteger(q.maxMicros)||q.maxMicros<0||q.maxMicros>100000000||currency!==undefined&&q.currency!==currency||maxSpend!==undefined&&q.maxMicros>amountMicros(maxSpend)||!Number.isFinite(Date.parse(q.expiresAt))||Date.parse(q.expiresAt)<=Date.now())throw Error('The quote does not match the currency or spending limit. Nothing was run.');
      operation={kind:'quote',fingerprint,idempotencyKey:randomUUID(),quoteId:q.id,maxSpendMicros:q.maxMicros,quote:q,unavailableChecks:quoted.unavailableChecks};
    }else operation={kind:'direct',fingerprint,idempotencyKey:randomUUID()};
    // Persist identity before dispatch. The file contains no phone, key, or result.
    await writeFile(path,JSON.stringify(operation,null,2),{flag:'wx',mode:0o600});
  }
  if(args.includes('--quote')){log(operation.kind==='quote'?{quote:operation.quote,unavailableChecks:operation.unavailableChecks}: {instruction:'The original direct lookup has no separate quote. Run the same command without --quote to recover it.'});return;}
  try{log(await api(operation.kind==='direct'?'/v1/phone/lookup?includeDetails=true':'/v1/phone/execute?includeDetails=true',operation.kind==='direct'?input:{quoteId:operation.quoteId,maxSpend:amount(operation.maxSpendMicros)},operation.idempotencyKey));}
  catch(error){log('Keep the request JSON and operation file. Run the same command to read the original status before retrying.');throw error;}
}

export async function main({env = process.env, args = process.argv.slice(2), fetch = globalThis.fetch, log = console.log} = {}) {
  const files=args.filter(arg=>!arg.startsWith('--'));
  if(files.length>1||args.some(arg=>arg.startsWith('--')&&!['--free','--execute','--quote','--new-lookup'].includes(arg)))throw Error('Use request.json, with optional --quote or --new-lookup.');
  if(args.includes('--quote')&&args.includes('--execute'))throw Error('Choose --quote or --execute.');
  const requestFile=files[0];args=args.filter(arg=>arg!==requestFile);
  if (!requestFile && args.includes('--free') && args.length > 1) throw Error('Run --free separately from paid lookups.');
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
      throw Object.assign(Error(code + (reference ? ' (request ' + reference + ')' : '')), {code});
    }
    if (!value || typeof value !== 'object') throw Error('Unexpected response; retain the original operation for recovery.');
    return value;
  }
  if(requestFile)return runRequestFile(requestFile,args,env,api,log);
  if(args.includes('--quote'))throw Error('Supply request.json to use --quote.');
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
