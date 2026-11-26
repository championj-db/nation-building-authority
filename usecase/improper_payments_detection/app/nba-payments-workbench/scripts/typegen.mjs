// Build-time type generation for an on-behalf-of-user app.
//
// Every query here is an .obo.sql file: at runtime it runs as the signed-in officer, so the app's
// service principal deliberately has no SELECT on the gold tables. The Databricks Apps build runs
// typegen as that service principal, gets INSUFFICIENT_PERMISSIONS, and AppKit treats that as a
// fatal SQL error. For this app it is environmental, so - only in that case, and only when the
// committed types exist - keep the committed types (the same fallback AppKit applies to 401/403)
// with a loud warning. Real SQL errors still fail the build. Locally, with access, this is a no-op
// wrapper around `appkit generate-types --wait`.
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';

const committed = ['shared/appkit-types/analytics.d.ts'];
// Call the project-local binary directly: build images do not always put npx on PATH.
const bin = path.join('node_modules', '.bin', process.platform === 'win32' ? 'appkit.cmd' : 'appkit');
const run = spawnSync(bin, ['generate-types', '--wait'], { encoding: 'utf8' });
if (run.error) {
  console.error(`[typegen] could not start ${bin}: ${run.error.message}`);
  process.exit(1);
}
process.stdout.write(run.stdout ?? '');
process.stderr.write(run.stderr ?? '');
if (run.status === 0) process.exit(0);

const output = `${run.stdout ?? ''}\n${run.stderr ?? ''}`;
// Per-query result lines look like "SQL ERR  <query_key>  <ERROR_CODE>"; ignore AppKit's hint lines.
// The build principal has no SELECT on the OBO-only gold tables, and the committed -- @param defaults
// are neutral placeholders (no environment-specific catalog is committed), so "not found" is as
// environmental as "permission denied" here.
const ENVIRONMENTAL = new Set([
  'INSUFFICIENT_PERMISSIONS',
  'PERMISSION_DENIED',
  'TABLE_OR_VIEW_NOT_FOUND',
  'SCHEMA_NOT_FOUND',
  'CATALOG_NOT_FOUND',
]);
const codes = [...output.matchAll(/SQL ERR\s+([a-z0-9_]+)\s+([A-Z_]+)\s*$/gm)].map((m) => m[2]);
const onlyPermissionErrors = codes.length > 0 && codes.every((code) => ENVIRONMENTAL.has(code));

if (onlyPermissionErrors && committed.every((file) => existsSync(file))) {
  console.warn(
    '\n[typegen] WARNING: build principal lacks SELECT on the OBO-only gold and app tables; using committed types ' +
      `(${committed.join(', ')}). Regenerate locally with \`npm run typegen\` after changing a query.\n`,
  );
  process.exit(0);
}
process.exit(run.status ?? 1);
