/** Pure row helpers, kept free of UI imports so they can be unit tested under Node. */

/**
 * The JSON transport delivers every column as a string. Normalise once at the boundary:
 * booleans and numbers become real values; identifier-like columns always stay strings
 * (an ABN or account number is digits, not a number).
 */
const KEEP_STRING =
  /(_id|_ids|_date|_ts|_at|name|label|number|_quoted|value|text|subject|sender|detail|criterion|source|source_url|summary|action|flag|week|code|codes|field|fields|checks|reasons|invoices|images|json|regime|state|status|channel|type|intent|manager|description|category|attachment_name|batch_id|as_of|gic_quarter|reason)$/;
const NUMERIC = /^-?\d+(\.\d+)?([eE][-+]?\d+)?$/;

export function normalizeRow(row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    if (value === 'true' || value === 'false') out[key] = value === 'true';
    else if (typeof value === 'string' && !KEEP_STRING.test(key) && NUMERIC.test(value)) out[key] = Number(value);
    else out[key] = value;
  }
  return out;
}

export function list(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value !== 'string' || !value) return [];
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}
